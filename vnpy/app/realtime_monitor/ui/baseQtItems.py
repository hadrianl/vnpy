#!/usr/bin/python
# -*- coding:utf-8 -*-

"""
@author:Hadrianl
THANKS FOR th github project https://github.com/moonnejs/uiKLine
"""


import numpy as np
import pandas as pd
import pyqtgraph as pg
import datetime as dt

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5 import QtGui, QtCore
from pyqtgraph.Point import Point
from tzlocal import get_localzone

# DEFAULT_MA = [5, 10, 30, 60]

from vnpy.chart.item import ChartItem, CandleItem, VolumeItem
from vnpy.chart.manager import BarManager
from vnpy.chart.widget import ChartWidget
from vnpy.trader.object import BarData, TickData, TradeData, OrderData
from vnpy.trader.constant import Direction, Status, Interval
from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, UP_COLOR, DOWN_COLOR, CURSOR_COLOR, BLACK_COLOR, NORMAL_FONT
from vnpy.trader.utility import ArrayManager, BarGenerator
from typing import Tuple, Callable
from collections import defaultdict
from vnpy.trader.ui.widget import BaseMonitor, TimeCell, BaseCell
from vnpy.app.realtime_monitor.ui.indicatorQtItems import INDICATOR
from vnpy.app.realtime_monitor.ui.indicatorQtItems import PNLCurveItem
import talib
from contextlib import contextmanager


class TickSaleMonitor(BaseMonitor):
    headers = {
        "datetime": {"display": "时间", "cell": TimeCell, "update": False},
        "last_price": {"display": "价格", "cell": BaseCell, "update": False},
        "last_volume": {"display": "现手", "cell": BaseCell, "update": False},
    }

    def unregister_event(self):
        self.signal.disconnect(self.process_event)
        self.event_engine.unregister(self.event_type, self.signal.emit)

    def clear_all(self):
        self.cells = {}
        self.clearContents()


