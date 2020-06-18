""""""

import importlib
import os
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from copy import copy
from tzlocal import get_localzone

from vnpy.event import Event, EventEngine, EVENT_TIMER
from vnpy.trader.engine import BaseEngine, MainEngine
from vnpy.trader.object import (
    OrderRequest,
    SubscribeRequest,
    HistoryRequest,
    LogData,
    TickData,
    BarData,
    ContractData
)
from vnpy.trader.event import (
    EVENT_TICK,
    EVENT_ORDER,
    EVENT_TRADE,
    EVENT_POSITION
)
from vnpy.trader.constant import (
    Direction,
    OrderType,
    Interval,
    Exchange,
    Offset,
    Status
)
from vnpy.trader.utility import load_json, save_json, extract_vt_symbol, round_to
from vnpy.trader.database import database_manager
from vnpy.trader.rqdata import rqdata_client

from .base import (
    APP_NAME,
    EVENT_CTA_LOG,
    EVENT_CTA_NOTIFY,
    EVENT_CTA_STRATEGY,
    EVENT_CTA_STOPORDER,
    EVENT_DAILY_CLOSE,
    EngineType,
    StopOrder,
    StopOrderStatus,
    STOPORDER_PREFIX
)
from .template import CtaTemplate
from .converter import OffsetConverter

import jpush


STOP_STATUS_MAP = {
    Status.SUBMITTING: StopOrderStatus.WAITING,
    Status.NOTTRADED: StopOrderStatus.WAITING,
    Status.PARTTRADED: StopOrderStatus.TRIGGERED,
    Status.ALLTRADED: StopOrderStatus.TRIGGERED,
    Status.CANCELLED: StopOrderStatus.CANCELLED,
    Status.REJECTED: StopOrderStatus.CANCELLED
}


