#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/8/20 0020 16:50
# @Author  : Hadrianl 
# @File    : widget


from vnpy.chart import ChartWidget, CandleItem, VolumeItem
from vnpy.trader.constant import Direction
from tzlocal import get_localzone
from vnpy.trader.ui import QtCore, QtWidgets, QtGui
from vnpy.trader.ui.widget import BaseMonitor, BaseCell, DirectionCell, EnumCell
from vnpy.trader.database import database_manager
import datetime as dt
from datetime import datetime
import pyqtgraph as pg
from vnpy.trader.engine import MainEngine
from vnpy.event import EventEngine
from vnpy.trader.object import HistoryRequest
from vnpy.trader.constant import Interval, Direction, Exchange
from vnpy.chart.base import BLACK_COLOR, CURSOR_COLOR, NORMAL_FONT
from collections import defaultdict
from ..engine import APP_NAME


class StrategyReviewer(QtWidgets.QWidget):
    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.review_engine = main_engine.get_engine(APP_NAME)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("策略执行回顾")
        self.resize(1100, 600)

        self.datetime_from = QtWidgets.QDateTimeEdit()
        self.datetime_to = QtWidgets.QDateTimeEdit()
        today = dt.date.today()
        self.datetime_from.setDateTime(dt.datetime(year=today.year, month=today.month, day=today.day))
        self.datetime_to.setDateTime(dt.datetime(year=today.year, month=today.month, day=today.day, hour=23, minute=59))
        # self.query_btn = QtWidgets.QPushButton("查询")
        self.skip_checkbox = QtWidgets.QCheckBox('AutoSkip')
        self.skip_checkbox.setToolTip('自动过滤未平仓订单')
        self.skip_checkbox.clicked.connect(self.update_strategy_data)
        self.datetime_from.editingFinished.connect(self.update_strategy_data)
        self.datetime_to.editingFinished.connect(self.update_strategy_data)
        # self.query_btn.clicked.connect(self.update_strategy_data)

        self.tab = QtWidgets.QTabWidget()
        self.strategy_monitor = StrategyMonitor(self.main_engine, self.event_engine)
        self.strategy_monitor.cellDoubleClicked.connect(self.show_trade_chart)
        # self.strategy_monitor.cellClicked.connect(self.check_strategies)
        self.strategy_monitor.resize(1000, 600)
        self.tab.addTab(self.strategy_monitor, '策略统计')

        self.trade = TradeChartDialog(self.main_engine, self.event_engine)

        time_hbox = QtWidgets.QHBoxLayout()
        time_hbox.addWidget(self.datetime_from, 3)
        time_hbox.addWidget(self.datetime_to, 3)
        time_hbox.addWidget(self.skip_checkbox, 1)
        # time_hbox.addWidget(self.query_btn, 1)

        vbox = QtWidgets.QVBoxLayout()
        vbox.addLayout(time_hbox)
        vbox.addWidget(self.tab)
        self.setLayout(vbox)

        self.update_strategy_data()

    def clear_data(self):
        """"""
        self.updated = False
        self.strategy_monitor.setRowCount(0)

    def update_strategy_data(self):
        start = self.datetime_from.dateTime().toPyDateTime()
        end = self.datetime_to.dateTime().toPyDateTime()
        skip=self.skip_checkbox.checkState()
        self.strategy_monitor.clearContents()
        self.strategy_monitor.setRowCount(0)
        self.strategies = self.review_engine.get_all_strategies(start, end, skip)
        self.update_data(self.strategies)
        self.strategy_monitor.resize_columns()


    def update_data(self, data: dict):
        """"""
        self.updated = True

        # data.reverse()
        for n, s in data.items():
            self.strategy_monitor.insert_new_row(s)

    def is_updated(self):
        """"""
        return self.updated

    def show_trade_chart(self, row, column):
        self.trade.clear_all()
        strategy_name = self.strategy_monitor.item(row, 0).text()
        # if strategy_name == 'TOTAL':
        #     strategy_name=None
        # strategy = self.review_engine.strategies[strategy_name]

        self.trade.update_daily_settlements(strategy_name)
        # self.trade.update_trades(strategy.raw_data, strategy_name)
        self.trade.showMaximized()

