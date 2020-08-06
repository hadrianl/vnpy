#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2019/9/3 0003 13:01
# @Author  : Hadrianl 
# @File    : indicatorQtItems

import numpy as np
import pyqtgraph as pg
import datetime as dt

from PyQt5 import QtGui, QtCore

# DEFAULT_MA = [5, 10, 30, 60]

from vnpy.chart.item import ChartItem
from vnpy.chart.manager import BarManager
from vnpy.trader.object import BarData, TickData, TradeData, OrderData
from vnpy.trader.constant import Direction, Status, Interval
from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, UP_COLOR, DOWN_COLOR, CURSOR_COLOR, BLACK_COLOR, NORMAL_FONT
from vnpy.trader.utility import ArrayManager, BarGenerator
from typing import Tuple, Callable
from collections import defaultdict
from vnpy.trader.utility import load_json
from dateutil import parser

import talib


class MACurveItem(ChartItem):
    name = 'ma'
    plot_name = 'candle'
    MA_PARAMS = [5, 10, 20, 30, 60]
    MA_COLORS = {5: pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH),
                 10: pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH),
                 20: pg.mkPen(color=(218, 112, 214), width=PEN_WIDTH),
                 30: pg.mkPen(color=(0, 255, 0), width=PEN_WIDTH),
                 60: pg.mkPen(color=(64, 224, 208), width=PEN_WIDTH)}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        # self.periods = [5, 10, 20, 30, 60]
        self.init_setting()
        self._arrayManager = ArrayManager(max(self.MA_PARAMS) + 1)
        self.mas = defaultdict(dict)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        self.MA_PARAMS = setting.get('params', self.MA_PARAMS)
        if 'pen' in setting:
            pen_settings = setting['pen']
            pen_colors = {}
            for p in self.MA_PARAMS:
                pen_colors[p] = pg.mkPen(**pen_settings[str(p)])
            self.MA_COLORS = pen_colors

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects

        if ix <= self.last_ix:
            return self.last_picture

        pre_bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        ma_picture = QtGui.QPicture()
        self._arrayManager.update_bar(pre_bar)
        painter = QtGui.QPainter(ma_picture)

        # Draw volume body
        for p in self.MA_PARAMS:
            if self._arrayManager.close[-(p + 1)] == 0:
                self.mas[p][ix - 1] = np.nan
                continue

            sma=self._arrayManager.ma(p, True)
            pre_ma = sma[-2]
            ma = sma[-1]
            self.mas[p][ix-1] = ma

            sp = QtCore.QPointF(ix-2, pre_ma)
            ep = QtCore.QPointF(ix-1, ma)
            drawPath(painter, sp, ep, self.MA_COLORS[p])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = ma_picture
        return ma_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        min_price, max_price = self._manager.get_price_range()
        rect = QtCore.QRectF(
            0,
            min_price,
            len(self._bar_picutures),
            max_price - min_price
        )
        return rect

    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_volume, max_volume = self._manager.get_price_range(min_ix, max_ix)
        return min_volume, max_volume

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        text = '\n'.join(f'ma{p}: {v.get(ix, np.nan):.2f}' for p, v in self.mas.items())
        return f"MA \n{text}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self._arrayManager = ArrayManager(max(self.MA_PARAMS) + 1)
        self.mas = defaultdict(dict)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()