class CtaEngine(BaseEngine):
    """"""

    engine_type = EngineType.LIVE  # live trading engine

    setting_filename = "ib_cta_strategy_setting.json"
    data_filename = "ib_cta_strategy_data.json"
    daily_close_filename = "dail_close_setting.json"

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        """"""
        super(CtaEngine, self).__init__(
            main_engine, event_engine, APP_NAME)

        self.strategy_setting = {}  # strategy_name: dict
        self.strategy_data = {}     # strategy_name: dict

        self.classes = {}           # class_name: stategy_class
        self.strategies = {}        # strategy_name: strategy

        self.symbol_strategy_map = defaultdict(
            list)                   # vt_symbol: strategy list
        self.orderid_strategy_map = {}  # vt_orderid: strategy
        self.strategy_orderid_map = defaultdict(
            set)                    # strategy_name: orderid list

        # self.stop_order_count = 0   # for generating stop_orderid
        # self.stop_orders = {}       # stop_orderid: stop_order

        self.init_executor = ThreadPoolExecutor(max_workers=1)

        self.vt_tradeids = set()    # for filtering duplicate trade

        self.offset_converter = OffsetConverter(self.main_engine)

        self.notifier = None

        self._lock = Lock()

        self.daily_close_setting = {}
        self._timer_count = 0

    def init_engine(self):
        """
        """
        self.init_notifier()
        self.load_strategy_class()
        self.load_strategy_setting()
        self.load_strategy_data()
        self.register_event()
        self.write_log("CTA策略引擎初始化成功")

    def close(self):
        """"""
        self.stop_all_strategies()

    def register_event(self):
        """"""
        self.event_engine.register(EVENT_TICK, self.process_tick_event)
        self.event_engine.register(EVENT_ORDER, self.process_order_event)
        self.event_engine.register(EVENT_TRADE, self.process_trade_event)
        self.event_engine.register(EVENT_POSITION, self.process_position_event)
        self.event_engine.register(EVENT_CTA_NOTIFY, self.process_notify_event)
        self.event_engine.register(EVENT_DAILY_CLOSE, self.process_daily_close_event)
        self.event_engine.register(EVENT_TIMER, self.process_timer_event)

    def init_notifier(self):
        from vnpy.trader.setting import get_settings
        push_settings = get_settings('notification.')
        if push_settings:
            krPush = jpush.JPush(push_settings['app_key'], push_settings['master_secret'])
            self.notifier = krPush.create_push()
            self.notifier.audience = jpush.all_
            self.notifier.platform = jpush.all_

    def process_tick_event(self, event: Event):
        """"""
        tick = event.data

        strategies = self.symbol_strategy_map[tick.vt_symbol]
        if not strategies:
            return

        # self.check_stop_order(tick)

        for strategy in strategies:
            if strategy.inited:
                self.call_strategy_func(strategy, strategy.on_tick, tick)

    def process_order_event(self, event: Event):
        """"""
        order = event.data

        self.offset_converter.update_order(order)

        strategy = self.orderid_strategy_map.get(order.vt_orderid, None)
        if not strategy:
            return

        # Remove vt_orderid if order is no longer active.
        vt_orderids = self.strategy_orderid_map[strategy.strategy_name]
        if order.vt_orderid in vt_orderids and not order.is_active():
            vt_orderids.remove(order.vt_orderid)

        # For server stop order, call strategy on_stop_order function
        if order.type == OrderType.STOP:
            so = StopOrder(
                vt_symbol=order.vt_symbol,
                direction=order.direction,
                offset=order.offset,
                price=order.price,
                volume=order.volume,
                stop_orderid=order.vt_orderid,
                strategy_name=strategy.strategy_name,
                status=STOP_STATUS_MAP.get(order.status, ""),
                vt_orderids=[order.vt_orderid],
            )
            self.call_strategy_func(strategy, strategy.on_stop_order, so)

        # Call strategy on_order function
        self.call_strategy_func(strategy, strategy.on_order, order)
        self.write_log(f'ORDER[{order.type.value}]<{order.vt_orderid}>:#{order.vt_symbol} {order.direction.value} {order.volume}@{order.price} -- {order.status}', strategy)

    def process_trade_event(self, event: Event):
        """"""
        trade = event.data

        # Filter duplicate trade push
        if trade.vt_tradeid in self.vt_tradeids:
            return
        self.vt_tradeids.add(trade.vt_tradeid)

        self.offset_converter.update_trade(trade)

        strategy = self.orderid_strategy_map.get(trade.vt_orderid, None)
        if not strategy:
            return

        # Update strategy pos before calling on_trade method
        if trade.direction == Direction.LONG:
            strategy.pos += trade.volume
        else:
            strategy.pos -= trade.volume

        self.call_strategy_func(strategy, strategy.on_trade, trade)

        # Sync strategy variables to data file
        self.sync_strategy_data(strategy)

        database_manager.save_trade_data([trade], strategy.strategy_name)

        # Update GUI
        self.put_strategy_event(strategy)
        self.write_log(f'TRADE<{trade.vt_tradeid}>:#{trade.vt_symbol} {trade.direction.value} {trade.volume}@{trade.price}', strategy)

    def process_position_event(self, event: Event):
        """"""
        position = event.data

        self.offset_converter.update_position(position)

    def process_notify_event(self, event: Event):
        notification = event.data.msg
        if self.notifier:
            self.notifier.notification = jpush.notification(alert=notification)
            try:
                response = self.notifier.send()
            except jpush.common.Unauthorized as unauth:
                self.write_log(f'KRPushUnauthorized: {unauth}')
            except jpush.common.APIConnectionException as conne:
                self.write_log(f'KRPushAPIConnectionException: {conne}')
            except jpush.common.JPushFailure as pushFail:
                self.write_log(f'KRPushFailure: {pushFail}')
            except Exception as e:
                self.write_log(f'KRPushException: {e}')
        else:
            self.write_log(f'KRPush未配置,无法推送->{notification}')

    def process_daily_close_event(self, event: Event):
        print(f'日内平仓测试{event}')
        # self.close_all_strategies_pos()

    def process_timer_event(self, event: Event):
        self._timer_count += 1

        if self._timer_count%3 == 0 and \
                self.daily_close_setting and \
                timedelta(seconds=-35) < datetime.now() - self.daily_close_setting['time'] < timedelta(seconds=-30):
            self.event_engine.put(Event(EVENT_DAILY_CLOSE))

        if self._timer_count < 600:
            return

        self._timer_count = 0
        self.load_daily_close_setting()

    def send_server_order(
        self,
        strategy: CtaTemplate,
        contract: ContractData,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        type: OrderType,
    ):
        """
        Send a new order to server.
        """
        # Create request and send order.
        original_req = OrderRequest(
            symbol=contract.symbol,
            exchange=contract.exchange,
            direction=direction,
            offset=offset,
            type=type,
            price=price,
            volume=volume,
            orderRef=strategy.strategy_name
        )

        # Convert with offset converter
        # req_list = self.offset_converter.convert_order_request(original_req, lock)
        req_list = [original_req]
        # Send Orders
        vt_orderids = []

        for req in req_list:
            req.reference = strategy.strategy_name      # Add strategy name as order reference

            vt_orderid = self.main_engine.send_order(
                req, contract.gateway_name)

            # Check if sending order successful
            if not vt_orderid:
                continue

            vt_orderids.append(vt_orderid)

            self.offset_converter.update_order_request(req, vt_orderid)

            # Save relationship between orderid and strategy.
            self.orderid_strategy_map[vt_orderid] = strategy
            self.strategy_orderid_map[strategy.strategy_name].add(vt_orderid)

        return vt_orderids

    def send_limit_order(
        self,
        strategy: CtaTemplate,
        contract: ContractData,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
    ):
        """
        Send a limit order to server.
        """
        return self.send_server_order(
            strategy,
            contract,
            direction,
            offset,
            price,
            volume,
            OrderType.LIMIT,
        )

    def send_server_stop_order(
        self,
        strategy: CtaTemplate,
        contract: ContractData,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
    ):
        """
        Send a stop order to server.

        Should only be used if stop order supported
        on the trading server.
        """
        return self.send_server_order(
            strategy,
            contract,
            direction,
            offset,
            price,
            volume,
            OrderType.STOP,
        )

    def cancel_server_order(self, strategy: CtaTemplate, vt_orderid: str):
        """
        Cancel existing order by vt_orderid.
        """
        order = self.main_engine.get_order(vt_orderid)
        if not order:
            self.write_log(f"撤单失败，找不到委托{vt_orderid}", strategy)
            return

        req = order.create_cancel_request()
        self.main_engine.cancel_order(req, order.gateway_name)

    def send_order(
        self,
        strategy: CtaTemplate,
        direction: Direction,
        offset: Offset,
        price: float,
        volume: float,
        stop: bool
    ):
        """
        """
        contract = self.main_engine.get_contract(strategy.vt_symbol)
        if not contract:
            self.write_log(f"委托失败，找不到合约：{strategy.vt_symbol}", strategy)
            return ""

        # Round order price and volume to nearest incremental value
        price = round_to(price, contract.pricetick)
        volume = round_to(volume, contract.min_volume)

        if stop:
            return self.send_server_stop_order(strategy, contract, direction, offset, price, volume)
        else:
            return self.send_limit_order(strategy, contract, direction, offset, price, volume)

    def cancel_order(self, strategy: CtaTemplate, vt_orderid: str):
        """
        """
        if vt_orderid.startswith(STOPORDER_PREFIX):
            self.cancel_local_stop_order(strategy, vt_orderid)
        else:
            self.cancel_server_order(strategy, vt_orderid)

    def cancel_all(self, strategy: CtaTemplate):
        """
        Cancel all active orders of a strategy.
        """
        vt_orderids = self.strategy_orderid_map[strategy.strategy_name]
        if not vt_orderids:
            return

        for vt_orderid in copy(vt_orderids):
            self.cancel_order(strategy, vt_orderid)

    def get_engine_type(self):
        """"""
        return self.engine_type

    def get_pricetick(self, strategy: CtaTemplate):
        """
        Return contract pricetick data.
        """
        contract = self.main_engine.get_contract(strategy.vt_symbol)

        if contract:
            return contract.pricetick
        else:
            return None

    def load_bar(
        self,
        vt_symbol: str,
        days: int,
        interval: Interval,
        callback: Callable[[BarData], None],
        use_database: bool
    ):
        """"""
        symbol, exchange = extract_vt_symbol(vt_symbol)
        end = datetime.now(get_localzone())
        start = end - timedelta(days)
        bars = []



        if not use_database:
            contract = self.main_engine.get_contract(vt_symbol)
            if not contract:
                self.write_log(f"load_bar失败，找不到合约：{vt_symbol}")
                return
            req = HistoryRequest(symbol, exchange, start=start, end=end, interval=interval)
            bars = self.main_engine.query_history(req, contract.gateway_name)
        else:
            ...

        for bar in bars:
            callback(bar)

    def load_tick(
        self,
        vt_symbol: str,
        days: int,
        callback: Callable[[TickData], None]
    ):
        """"""
        symbol, exchange = extract_vt_symbol(vt_symbol)
        end = datetime.now()
        start = end - timedelta(days)

        ticks = database_manager.load_tick_data(
            symbol=symbol,
            exchange=exchange,
            start=start,
            end=end,
        )

        for tick in ticks:
            callback(tick)

    def call_strategy_func(
        self, strategy: CtaTemplate, func: Callable, params: Any = None
    ):
        """
        Call function of a strategy and catch any exception raised.
        """
        try:
            if params:
                func(params)
            else:
                func()
        except Exception:
            strategy.trading = False
            strategy.inited = False

            msg = f"触发异常已停止\n{traceback.format_exc()}"
            self.write_log(msg, strategy)

    def add_strategy(
        self, class_name: str, strategy_name: str, vt_symbol: str, setting: dict
    ):
        """
        Add a new strategy.
        """
        if strategy_name in self.strategies:
            self.write_log(f"创建策略失败，存在重名{strategy_name}")
            return

        strategy_class = self.classes.get(class_name, None)
        if not strategy_class:
            self.write_log(f"创建策略失败，找不到策略类{class_name}")
            return

        strategy = strategy_class(self, strategy_name, vt_symbol, setting)
        self.strategies[strategy_name] = strategy

        # Add vt_symbol to strategy map.
        strategies = self.symbol_strategy_map[vt_symbol]
        strategies.append(strategy)

        # Update to setting file.
        self.update_strategy_setting(strategy_name, setting)

        self.put_strategy_event(strategy)

    def init_strategy(self, strategy_name: str):
        """
        Init a strategy.
        """
        self.init_executor.submit(self._init_strategy, strategy_name)

    def _init_strategy(self, strategy_name: str):
        """
        Init strategies in queue.
        """
        strategy = self.strategies[strategy_name]

        if strategy.inited:
            self.write_log(f"{strategy_name}已经完成初始化，禁止重复操作")
            return

        self.write_log(f"{strategy_name}开始执行初始化")

        # Call on_init function of strategy
        self.call_strategy_func(strategy, strategy.on_init)

        # Restore strategy data(variables)
        # data = self.strategy_data.get(strategy_name, None)
        # if data:
        #     for name in strategy.variables:
        #         value = data.get(name, None)
        #         if value:
        #             setattr(strategy, name, value)

        # Subscribe market data
        contract = self.main_engine.get_contract(strategy.vt_symbol)
        if contract:
            req = SubscribeRequest(
                symbol=contract.symbol, exchange=contract.exchange)
            self.main_engine.subscribe(req, contract.gateway_name)
        else:
            self.write_log(f"行情订阅失败，找不到合约{strategy.vt_symbol}", strategy)

        # Put event to update init completed status.
        strategy.inited = True
        self.put_strategy_event(strategy)
        self.write_log(f"{strategy_name}初始化完成")

    def start_strategy(self, strategy_name: str):
        """
        Start a strategy.
        """
        strategy = self.strategies[strategy_name]
        if not strategy.inited:
            self.write_log(f"策略{strategy.strategy_name}启动失败，请先初始化")
            return

        if strategy.trading:
            self.write_log(f"{strategy_name}已经启动，请勿重复操作")
            return
        self.write_log("策略启动", strategy)
        self.call_strategy_func(strategy, strategy.on_start)
        strategy.trading = True

        self.put_strategy_event(strategy)

    def recover_strategy(self, strategy_name: str):
        """
        Recover a strategy.
        """
        strategy = self.strategies[strategy_name]
        if not strategy.inited:
            self.write_log(f"策略{strategy.strategy_name}恢复失败，请先初始化")
            return

        if strategy.trading:
            self.write_log(f"{strategy_name}已经启动，请勿做恢复操作")
            return

        # Restore strategy data(variables)
        data = self.strategy_data.get(strategy_name, None)
        variables = {}
        if data:
            for name in strategy.variables:
                if name in ['inited', 'trading']:
                    continue
                variables[name] = data.get(name, None)

        self.recover_orders_and_trades()

        self.write_log("策略恢复", strategy)
        self.call_strategy_func(strategy, strategy.on_recover, variables)

        self.put_strategy_event(strategy)

    def stop_strategy(self, strategy_name: str):
        """
        Stop a strategy.
        """
        strategy = self.strategies[strategy_name]
        if not strategy.trading:
            return
        self.write_log("策略停止", strategy)
        # Call on_stop function of the strategy
        self.call_strategy_func(strategy, strategy.on_stop)

        # Change trading status of strategy to False
        strategy.trading = False

        # Cancel all orders of the strategy
        self.cancel_all(strategy)

        # Sync strategy variables to data file
        self.sync_strategy_data(strategy)

        # Update GUI
        self.put_strategy_event(strategy)

    def close_strategy_pos(self, strategy_name: str):
        strategy = self.strategies[strategy_name]
        if not strategy.trading:
            return

        # Cancel all orders of the strategy
        self.cancel_all(strategy)

        if strategy.pos != 0:
            tick = self.main_engine.get_tick(strategy.vt_symbol)
            if not tick:
                self.write_log(f"不存在Tick，请先订阅", strategy)
                return

            if strategy.pos > 0:
                strategy.send_order(Direction.SHORT, Offset.CLOSE, tick.last_price - 15, strategy.pos)
            else:
                strategy.send_order(Direction.LONG, Offset.CLOSE, tick.last_price + 15, -strategy.pos)

        self.sync_strategy_data(strategy)

        # Update GUI
        self.put_strategy_event(strategy)

    def edit_strategy(self, strategy_name: str, setting: dict):
        """
        Edit parameters of a strategy.
        """
        strategy = self.strategies[strategy_name]
        strategy.update_setting(setting)

        self.update_strategy_setting(strategy_name, setting)
        self.put_strategy_event(strategy)

    def modify_strategy_data(self, strategy_name: str, key: str, value):
        """

        Change parameters or variable of a straegy.
        """
        strategy = self.strategies[strategy_name]

        if not hasattr(strategy, key):
            self.write_log(f"策略{strategy.strategy_name}不存在字段：{key}")
            return

        _type = type(getattr(strategy, key))

        with self._lock:
            try:
                setattr(strategy, key, _type(value))
            except Exception as e:
                self.write_log(f"策略{strategy.strategy_name}设置{key}错误--{e}")

        self.put_strategy_event(strategy)

    def remove_strategy(self, strategy_name: str):
        """
        Remove a strategy.
        """
        strategy = self.strategies[strategy_name]
        if strategy.trading:
            self.write_log(f"策略{strategy.strategy_name}移除失败，请先停止")
            return

        # Remove setting
        self.remove_strategy_setting(strategy_name)

        # Remove from symbol strategy map
        strategies = self.symbol_strategy_map[strategy.vt_symbol]
        strategies.remove(strategy)

        # Remove from active orderid map
        if strategy_name in self.strategy_orderid_map:
            vt_orderids = self.strategy_orderid_map.pop(strategy_name)

            # Remove vt_orderid strategy map
            for vt_orderid in vt_orderids:
                if vt_orderid in self.orderid_strategy_map:
                    self.orderid_strategy_map.pop(vt_orderid)

        # Remove from strategies
        self.strategies.pop(strategy_name)

        return True

    def load_strategy_class(self):
        """
        Load strategy class from source code.
        """
        path1 = Path(__file__).parent.joinpath("strategies")
        self.load_strategy_class_from_folder(
            path1, "vnpy.app.ib_cta_strategy.strategies")

        path2 = Path.cwd().joinpath("strategies")
        self.load_strategy_class_from_folder(path2, "strategies")

    def recover_orders_and_trades(self):
        """
        recover strategy orders from open orders.
        """
        orders = self.main_engine.get_all_orders()

        for o in orders:
            if o.orderRef in self.strategies:
                self.orderid_strategy_map[o.vt_orderid] = self.strategies[o.orderRef]
                self.strategy_orderid_map[o.orderRef].add(o.vt_orderid)

        trades = self.main_engine.get_all_trades()

        for t in trades:
            if t.orderRef in self.strategies:
                database_manager.save_trade_data([t], t.orderRef)

    def load_strategy_class_from_folder(self, path: Path, module_name: str = ""):
        """
        Load strategy class from certain folder.
        """
        for dirpath, dirnames, filenames in os.walk(str(path)):
            for filename in filenames:
                if filename.split(".")[-1] in ("py", "pyd", "so"):
                    strategy_module_name = ".".join([module_name, filename.split(".")[0]])
                    self.load_strategy_class_from_module(strategy_module_name)

    def load_strategy_class_from_module(self, module_name: str):
        """
        Load strategy class from module file.
        """
        try:
            module = importlib.import_module(module_name)

            for name in dir(module):
                value = getattr(module, name)
                if (isinstance(value, type) and issubclass(value, CtaTemplate) and value is not CtaTemplate):
                    self.classes[value.__name__] = value
        except:  # noqa
            msg = f"策略文件{module_name}加载失败，触发异常：\n{traceback.format_exc()}"
            self.write_log(msg)

    def load_strategy_data(self):
        """
        Load strategy data from json file.
        """
        self.strategy_data = load_json(self.data_filename)

    def sync_strategy_data(self, strategy: CtaTemplate):
        """
        Sync strategy data into json file.
        """
        data = strategy.get_variables()
        data.pop("inited")      # Strategy status (inited, trading) should not be synced.
        data.pop("trading")

        self.strategy_data[strategy.strategy_name] = data
        save_json(self.data_filename, self.strategy_data)

    def get_all_strategy_class_names(self):
        """
        Return names of strategy classes loaded.
        """
        return list(self.classes.keys())

    def get_strategy_class_parameters(self, class_name: str):
        """
        Get default parameters of a strategy class.
        """
        strategy_class = self.classes[class_name]

        parameters = {}
        for name in strategy_class.parameters:
            parameters[name] = getattr(strategy_class, name)

        return parameters

    def get_strategy_parameters(self, strategy_name):
        """
        Get parameters of a strategy.
        """
        strategy = self.strategies[strategy_name]
        return strategy.get_parameters()

    def init_all_strategies(self):
        """
        """
        for strategy_name in self.strategies.keys():
            self.init_strategy(strategy_name)

    def start_all_strategies(self):
        """
        """
        for strategy_name in self.strategies.keys():
            self.start_strategy(strategy_name)

    def recover_all_strategies(self):
        """
        """
        for strategy_name in self.strategies.keys():
            self.recover_strategy(strategy_name)

    def stop_all_strategies(self):
        """
        """
        for strategy_name in self.strategies.keys():
            self.stop_strategy(strategy_name)

    def close_all_strategies_pos(self):
        """
        """
        for strategy_name in self.strategies.keys():
            self.close_strategy_pos(strategy_name)

    def load_strategy_setting(self):
        """
        Load setting file.
        """
        self.strategy_setting = load_json(self.setting_filename)

        for strategy_name, strategy_config in self.strategy_setting.items():
            self.add_strategy(
                strategy_config["class_name"],
                strategy_name,
                strategy_config["vt_symbol"],
                strategy_config["setting"]
            )

    def load_daily_close_setting(self):
        setting = load_json(self.daily_close_filename)

        if 'time' in setting:
            try:
                self.daily_close_setting = datetime.now().replace(hour=setting['time'][0], minute=setting['time'][1], second=0)
            except Exception as e:
                self.write_log(f"配置日内平仓错误：{e}")
        else:
            self.daily_close_setting = {}

    def update_strategy_setting(self, strategy_name: str, setting: dict):
        """
        Update setting file.
        """
        strategy = self.strategies[strategy_name]

        self.strategy_setting[strategy_name] = {
            "class_name": strategy.__class__.__name__,
            "vt_symbol": strategy.vt_symbol,
            "setting": setting,
        }
        save_json(self.setting_filename, self.strategy_setting)

    def remove_strategy_setting(self, strategy_name: str):
        """
        Update setting file.
        """
        if strategy_name not in self.strategy_setting:
            return

        self.strategy_setting.pop(strategy_name)
        save_json(self.setting_filename, self.strategy_setting)

    def put_stop_order_event(self, stop_order: StopOrder):
        """
        Put an event to update stop order status.
        """
        event = Event(EVENT_CTA_STOPORDER, stop_order)
        self.event_engine.put(event)

    def put_strategy_event(self, strategy: CtaTemplate):
        """
        Put an event to update strategy status.
        """
        data = strategy.get_data()
        event = Event(EVENT_CTA_STRATEGY, data)
        self.event_engine.put(event)

    def write_log(self, msg: str, strategy: CtaTemplate = None):
        """
        Create cta engine log event.
        """
        if strategy:
            msg = f"{strategy.strategy_name}: {msg}"

        log = LogData(msg=msg, gateway_name="CtaStrategy")
        event = Event(type=EVENT_CTA_LOG, data=log)
        self.event_engine.put(event)

    def send_notification(self, msg: str, strategy: CtaTemplate = None):
        """
        Create cta engine log event.
        """
        if strategy:
            msg = f"{strategy.strategy_name}: {msg}"

        log = LogData(msg=msg, gateway_name="CtaStrategy")
        event = Event(type=EVENT_CTA_NOTIFY, data=log)
        self.event_engine.put(event)

    def send_email(self, msg: str, strategy: CtaTemplate = None):
        """
        Send email to default receiver.
        """
        if strategy:
            subject = f"{strategy.strategy_name}"
        else:
            subject = "CTA策略引擎"

        self.main_engine.send_email(subject, msg)