class CheckCell(BaseCell):
    def __init__(self, content, data):
        super().__init__(content, data)

    def set_content(self, content, data):
        self.setText(str(content))
        self._data = data
        # if self._data:
        self.setCheckState(QtCore.Qt.Checked)
        # else:
        #     self.setCheckState(QtCore.Qt.Unchecked)

class StrategyMonitor(BaseMonitor):
    sorting = True
    headers = {
        "name": {"display": "策略名称", "cell": BaseCell, "update": False},
        "start_datetime": {"display": "首次交易时间", "cell": BaseCell, "update": False},
        "end_datetime": {"display": "最后交易时间", "cell": BaseCell, "update": False},
        "trade_count": {"display": "交易次数", "cell": BaseCell, "update": False},
        "cost": {"display": "持仓成本", "cell": BaseCell, "update": False},
    }

class DailyMonitor(BaseMonitor):
    sorting = True
    headers = {
        "date": {"display": "交易日期", "cell": BaseCell, "update": False},
        "vt_symbol": {"display": "代码", "cell": BaseCell, "update": False},
        "trade_count": {"display": "交易次数", "cell": BaseCell, "update": False},
        "realizedPNL": {"display": "实现盈亏", "cell": BaseCell, "update": False},
        "strategy": {"display": "策略名称", "cell": BaseCell, "update": False},
    }

class TradeMonitor(BaseMonitor):
    """
    Monitor for trade data.
    """
    data_key = 'tradeid'
    sorting = True
    headers = {
        "tradeid": {"display": "成交号 ", "cell": CheckCell, "update": False},
        "orderid": {"display": "委托号", "cell": BaseCell, "update": False},
        "symbol": {"display": "代码", "cell": BaseCell, "update": False},
        "exchange": {"display": "交易所", "cell": EnumCell, "update": False},
        "direction": {"display": "方向", "cell": DirectionCell, "update": False},
        # "offset": {"display": "开平", "cell": EnumCell, "update": False},
        "price": {"display": "价格", "cell": BaseCell, "update": False},
        "volume": {"display": "数量", "cell": BaseCell, "update": False},
        "datetime": {"display": "时间", "cell": BaseCell, "update": False},
        "strategy": {"display": "策略", "cell": BaseCell, "update": False},
        # "gateway_name": {"display": "接口", "cell": BaseCell, "update": False},
    }