class MACDItem(ChartItem):
    name = 'macd'
    plot_name = 'indicator'
    MACD_PARAMS = [12, 26, 9]
    MACD_COLORS = {'diff': pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH),
                 'dea': pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH),
                 'macd': {'up': pg.mkBrush(color=(255, 0, 0)), 'down': pg.mkBrush(color=(0, 255, 50))}}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        self.init_setting()
        self._arrayManager = ArrayManager(150)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.macds = defaultdict(dict)
        self.br_max = 0
        self.br_min = 0

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        self.MACD_PARAMS = setting.get('params', self.MACD_PARAMS)
        if 'pen' in setting:
            pen_settings = setting['pen']
            self.MACD_COLORS['diff'] = pg.mkPen(**pen_settings['diff'])
            self.MACD_COLORS['dea'] = pg.mkPen(**pen_settings['dea'])

        if 'brush' in setting:
            brush_settings = setting['brush']
            self.MACD_COLORS['macd'] = {'up': pg.mkBrush(**brush_settings['macd']['up']),
                                        'down': pg.mkBrush(**brush_settings['macd']['down'])}

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects
        if ix <= self.last_ix:
            return self.last_picture

        pre_bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        macd_picture = QtGui.QPicture()
        self._arrayManager.update_bar(pre_bar)
        painter = QtGui.QPainter(macd_picture)

        diff, dea, macd = self._arrayManager.macd(*self.MACD_PARAMS, array=True)
        self.br_max = max(self.br_max, diff[-1], dea[-1], macd[-1])
        self.br_min = min(self.br_min, diff[-1], dea[-1], macd[-1])
        self.macds['diff'][ix-1] = diff[-1]
        self.macds['dea'][ix-1] = dea[-1]
        self.macds['macd'][ix-1] = macd[-1]
        if not (np.isnan(diff[-2]) or np.isnan(dea[-2]) or np.isnan(macd[-1])):
            macd_bar = QtCore.QRectF(ix - 1 - BAR_WIDTH, 0,
                                     BAR_WIDTH * 2, macd[-1])
            painter.setPen(pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH))
            if macd[-1] > 0:
                painter.setBrush(self.MACD_COLORS['macd']['up'])
            else:
                painter.setBrush(self.MACD_COLORS['macd']['down'])
            painter.drawRect(macd_bar)

            diff_sp = QtCore.QPointF(ix - 2, diff[-2])
            diff_ep = QtCore.QPointF(ix - 1, diff[-1])
            drawPath(painter, diff_sp, diff_ep, self.MACD_COLORS['diff'])

            dea_sp = QtCore.QPointF(ix - 2, dea[-2])
            dea_ep = QtCore.QPointF(ix - 1, dea[-1])
            drawPath(painter, dea_sp, dea_ep, self.MACD_COLORS['dea'])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = macd_picture
        return macd_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            self.br_min,
            len(self._bar_picutures),
            self.br_max - self.br_min
        )
        return rect


    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_ix = 0 if min_ix is None else min_ix
        max_ix = self.last_ix if max_ix is None else max_ix

        min_v = 0
        max_v = 0

        for i in range(min_ix, max_ix):
            min_v = min(min_v, self.macds['diff'].get(i, min_v), self.macds['dea'].get(i, min_v), self.macds['macd'].get(i, min_v))
            max_v = max(max_v, self.macds['diff'].get(i, max_v), self.macds['dea'].get(i, max_v), self.macds['macd'].get(i, max_v))

        return min_v, max_v

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        return f"MACD{self.MACD_PARAMS}  DIFF:{self.macds['diff'].get(ix, np.nan):.2f} DEA:{self.macds['dea'].get(ix, np.nan):.2f} MACD:{self.macds['macd'].get(ix, np.nan):.2f}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self._arrayManager = ArrayManager(150)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.macds = defaultdict(dict)
        self.br_max = 0
        self.br_min = 0