class InfoWidget(QFormLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.symbol_line = QLabel(" " * 30)
        self.symbol_line.setStyleSheet('color: rgb(255, 6, 10)')


        self.ask_line = QLabel(" " * 20)
        self.ask_line.setStyleSheet('color: rgb(255, 255, 255);\nbackground-color: rgb(0, 255, 50);')
        self.bid_line = QLabel(" " * 20)
        self.bid_line.setStyleSheet('color: rgb(255, 255, 255);\nbackground-color: rgb(255, 0, 0);')

        self.addRow(self.symbol_line)
        self.addRow("卖出", self.ask_line)
        self.addRow("买入", self.bid_line)

    def update_tick(self, tick: TickData):
        self.symbol_line.setText(tick.vt_symbol)
        self.ask_line.setText(f'{tick.ask_volume_1}@{tick.ask_price_1}')
        self.bid_line.setText(f'{tick.bid_volume_1}@{tick.bid_price_1}')

    def clear_all(self):
        self.symbol_line.setText("")
        self.ask_line.setText("")
        self.bid_line.setText("")

class MarketDataChartWidget(ChartWidget):
    signal_new_bar_request = QtCore.pyqtSignal(int)
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.dt_ix_map = {}
        self.last_ix = -1
        self.ix_trades_map = defaultdict(list)
        self.ix_pos_map = defaultdict(lambda :(0, 0))
        self.ix_holding_pos_map = defaultdict(lambda :(0, 0))
        self.vt_symbol = None
        self.bar = None
        self.last_tick = None
        self._updated = True
        self.indicators = {i.name: i for i in INDICATOR if i.plot_name == 'indicator'}
        self.current_indicator = list(self.indicators.keys())[0]
        self.init_chart_ui()

    def init_chart_ui(self):
        self.add_plot("candle", hide_x_axis=True, minimum_height=200)
        self.add_plot("indicator", hide_x_axis=True, maximum_height=120)
        self.add_plot("pnl", hide_x_axis=True, maximum_height=80)
        self.add_plot("volume", maximum_height=100)

        self.get_plot("candle").showGrid(True, True)
        self.get_plot("indicator").showGrid(True, True)
        self.get_plot("pnl").showGrid(True, True)
        self.get_plot("volume").showGrid(True, True)

        self.add_item(CandleItem, "candle", "candle")

        for i in INDICATOR:
            if i.plot_name == 'candle':
                self.add_item(i, i.name, i.plot_name)

        ind = self.indicators[self.current_indicator]
        self.add_item(ind, ind.name, ind.plot_name)
        self.add_item(PNLCurveItem, PNLCurveItem.name, PNLCurveItem.plot_name)
        self.add_item(VolumeItem, "volume", "volume")
        self.add_cursor()

        self.init_trade_scatter()
        self.init_last_tick_line()
        self.init_order_lines()
        self.init_trade_info()
        self.init_splitLine()

    def init_trade_scatter(self):
        self.trade_scatter = pg.ScatterPlotItem()
        candle_plot = self.get_plot("candle")
        candle_plot.addItem(self.trade_scatter)

    def init_last_tick_line(self):
        self.last_tick_line = pg.InfiniteLine(angle=0, label='')
        candle_plot = self.get_plot("candle")
        candle_plot.addItem(self.last_tick_line)

    def init_order_lines(self):
        self.order_lines = defaultdict(pg.InfiniteLine)

    def init_trade_info(self):
        self.trade_info = pg.TextItem(
                "info",
                anchor=(1, 0),
                color=CURSOR_COLOR,
                border=CURSOR_COLOR,
                fill=BLACK_COLOR
            )
        self.trade_info.hide()
        self.trade_info.setZValue(2)
        self.trade_info.setFont(NORMAL_FONT)

        candle_plot = self.get_plot("candle")
        candle_plot.addItem(self.trade_info)

        self.scene().sigMouseMoved.connect(self.show_trade_info)

    def change_indicator(self, indicator):
        indicator_plot = self.get_plot("indicator")
        if self.current_indicator:
            for item in indicator_plot.items:
                if isinstance(item, ChartItem):
                    indicator_plot.removeItem(item)
                    self._items.pop(self.current_indicator)
                    self._item_plot_map.pop(item)

        self.current_indicator = indicator
        self.add_item(self.indicators[indicator], indicator, "indicator")

        self._items[self.current_indicator].update_history(self._manager.get_all_bars())

    def show_trade_info(self, evt: tuple) -> None:
        info = self.trade_info
        info.hide()
        trades = self.ix_trades_map[self._cursor._x]
        pos = self.ix_pos_map[self._cursor._x]
        holding_pos = self.ix_holding_pos_map[self._cursor._x]
        pos_info_text = f'Pos: {pos[0]}@{pos[1]/pos[0] if pos[0] != 0 else pos[1]:.1f}'
        holding_pos_text = f'Holding: {holding_pos[0]}@{holding_pos[1]/holding_pos[0] if holding_pos[0] != 0 else holding_pos[1]:.1f}'
        trade_info_text = '\n'.join(f'{t.datetime}: {"↑" if t.direction == Direction.LONG else "↓"}{t.volume}@{t.price:.1f}' for t in trades)
        info.setText('\n'.join([pos_info_text, holding_pos_text, trade_info_text]))
        view = self._cursor._views['candle']
        rect = view.sceneBoundingRect()
        top_middle = view.mapSceneToView(QPointF(rect.right() - rect.width()/2, rect.top()))
        info.setPos(top_middle)
        info.show()

    def update_all(self, history, trades, orders):
        self.update_history(history)
        self.update_trades(trades)
        self.update_orders(orders)
        self.update_pos()
        self.update_pnl()

    def update_history(self, history: list):
        """"""
        with self.updating():
            super().update_history(history)

            if len(history) == 0:
                return

            for ix, bar in enumerate(history):
                self.dt_ix_map[bar.datetime] = ix
            else:
                self.last_ix = ix

    def update_tick(self, tick: TickData):
        """
        Update new tick data into generator.
        """
        new_minute = False

        # Filter tick data with 0 last price
        if not tick.last_price:
            return

        if not self.bar or self.bar.datetime.minute != tick.datetime.minute:
            new_minute = True

        if new_minute:
            self.bar = BarData(
                symbol=tick.symbol,
                exchange=tick.exchange,
                interval=Interval.MINUTE,
                datetime=tick.datetime.replace(second=0),
                gateway_name=tick.gateway_name,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
                open_interest=tick.open_interest
            )
        else:
            self.bar.high_price = max(self.bar.high_price, tick.last_price)
            self.bar.low_price = min(self.bar.low_price, tick.last_price)
            self.bar.close_price = tick.last_price
            self.bar.open_interest = tick.open_interest
            # self.bar.datetime = tick.datetime

        if self.last_tick:
            volume_change = tick.volume - self.last_tick.volume
            self.bar.volume += max(volume_change, 0)

        self.last_tick = tick
        self.update_bar(self.bar)

    def clear_tick(self):
        self.last_tick = None
        self.last_tick_line.setPos(0)

    def update_bar(self, bar: BarData) -> None:
        if bar.datetime not in self.dt_ix_map:
            self.last_ix += 1
            self.dt_ix_map[bar.datetime] = self.last_ix
            self.ix_pos_map[self.last_ix] = self.ix_pos_map[self.last_ix - 1]
            self.ix_holding_pos_map[self.last_ix] = self.ix_holding_pos_map[self.last_ix - 1]
            super().update_bar(bar)
        else:
            candle = self._items.get('candle')
            volume = self._items.get('volume')
            if candle:
                candle.update_bar(bar)

            if volume:
                volume.update_bar(bar)

    def clear_bars(self):
        self.vt_symbol = None
        self.dt_ix_map.clear()
        self.last_ix = -1

    def update_trades(self, trades: list):
        """"""
        trade_scatters = []
        for trade in trades:

            for _dt, ix in self.dt_ix_map.items():
                if trade.datetime < _dt:
                    self.ix_trades_map[ix - 1].append(trade)
                    scatter = self.__trade2scatter(ix - 1, trade)
                    trade_scatters.append(scatter)
                    break

        self.trade_scatter.setData(trade_scatters)

    def update_trade(self, trade: TradeData):
        ix = self.dt_ix_map.get(trade.datetime.replace(second=0))
        if ix is not None:
            self.ix_trades_map[ix].append(trade)
            scatter = self.__trade2scatter(ix, trade)
            self.__trade2pos(ix, trade)
            self.trade_scatter.addPoints([scatter])

        for _dt, ix in self.dt_ix_map.items():
            if trade.datetime < _dt:
                self.ix_trades_map[ix - 1].append(trade)
                scatter = self.__trade2scatter(ix - 1, trade)
                self.__trade2pos(ix-1, trade)
                self.trade_scatter.addPoints([scatter])
                break

    def clear_trades(self):
        self.trade_scatter.clear()
        self.ix_trades_map = defaultdict(list)

    def update_orders(self, orders: list):
        for o in orders:
            self.update_order(o)

    def __trade2scatter(self, ix, trade: TradeData):
        scatter = {
            "pos": (ix, trade.price),
            "data": 1,
            "size": 14,
            "pen": pg.mkPen((255, 255, 255))
        }

        if trade.direction == Direction.LONG:
            scatter["symbol"] = "t1"
            scatter["brush"] = pg.mkBrush((255, 255, 0))
        else:
            scatter["symbol"] = "t"
            scatter["brush"] = pg.mkBrush((0, 0, 255))

        return scatter

    def __trade2pos(self, ix, trade: TradeData):
        if trade.direction == Direction.LONG:
            p = trade.volume
            v = trade.volume * trade.price
        else:
            p = -trade.volume
            v = -trade.volume * trade.price
        self.ix_pos_map[ix] = (self.ix_pos_map[ix][0] + p, self.ix_pos_map[ix][1] + v)

        if self.ix_pos_map[ix][0] == 0:
            self.ix_holding_pos_map[ix] = (0, 0)
        else:
            self.ix_holding_pos_map[ix] = (self.ix_holding_pos_map[ix][0] + p, self.ix_holding_pos_map[ix][1] + v)

    def update_order(self, order: OrderData):
        if order.status in (Status.NOTTRADED, Status.PARTTRADED):
            line = self.order_lines[order.vt_orderid]
            candle_plot = self.get_plot("candle")

            if line not in candle_plot.items:
                candle_plot.addItem(line)

            line.setAngle(0)
            line.label = pg.InfLineLabel(line,
                                         text=f'{order.type.value}:{"↑" if order.direction == Direction.LONG else "↓"}{order.volume - order.traded}@{order.price}',
                                         color='r' if order.direction == Direction.LONG else 'g')
            line.setPen(pg.mkPen(color=UP_COLOR if order.direction == Direction.LONG else DOWN_COLOR, width=PEN_WIDTH))
            line.setHoverPen(pg.mkPen(color=UP_COLOR if order.direction == Direction.LONG else DOWN_COLOR, width=PEN_WIDTH * 2))
            line.setPos(order.price)

        elif order.status in (Status.ALLTRADED, Status.CANCELLED, Status.REJECTED):
            if order.vt_orderid in self.order_lines:
                line = self.order_lines[order.vt_orderid]
                candle_plot = self.get_plot("candle")
                candle_plot.removeItem(line)

    def clear_orders(self):
        candle_plot = self.get_plot("candle")
        for _, l in self.order_lines.items():
            candle_plot.removeItem(l)

        self.order_lines.clear()

    def update_tick_line(self, tick: TickData):
        c = tick.last_price
        o = self.bar.close_price if self.bar else c
        self.last_tick_line.setPos(c)
        if c >= o:
            self.last_tick_line.setPen(pg.mkPen(color=UP_COLOR, width=PEN_WIDTH/2))
            self.last_tick_line.label.setText(str(c), color=(255, 69, 0))
        else:
            self.last_tick_line.setPen(pg.mkPen(color=DOWN_COLOR, width=PEN_WIDTH / 2))
            self.last_tick_line.label.setText(str(c), color=(173, 255, 47))

    def update_pos(self):
        net_p = 0
        net_value = 0
        holding_value = 0
        for ix in self.dt_ix_map.values():
            trades = self.ix_trades_map[ix]
            for t in trades:
                if t.direction == Direction.LONG:
                    net_p += t.volume
                    net_value += t.volume * t.price
                    holding_value += t.volume * t.price
                else:
                    net_p -= t.volume
                    net_value -= t.volume * t.price
                    holding_value -= t.volume * t.price
            else:
                if net_p == 0:
                    holding_value = 0
            self.ix_pos_map[ix] = (net_p, net_value)
            self.ix_holding_pos_map[ix] = (net_p, holding_value)

    def clear_pos(self):
        self.ix_pos_map = defaultdict(lambda :(0, 0))
        self.ix_holding_pos_map = defaultdict(lambda :(0, 0))

    def update_pnl(self):
        pnl_plot = self._plots.get('pnl')
        pnl_item = self._items.get('pnl')
        if pnl_plot and pnl_item:
            pnl_item.clear_all()
            pnl_item.set_ix_pos_map(self.ix_pos_map)
            pnl_item.update_history(self._manager.get_all_bars())

            min_value, max_value = pnl_item.get_y_range()

            pnl_plot.setLimits(
                xMin=-1,
                xMax=self._manager.get_count(),
                yMin=min_value,
                yMax=max_value
            )


    def init_splitLine(self):
        self.splitLines = []

    def add_splitLine(self, split_dt, style=None, offset=-0.5):
        candle = self.get_plot('candle')
        ix = self.dt_ix_map.get(split_dt, None)
        if candle and ix is not None:
            sl = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color='r', width=1.5, style=style if style else QtCore.Qt.DashDotLine))
            sl.setPos(ix + offset)
            candle.addItem(sl)
            self.splitLines.append(sl)

    def clear_splitLine(self):
        candle = self.get_plot('candle')
        if candle:
            for l in self.splitLines:
                candle.removeItem(l)
            else:
                self.splitLines.clear()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """
        Reimplement this method of parent to move chart horizontally and zoom in/out.
        """
        super().keyPressEvent(event)

        if event.key() == QtCore.Qt.Key_PageUp:
            self._on_key_pageUp()
        elif event.key() == QtCore.Qt.Key_PageDown:
            self._on_key_pageDown()

    def _on_key_pageUp(self):
        x = self._cursor._x
        while x <= self._right_ix:
            x += 1
            if self.ix_trades_map.get(x):
                self._cursor.move_to(x)
                self.show_trade_info(tuple())
                break

    def _on_key_pageDown(self):
        x = self._cursor._x
        while x >= 0:
            x -= 1
            if self.ix_trades_map.get(x):
                self._cursor.move_to(x)
                self.show_trade_info(tuple())
                break

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)

        if ev.buttons() != Qt.LeftButton:
            return

        last_x = self._mouse_last_x
        cur_x = ev.x()
        self._mouse_last_x = ev.x()
        offset = last_x - cur_x
        if self.is_updated() and offset >= 15 and self._right_ix >= self.last_ix:
            self.signal_new_bar_request.emit(offset)

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)

        if ev.buttons() != Qt.LeftButton:
            return

        self._mouse_last_x = ev.x()

    # def mouseReleaseEvent(self, ev):
    #     super().mouseReleaseEvent(ev)
    #
    #     if ev.buttons() != Qt.LeftButton:
    #         return
    #
    #     self._mouse_last_x = None
    #     self._allow_new_bar_request = False

    def is_updated(self):
        return self._updated

    @contextmanager
    def updating(self):
        self._updated = False
        yield self
        self._updated = True

    def clear_all(self) -> None:
        """"""
        super().clear_all()
        self.clear_bars()
        self.clear_trades()
        self.clear_pos()
        self._updated = True

        self.clear_orders()
        self.clear_tick()
        self.clear_splitLine()