from vnpy.app.realtime_monitor.ui.baseQtItems import MarketDataChartWidget
class TradeChartDialog(QtWidgets.QDialog):
    def __init__(self, main_engine, event_engine, skip_opentrade=False):
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.review_engine = main_engine.get_engine(APP_NAME)
        self.history_data = None
        self._skip = skip_opentrade
        self.strategy = ""
        self.settlements = {}
        self.trade_datas = defaultdict(list)
        self.available_tradeid = set()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("策略交易明细")
        self.resize(900, 600)


        self.dailyChart = DailyMonitor(self.main_engine, self.event_engine)
        self.tradeChart = TradeMonitor(self.main_engine, self.event_engine)
        self.cost_text = QtWidgets.QTextEdit()
        self.candleChart = CandleChartDialog(self.main_engine, self.event_engine)

        hsplit = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        vsplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        vsplit.addWidget(self.tradeChart)
        vsplit.addWidget(self.cost_text)
        vsplit.addWidget(self.candleChart)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 1)
        vsplit.setStretchFactor(2, 6)

        hsplit.addWidget(self.dailyChart)
        hsplit.addWidget(vsplit)
        hsplit.setStretchFactor(0, 4)
        hsplit.setStretchFactor(1, 6)
        hbox = QtWidgets.QHBoxLayout()
        hbox.addWidget(hsplit)

        # hbox = QtWidgets.QHBoxLayout()
        # vbox = QtWidgets.QVBoxLayout()
        # vbox.addWidget(self.tradeChart, 8)
        # vbox.addWidget(self.cost_text, 2)
        # hbox.addWidget(self.dailyChart, 3)
        # hbox.addLayout(vbox, 7)
        self.setLayout(hbox)

        self.dailyChart.cellDoubleClicked.connect(self.update_daily_trades)
        # self.tradeChart.cellDoubleClicked.connect(self.show_candle_chart)
        self.tradeChart.cellClicked.connect(self.check_tradeid)

    # def update_trades(self, start, end, strategy=None):
    #     trade_data = database_manager.load_trade_data(start, end, strategy=strategy)
    #     self.strategy = strategy
    #     self.available_tradeid = set()
    #     for t in trade_data:
    #         self.trade_data[t.tradeid] = t
    #         self.tradeChart.insert_new_row(t)
    #         self.available_tradeid.add(t.tradeid)
    #
    #     self.show_cost()
    def update_daily_settlements(self, strategy):
        self.strategy = strategy
        self.dailyChart.clearContents()
        self.dailyChart.setRowCount(0)
        self.settlements = self.review_engine.get_strategy_daily_settlements(strategy)
        for _, s in self.settlements.items():
            self.dailyChart.insert_new_row(s)
        else:
            self.dailyChart.resize_columns()


    def update_daily_trades(self, r, c):
        date = self.dailyChart.item(r, 0).get_data().date
        vt_symbol = self.dailyChart.item(r, 1).text()

        settlement = self.settlements[(vt_symbol, date)]

        self.trade_datas = {}
        self.tradeChart.clearContents()
        self.available_tradeid = set()
        for t in settlement.trades:
            self.trade_datas[t.tradeid] = t
            self.tradeChart.insert_new_row(t)
            self.available_tradeid.add(t.tradeid)
        else:
            self.tradeChart.resize_columns()

        self.show_cost()
        self.show_candle_chart_by_daily_result(date, vt_symbol, self.trade_datas)

    def check_tradeid(self, r, c):
        if c == 0:
            cell = self.tradeChart.item(r, c)
            if cell.checkState():
                cell.setCheckState(QtCore.Qt.Unchecked)
                self.available_tradeid.remove(cell.text())
            else:
                cell.setCheckState(QtCore.Qt.Checked)
                self.available_tradeid.add(cell.text())

            self.show_cost()

    def show_cost(self):
        all_cost = defaultdict(lambda: [0, 0, 0])
        for t_id in self.available_tradeid:
            t = self.trade_datas[t_id]
            all_cost[t.vt_symbol][2] += 1
            if t.direction == Direction.SHORT:
                all_cost[t.vt_symbol][0] -= t.volume
                all_cost[t.vt_symbol][1] -= t.volume * t.price
            else:
                all_cost[t.vt_symbol][0] += t.volume
                all_cost[t.vt_symbol][1] += t.volume * t.price

        result = '\n'.join([f'#<{s}>:{p[0]}@{p[1] / p[0] if p[0] != 0 else p[1]:.1f} Total:{p[2]}' for s, p in all_cost.items()])
        self.cost_text.setText(result)

    def clear_all(self):
        self.strategy = ""
        self.trade_datas = {}
        self.tradeChart.clearContents()

    def show_candle_chart(self, row, column):
        self.candleChart.clear_all()
        tradeid = self.tradeChart.item(row, 0).text()
        symbol = self.trade_datas[tradeid].symbol
        exchange = self.trade_datas[tradeid].exchange
        trade_datas = [t for t in self.trade_datas.values() if t.symbol == symbol and t.exchange == exchange and t.tradeid in self.available_tradeid]
        trade_datas.sort(key=lambda t:t.datetime)
        time = self.trade_datas[tradeid].datetime
        start = time.replace(hour=0, minute=0, second=0) - dt.timedelta(minutes=120)
        # end = min(time.replace(hour=23, minute=59, second=59) + dt.timedelta(minutes=120),
        #           dt.datetime.now())

        self.candleChart.update_all(symbol, exchange, trade_datas, start)

        # self.candleChart.show()

    def show_candle_chart_by_daily_result(self, date, vt_symbol, trade_datas):
        self.candleChart.clear_all()

        # trade_datas.sort(key=lambda t:t.time)
        start = dt.datetime(year=date.year, month=date.month, day=date.day,
                            hour=0, minute=0, second=0) - dt.timedelta(minutes=120)
        end = min(dt.datetime(year=date.year, month=date.month, day=date.day,
                            hour=23, minute=59, second=0) + dt.timedelta(minutes=120),
                  dt.datetime.now())

        symbol, exchange = vt_symbol.split('.')
        self.candleChart.update_all(symbol, Exchange(exchange),
                                    [t for _, t in trade_datas.items()],
                                    start, end)

        # self.candleChart.show()

    def closeEvent(self, QCloseEvent):
        super().closeEvent(QCloseEvent)

        self.tradeChart.clearContents()
        self.cost_text.clear()
        self.candleChart.clear_all()