class INCItem(ChartItem):
    name = 'inc'
    plot_name = 'indicator'
    INC_PARAMS = [60, 2]
    INC_COLORS = {'up': pg.mkPen(color=(0, 0, 255), width=PEN_WIDTH),
                 'inc': {'up_gte': pg.mkBrush(color=(255, 0, 0)), 'up_lt': pg.mkBrush(color=(160, 32, 240)),
                         'down_gte': pg.mkBrush(color=(0, 255, 0)), 'down_lt': pg.mkBrush(color=(0, 255, 255))},
                 'down': pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH)}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        self.init_setting()
        self._arrayManager = ArrayManager(150)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.incs = defaultdict(dict)
        self.br_max = 0
        self.br_min = 0

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        self.INC_PARAMS = setting.get('params', self.INC_PARAMS)
        if 'pen' in setting:
            pen_settings = setting['pen']
            self.INC_COLORS['up'] = pg.mkPen(**pen_settings['up'])
            self.INC_COLORS['down'] = pg.mkPen(**pen_settings['down'])

        if 'brush' in setting:
            brush_settings = setting['brush']
            self.INC_COLORS['inc'] = {'up_gte': pg.mkBrush(**brush_settings['up_gte']),
                                      'up_lt': pg.mkBrush(**brush_settings['up_lt']),
                                      'down_gte': pg.mkBrush(**brush_settings['down_gte']),
                                      'down_lt': pg.mkBrush(**brush_settings['down_lt'])}

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects
        if ix <= self.last_ix:
            return self.last_picture

        pre_bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        inc_picture = QtGui.QPicture()
        self._arrayManager.update_bar(pre_bar)
        painter = QtGui.QPainter(inc_picture)

        inc = self._arrayManager.close - self._arrayManager.open
        std = talib.STDDEV(inc, self.INC_PARAMS[0])
        multiple =  inc / std

        # diff, dea, macd = self._arrayManager.macd(*self.MACD_PARAMS, array=True)
        self.br_max = max(self.br_max, std[-1], inc[-1])
        self.br_min = min(self.br_min, -std[-1], inc[-1])
        self.incs['up'][ix-1] = std[-1]
        self.incs['inc'][ix-1] = inc[-1]
        self.incs['down'][ix-1] = -std[-1]
        self.incs['multiple'][ix-1] = multiple[-1]
        if not (np.isnan(std[-2]*std[-1]*inc[-2]*inc[-1])):
            multiple_bar = QtCore.QRectF(ix - 1 - BAR_WIDTH, 0,
                                         BAR_WIDTH * 2, inc[-1])
            painter.setPen(pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH/2))
            if multiple[-1] >= 0:
                ud = 'up'
            else:
                ud = 'down'
            if abs(multiple[-1]) >= self.INC_PARAMS[1]:
                cp = 'gte'
            else:
                cp = 'lt'
            painter.setBrush(self.INC_COLORS['inc'][f'{ud}_{cp}'])
            painter.drawRect(multiple_bar)

            up_sp = QtCore.QPointF(ix - 2, std[-2])
            up_ep = QtCore.QPointF(ix - 1, std[-1])
            drawPath(painter, up_sp, up_ep, self.INC_COLORS['up'])

            down_sp = QtCore.QPointF(ix - 2, -std[-2])
            down_ep = QtCore.QPointF(ix - 1, -std[-1])
            drawPath(painter, down_sp, down_ep, self.INC_COLORS['down'])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = inc_picture
        return inc_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            self.br_min,
            len(self._bar_picutures),
            self.br_max - self.br_min
        )
        return rect


    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_ix = 0 if min_ix is None else min_ix
        max_ix = self.last_ix if max_ix is None else max_ix

        min_v = 0
        max_v = 0

        for i in range(min_ix, max_ix):
            min_v = min(min_v, self.incs['down'].get(i, min_v), self.incs['inc'].get(i, min_v))
            max_v = max(max_v, self.incs['up'].get(i, max_v), self.incs['inc'].get(i, max_v))

        return min_v, max_v

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        return f"INC{self.INC_PARAMS}  UP:{self.incs['up'].get(ix, np.nan):.2f} DOWN:{self.incs['down'].get(ix, np.nan):.2f} INC:{self.incs['inc'].get(ix, np.nan):.2f} MUTIPLE:{self.incs['multiple'].get(ix, np.nan):.2f}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self._arrayManager = ArrayManager(150)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.incs = defaultdict(dict)
        self.br_max = 0
        self.br_min = 0


class RSICurveItem(ChartItem):
    name = 'rsi'
    plot_name = 'indicator'
    RSI_PARAMS = [6, 12, 24]
    RSI_COLORS = {6: pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH),
                 12: pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH),
                 24: pg.mkPen(color=(218, 112, 214), width=PEN_WIDTH)}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        # self.periods = [6, 12, 24]
        self.init_setting()
        self._arrayManager = ArrayManager(150)
        self.rsis = defaultdict(dict)
        self.last_ix = 0
        self.br_max = -np.inf
        self.br_min = np.inf
        self.last_picture = QtGui.QPicture()

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        self.RSI_PARAMS = setting.get('params', self.RSI_PARAMS)
        if 'pen' in setting:
            pen_settings = setting['pen']
            for p in self.RSI_PARAMS:
                self.RSI_COLORS[p] = pg.mkPen(**pen_settings[str(p)])

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects

        if ix <= self.last_ix:
            return self.last_picture

        pre_bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        rsi_picture = QtGui.QPicture()
        self._arrayManager.update_bar(pre_bar)
        painter = QtGui.QPainter(rsi_picture)

        # Draw volume body
        for p in self.RSI_PARAMS:
            rsi_=self._arrayManager.rsi(p, True)
            pre_rsi = rsi_[-2]
            rsi = rsi_[-1]
            self.rsis[p][ix-1] = rsi
            if np.isnan(pre_rsi) or np.isnan(rsi):
                continue

            self.br_max = max(self.br_max, rsi_[-1])
            self.br_min = min(self.br_min, rsi_[-1])

            rsi_sp = QtCore.QPointF(ix-2, rsi_[-2])
            rsi_ep = QtCore.QPointF(ix-1, rsi_[-1])
            drawPath(painter, rsi_sp, rsi_ep, self.RSI_COLORS[p])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = rsi_picture
        return rsi_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            self.br_min,
            len(self._bar_picutures),
            self.br_max - self.br_min
        )
        return rect

    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_ix = 0 if min_ix is None else min_ix
        max_ix = self.last_ix if max_ix is None else max_ix

        min_v = np.inf
        max_v = -np.inf

        p = self.RSI_PARAMS[0]
        for i in range(min_ix, max_ix):
            min_v = min(min_v, self.rsis[p].get(i, min_v), self.rsis[p].get(i, min_v))
            max_v = max(max_v, self.rsis[p].get(i, max_v), self.rsis[p].get(i, max_v))

        return min_v, max_v

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        text = '\n'.join(f'rsi{p}: {v.get(ix, np.nan):.2f}' for p, v in self.rsis.items())
        return f"RSI \n{text}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self._arrayManager = ArrayManager(150)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.rsis = defaultdict(dict)
        self.br_max = -np.inf
        self.br_min = np.inf


