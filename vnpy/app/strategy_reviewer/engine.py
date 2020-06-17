#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/8/20 0020 16:51
# @Author  : Hadrianl 
# @File    : engine


from vnpy.event import EventEngine, Event
from vnpy.trader.engine import BaseEngine, MainEngine
from vnpy.trader.event import (
    EVENT_TICK, EVENT_ORDER, EVENT_TRADE, EVENT_LOG)
from vnpy.trader.constant import (Direction, Offset, OrderType,Interval)
from vnpy.trader.object import (SubscribeRequest, OrderRequest, LogData, HistoryRequest, ContractData)
from collections import defaultdict
from vnpy.trader.database import database_manager


APP_NAME = "StrategyReviewer"


class StrategyReviewEngine(BaseEngine):
    """"""
    setting_filename = "strategy_review_setting.json"

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        """Constructor"""
        super().__init__(main_engine, event_engine, APP_NAME)


        self.init_engine()

    def init_engine(self):
        """"""
        # self.write_log("策略执行回顾引擎启动")
        self.strategies = {}

    def get_daily_history(self, symbol, exchange, start, end=None):
        req = HistoryRequest(symbol, exchange, start, end, Interval.DAILY)
        his_data = self.main_engine.query_history(req, 'IB')
        return his_data

    def get_all_strategies(self, start, end, skip=False):
        strategies = database_manager.get_all_strategy()
        strategy_dict = {}
        all_datas = []
        for n in strategies:
            datas = database_manager.load_trade_data(start, end, strategy=n)
            if datas:
                s = Strategy(n, datas, skip)
                all_datas.extend(s.raw_data)
                strategy_dict[n] = s
        else:
            # datas = database_manager.load_trade_data(start, end)
            s = Strategy('TOTAL', all_datas, skip)
            strategy_dict['TOTAL'] = s

        self.strategies = strategy_dict
        return strategy_dict

    def get_strategy_daily_settlements(self, name):
        strategy = self.strategies[name]

        ret = {}

        for symbol in strategy.datas:
            for date in strategy.datas[symbol]:
                trades = strategy.datas[symbol][date]
                settlement = DailySettlement(name)
                settlement.settlement(trades)
                ret[(settlement.vt_symbol, settlement.date)] = settlement

        return ret

class DailySettlement:
    def __init__(self, strategy, **kwargs):
        self.strategy = strategy
        self.vt_symbol = ''
        self.date = None
        self.net_pos = 0
        self.net_value = 0
        self.realizedPNL = 0
        self.holding_value = 0
        self.expose_trades = []
        self.trades = []
        self.trade_count = 0
        for k, v in kwargs:
            setattr(self, k, v)

    def settlement(self, trades, _from=None, _to=None):
        if len(trades) == 0:
            return

        self.date = trades[0].datetime.date()
        self.vt_symbol = trades[0].vt_symbol

        for t in trades:
            if self.date != t.datetime.date() or self.vt_symbol != t.vt_symbol:
                continue

            self.trades.append(t)
            self.expose_trades.append(t)
            self.trade_count += 1
            if t.direction == Direction.LONG:
                self.net_pos += t.volume
                self.net_value += t.price * t.volume
                self.holding_value += t.price * t.volume
            else:
                self.net_pos -= t.volume
                self.net_value -= t.price * t.volume
                self.holding_value -= t.price * t.volume

            if self.net_pos == 0:
                self.realizedPNL = -self.net_value
                self.holding_value = 0
                self.expose_trades.clear()

class Strategy:
    def __init__(self, name, datas, auto_skip_daily_opentrade=False):
        self.name = name
        self.raw_data = datas
        self._skip = auto_skip_daily_opentrade
        self.raw_data.sort(key=lambda d: d.datetime)
        self.datas = defaultdict(lambda :defaultdict(list))
        self.init_data(auto_skip_daily_opentrade)


    def init_data(self, skip):
        for d in self.raw_data:
            self.datas[d.vt_symbol][d.datetime.date()].append(d)

        if skip:
            for symbol, trades_groupby_date in self.datas.items():
                for date in list(trades_groupby_date.keys()):
                    trades = trades_groupby_date[date]
                    daily_pos = 0
                    daily_value = 0
                    for t in trades:
                        if t.direction == Direction.LONG:
                            daily_pos += t.volume
                            daily_value += t.price * t.volume
                        else:
                            daily_pos -= t.volume
                            daily_value -= t.price * t.volume
                    else:
                        if daily_pos != 0:
                            tls=trades_groupby_date.pop(date)

                            for t in tls:
                                self.raw_data.remove(t)

    @property
    def start_datetime(self):
        if len(self.raw_data) == 0:
            return

        return self.raw_data[0].datetime

    @property
    def end_datetime(self):
        if len(self.raw_data) == 0:
            return

        return self.raw_data[-1].datetime

    @property
    def trade_count(self):
        return len(self.raw_data)

    @property
    def cost(self):
        all_cost = []
        for vt_symbol, daily_trades in self.datas.items():
            net_pos = 0
            net_value = 0
            for date, tl in daily_trades.items():
                daily_pos = 0
                daily_value = 0
                for t in tl:
                    if t.direction == Direction.SHORT:
                        daily_pos -= t.volume
                        daily_value -= t.volume * t.price
                    else:
                        daily_pos += t.volume
                        daily_value += t.volume * t.price
                else:
                    net_pos += daily_pos
                    net_value += daily_value
            else:
                all_cost.append(f'#<{vt_symbol}>:{net_pos}@{net_value/net_pos if net_pos != 0 else net_value:.1f}  ')

        return '\n'.join(all_cost)