class CandleChartDialog(QtWidgets.QDialog):
    def __init__(self,  main_engine, event_engine,):
        """"""
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.last_end = dt.datetime(1970, 1, 1)
        self._interval = Interval.MINUTE
        self._symbol = None
        self._exchange = None
        self._start = None
        self._end = None
        self.trade_datas = []
        self.init_ui()

    def init_ui(self):
        """"""
        self.setWindowTitle("策略K线图表")

        # Create chart widget
        self.chart = MarketDataChartWidget()
        self.indicator_combo = QtWidgets.QComboBox()
        self.indicator_combo.addItems(self.chart.indicators.keys())
        self.indicator_combo.currentTextChanged.connect(self.chart.change_indicator)

        self.interval_combo = QtWidgets.QComboBox()
        for i in Interval:
            self.interval_combo.addItem(i.value, i)
        self.interval_combo.setCurrentText(Interval.MINUTE.value)

        self.forward_btn = QtWidgets.QPushButton('←')

        self.interval_combo.currentIndexChanged.connect(self.change_interval)
        self.forward_btn.clicked.connect(self.forward)
        self.chart.signal_new_bar_request.connect(self.update_backward_bars)

        # Set layout
        hbox = QtWidgets.QHBoxLayout()
        hbox.addWidget(self.indicator_combo)
        hbox.addWidget(self.interval_combo)
        hbox.addWidget(self.forward_btn)
        vbox = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox)
        vbox.addWidget(self.chart)
        self.setLayout(vbox)

    def change_interval(self, interval):
        old_tp = self.interval2timdelta(self._interval)
        self._interval = self.interval_combo.itemData(interval)
        new_tp = self.interval2timdelta(self._interval)
        symbol = self._symbol
        exchange = self._exchange
        trade_datas = self.trade_datas
        if new_tp > old_tp:
            start = self._start
            end = self._end
        else:
            cur_bar = self.chart._manager.get_bar(self.chart._cursor._x)
            start = cur_bar.datetime
            end=None

        self.clear_all()
        self.update_all(symbol, exchange, trade_datas, start, end)

    def update_all(self, symbol, exchange, trade_datas, start, end=None):
        self._symbol = symbol
        self._exchange = exchange
        self._start = start
        interval = self._interval
        tp = self.interval2timdelta(self._interval)

        backward_n = max(60 * tp, dt.timedelta(hours=25))
        end = start + backward_n if end is None else end
        history_data = database_manager.load_bar_data(symbol, exchange, interval, start=start, end=end)
        self.trade_datas = trade_datas

        if len(history_data) > 0 and len(history_data)/ ((end - start).total_seconds() / 60) > 0.7:
            self.chart.update_all(history_data, trade_datas, [])
        else:
            req = HistoryRequest(symbol, exchange, start, end, interval)
            gateway = self.main_engine.get_gateway('IB')
            if gateway and gateway.api.status:
                self.history_data = history_data = gateway.query_history(req)
                self.chart.update_all(history_data, trade_datas, [])
            database_manager.save_bar_data(history_data)

        if len(getattr(self, 'history_data', [])) >0:
            self._end = self.history_data[-1].datetime

    def forward(self):
        start = self._start
        symbol = self._symbol
        exchange = self._exchange
        interval = self._interval
        end = self._end

        if all([symbol, exchange, interval, start, end]):
            tp = self.interval2timdelta(interval)
            forward_n = max(60 * tp, dt.timedelta(hours=25))
            self._start = start - forward_n
            self.chart.clear_all()
            self.update_all(symbol, exchange, self.trade_datas, self._start, end)

    def clear_all(self):
        self._symbol = None
        self._exchange = None
        self._start = None
        self._end = None
        self.trade_datas = []
        self.chart.clear_all()

    def update_backward_bars(self, n):
        chart = self.chart
        last_bar = chart._manager.get_bar(chart.last_ix)
        if last_bar:
            symbol = last_bar.symbol
            exchange = last_bar.exchange
            if self._end:
                start = max(last_bar.datetime, self._end)
            else:
                start = last_bar.datetime


            if start >= dt.datetime.now(get_localzone()):
                return

            tp = self.interval2timdelta(self._interval)
            backward_n = max(tp * n, dt.timedelta(minutes=60))
            end = start + backward_n
            if not self.checkTradeTime(end.time()):
                history_data = database_manager.load_bar_data(symbol, exchange, self._interval, start=start, end=end)

                if len(history_data) == 0 or len(history_data) / ((end - start).total_seconds() / 60) < 0.7:
                    req = HistoryRequest(symbol, exchange, start, end, self._interval)
                    gateway = self.main_engine.get_gateway('IB')
                    if gateway and gateway.api.status:
                        history_data = gateway.query_history(req)
                    database_manager.save_bar_data(history_data)

                for bar in history_data:
                    self.chart.update_bar(bar)

                last_bar_after_update = chart._manager.get_bar(chart.last_ix)
                self.chart.clear_trades()
                self.chart.update_trades([t for t in self.trade_datas if t.datetime <= last_bar_after_update.datetime])
                self.chart.update_pos()
                self.chart.update_pnl()

            self._end = end

    @staticmethod
    def checkTradeTime(t):
        TRADINGHOURS = [(dt.time(3, 0), dt.time(9, 15)),
                        (dt.time(12, 0), dt.time(13, 0)),
                        (dt.time(16, 30), dt.time(17, 15))]
        for tp in TRADINGHOURS:
            if tp[0] <= t < tp[1]:
                return True

        return False

    @staticmethod
    def interval2timdelta(interval):
        return {Interval.MINUTE: dt.timedelta(minutes=1), Interval.HOUR: dt.timedelta(hours=1),
                  Interval.DAILY: dt.timedelta(days=1), Interval.WEEKLY: dt.timedelta(weeks=1)}[interval]

    # def update_all(self, history, trades, orders):
    #     self.chart.update_all(history, trades, orders)


class DailyResultChart(QtWidgets.QDialog):
    def __init__(self):
        """"""
        super().__init__()
        self.init_ui()

    def init_ui(self):
        """"""
        self.setWindowTitle("策略K线图表")
        self.resize(1400, 800)

        # Create chart widget
        self.pnlChart = pg.PlotCurveItem()
        # Set layout
        vbox = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.pnlChart)
        self.setLayout(vbox)

    def clear_all(self):
        self.pnlChart.clear()

    # def update_all(self, history, trades, orders):
    #     self.chart.update_all(history, trades, orders)