class RECORDCurveItem(ChartItem):
    name = 'record'
    plot_name = 'indicator'
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        self.records_df = None
        self.RECORD_COLOR = {}
        self.last_ix = 0
        self.br_max = -np.inf
        self.br_min = np.inf
        self.last_picture = QtGui.QPicture()

    def set_records(self, records_df):
        from hashlib import sha256
        self.records_df = records_df
        for name in self.records_df.columns:
            _hash = sha256()
            _hash.update(name.encode())
            self.RECORD_COLOR[name] = pg.Color(int(_hash.hexdigest(), base=16))


    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects

        if ix <= self.last_ix:
            return self.last_picture

        pre_bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        records_picture = QtGui.QPicture()
        painter = QtGui.QPainter(records_picture)

        if self.records_df is None or self.records_df.empty:
            return records_picture

        pre_records = self.records_df.iloc[ix-1]    # self.records_df[pre_bar.datetime]
        cur_records = self.records_df.iloc[ix]    # self.records_df[bar.datetime]

        for (n, pv), (_, cv) in zip(pre_records.items(), cur_records.items()):
            rsi_sp = QtCore.QPointF(ix-1, pv)
            rsi_ep = QtCore.QPointF(ix, cv)
            self.br_max = max(self.br_max, pv, cv)
            self.br_min = min(self.br_min, pv, cv)
            drawPath(painter, rsi_sp, rsi_ep, self.RECORD_COLOR[n])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = records_picture
        return records_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            self.br_min,
            len(self._bar_picutures),
            self.br_max - self.br_min
        )
        return rect

    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_ix = 0 if min_ix is None else min_ix
        max_ix = self.last_ix if max_ix is None else max_ix

        min_v = np.inf
        max_v = -np.inf

        if not self.records_df.empty:
            min_v = min(min_v, self.records_df[min_ix:max_ix].min().min())
            max_v = max(max_v, self.records_df[min_ix:max_ix].max().max())

        return min_v, max_v

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        text = '\n'.join(f'record {p}: {v:.2f}' for p, v in self.records_df.iloc[ix].items())
        return f"RECORDS \n{text}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.br_max = -np.inf
        self.br_min = np.inf

class PNLCurveItem(ChartItem):
    name = 'pnl'
    plot_name = 'pnl'
    PNL_COLORS = {"up": pg.mkPen(color=(0, 0, 255), width=PEN_WIDTH),
                 "down": pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH)}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        # self.periods = [6, 12, 24]
        self.ix_pos_map = defaultdict(lambda :(0, 0))
        self.ix_pnl_map = defaultdict(int)
        self.init_setting()
        self.last_ix = 0
        self.br_max = -9999
        self.br_min = 9999
        self.last_picture = QtGui.QPicture()

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        if 'pen' in setting:
            pen_settings = setting['pen']
            for p in self.PNL_COLORS:
                self.PNL_COLORS[p] = pg.mkPen(**pen_settings[str(p)])

    def set_ix_pos_map(self, ix_pos_map):
        self.ix_pos_map = ix_pos_map

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects

        pre_bar = self._manager.get_bar(ix-2)
        bar = self._manager.get_bar(ix-1)

        if not pre_bar:
            return self.last_picture

        pnl_picture = QtGui.QPicture()
        painter = QtGui.QPainter(pnl_picture)

        # Draw volume body
        pre_pos = self.ix_pos_map[ix-2]
        pos = self.ix_pos_map[ix-1]
        if pre_pos[0] == 0:
            pre_pnl = -pre_pos[1]
        else:
            pre_pnl = pre_bar.close_price * pre_pos[0] - pre_pos[1]

        if pos[0] == 0:
            pnl = -pos[1]
        else:
            pnl = bar.close_price * pos[0] -  pos[1]

        self.ix_pnl_map[ix-1] = pnl
        self.br_max = max(self.br_max, pnl)
        self.br_min = min(self.br_min, pnl)

        pnl_sp = QtCore.QPointF(ix-2, pre_pnl)
        pnl_ep = QtCore.QPointF(ix-1, pnl)
        drawPath(painter, pnl_sp, pnl_ep, self.PNL_COLORS['up'])

        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = pnl_picture
        return pnl_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            self.br_min - 10,
            len(self._bar_picutures),
            (self.br_max - self.br_min) + 10
        )

        return rect

    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_ix = 0 if min_ix is None else min_ix
        max_ix = self.last_ix if max_ix is None else max_ix

        min_v = 9999
        max_v = -9999

        for i in range(min_ix, max_ix):
            pnl = self.ix_pnl_map[i]
            min_v = min(min_v, pnl)
            max_v = max(max_v, pnl)

        return min_v - 10 , max_v + 10

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        text = self.ix_pnl_map[ix]
        return f"PNL: \n{text}"

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self.ix_pos_map = defaultdict(lambda :(0, 0))
        self.ix_pnl_map = defaultdict(int)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()
        self.br_max = -9999
        self.br_min = 9999

