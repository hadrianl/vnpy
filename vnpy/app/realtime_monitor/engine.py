#!/usr/bin/python
# -*- coding:utf-8 -*-

"""
@author:Hadrianl

"""

from vnpy.event import EventEngine, Event
from vnpy.trader.engine import BaseEngine, MainEngine
from vnpy.trader.event import (
    EVENT_TICK, EVENT_ORDER, EVENT_TRADE, EVENT_LOG, EVENT_CONTRACT)
from vnpy.trader.constant import (Direction, Offset, OrderType,Interval)
from vnpy.trader.object import (SubscribeRequest, OrderRequest, LogData, HistoryRequest)
from vnpy.trader.utility import load_json, save_json
import datetime as dt
from tzlocal import get_localzone



APP_NAME = "Visulization"

class VisualEngine(BaseEngine):
    """"""
    setting_filename = "visual_setting.json"

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        """Constructor"""
        super().__init__(main_engine, event_engine, APP_NAME)
        self.bar_generator = None
        self.first = True
        self.init_engine()

    def init_engine(self):
        """"""
        self.write_log("市场数据可视化引擎启动")

    def get_tick(self, vt_symbol: str):
        """"""
        tick = self.main_engine.get_tick(vt_symbol)

        if not tick:
            self.write_log(f"查询行情失败，找不到行情：{vt_symbol}")

        return tick

    def get_contract(self, vt_symbol: str):
        """"""
        contract = self.main_engine.get_contract(vt_symbol)

        if not contract:
            self.write_log(f"查询合约失败，找不到合约：{vt_symbol}")

        return contract

    def write_log(self, msg: str):
        """"""

        event = Event(EVENT_LOG)
        log = LogData(msg=msg, gateway_name='IB')
        event.data = log
        self.event_engine.put(event)

    def get_historical_data(self, contract, end, bar_count, interval):
        total_minutes = {Interval.MINUTE: 1, Interval.HOUR: 60}[interval] * bar_count
        start = (end if end else dt.datetime.now(get_localzone())) - dt.timedelta(minutes=total_minutes)
        req = HistoryRequest(contract.symbol, contract.exchange,
                             start=start,
                             end=end,
                             interval=interval)

        his_data = self.main_engine.query_history(req, contract.gateway_name)

        return his_data

    def get_trades(self, contract):
        return [t for t in self.main_engine.get_all_trades() if t.vt_symbol == contract.vt_symbol]

    def get_orders(self, contract):
        return [o for o in self.main_engine.get_all_orders() if o.vt_symbol == contract.vt_symbol]

    def close(self):
        ...