class SplitLineItem(ChartItem):
    name = 'split'
    plot_name = 'candle'
    SPLITLINE_PARAMS = ['09:15', '17:15']
    SPLITLINE_COLORS = {'09:15': pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH),
                        '17:15': pg.mkPen(color=(255, 255, 0), width=PEN_WIDTH)}
    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        # self.periods = [5, 10, 20, 30, 60]
        self.init_setting()
        self.splitLines = defaultdict(dict)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()

    def init_setting(self):
        setting = VISUAL_SETTING.get(self.name, {})
        self.SPLITLINE_PARAMS = setting.get('params', self.SPLITLINE_PARAMS)
        if 'pen' in setting:
            pen_settings = setting['pen']
            pen_colors = {}
            for p in self.SPLITLINE_PARAMS:
                pen_colors[p] = pg.mkPen(**pen_settings[str(p)])
            self.SPLITLINE_COLORS = pen_colors

        for p in self.SPLITLINE_COLORS.values():
            p.setStyle(QtCore.Qt.DashDotDotLine)

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        # Create objects
        if ix <= self.last_ix:
            return self.last_picture

        splitLine_picture = QtGui.QPicture()
        painter = QtGui.QPainter(splitLine_picture)
        # Draw volume body
        last_bar = self._manager.get_bar(self.last_ix)
        timestr = bar.datetime.time().strftime('%H:%M')
        for t in self.SPLITLINE_PARAMS:
            _time = parser.parse(t).time()
            if _time <= bar.datetime.time() and last_bar.datetime < bar.datetime.replace(hour=_time.hour, minute=_time.minute):
                pen = self.SPLITLINE_COLORS.get(timestr, pg.mkPen(color=(255, 255, 255), width=PEN_WIDTH, style=QtCore.Qt.DashDotDotLine))
                painter.setPen(pen)
                line = QtCore.QLineF(ix-0.5, 0, ix-0.5, 40000)
                self.splitLines[bar.datetime] = line
                painter.drawLine(line)
        # Finish
        painter.end()
        self.last_ix = ix
        self.last_picture = splitLine_picture
        return splitLine_picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        rect = QtCore.QRectF(
            0,
            0,
            len(self._bar_picutures),
            40000
        )
        return rect

    def get_y_range(self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """
        Get range of y-axis with given x-axis range.

        If min_ix and max_ix not specified, then return range with whole data set.
        """
        min_p, max_p = self._manager.get_price_range(min_ix, max_ix)
        return min_p, max_p

    def get_info_text(self, ix: int) -> str:
        """
        Get information text to show by cursor.
        """
        text = ''
        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        super().clear_all()
        self.splitLines = defaultdict(dict)
        self.last_ix = 0
        self.last_picture = QtGui.QPicture()

def drawPath(painter, sp, ep, color):
    path = QtGui.QPainterPath(sp)
    c1 = QtCore.QPointF((sp.x() + ep.x()) / 2, (sp.y() + ep.y()) / 2)
    c2 = QtCore.QPointF((sp.x() + ep.x()) / 2, (sp.y() + ep.y()) / 2)
    path.cubicTo(c1, c2, ep)
    painter.setPen(color)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.drawPath(path)

VISUAL_SETTING = load_json('visual_setting.json')
INDICATOR = [MACurveItem, SplitLineItem, MACDItem, INCItem, RSICurveItem]