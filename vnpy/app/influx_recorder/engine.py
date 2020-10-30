#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2020/10/28 0028 9:31
# @Author  : Hadrianl 
# @File    : engine


import traceback
from typing import Optional

from vnpy.event import Event, EventEngine
from vnpy.trader.event import EVENT_TICK, EVENT_TRADE, EVENT_LOG
from vnpy.trader.engine import BaseEngine, MainEngine
from vnpy.trader.utility import load_json, save_json
from vnpy.trader.object import LogData
from vnpy.app.ib_cta_strategy.base import EVENT_CTA_LOG
from influxdb import InfluxDBClient

APP_NAME = "InfluxRecorder"

class InfluxRecorderEngine(BaseEngine):
    """"""
    setting_filename = "influx_recorder_setting.json"
    db_name = "vnpy_record"

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        """"""
        super().__init__(main_engine, event_engine, APP_NAME)

        self._retry = 5
        self.retention_policy_name = 'rt'
        self.host = "localhost"
        self.port = 8086
        self.user = ""
        self.password = ""

        self.influx_client: Optional[InfluxDBClient] = None

        self.load_setting()

    def start_recorder(self, host, port, user, password):
        """"""
        self.influx_client = InfluxDBClient(host, port, user, password, self.db_name)
        self.influx_client.ping()
        self.influx_client.create_database(self.db_name)
        self.influx_client.create_retention_policy(self.retention_policy_name, '7d', '1', shard_duration='1d')
        self.register_event()

    def stop_recorder(self):
        """"""
        self.unregister_event()
        self.influx_client = None

    def load_setting(self):
        """"""
        setting = load_json(self.setting_filename)
        self.host = setting.get("host", self.host)
        self.port = setting.get("port", self.port)
        self.user = setting.get("user", self.user)
        self.password = setting.get("password", self.password)

    def save_setting(self):
        """"""
        setting = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
        }
        save_json(self.setting_filename, setting)

    def register_event(self):
        """"""
        self.event_engine.register(EVENT_TICK, self.process_tick_event)
        self.event_engine.register(EVENT_TRADE, self.process_trade_event)
        self.event_engine.register(EVENT_LOG, self.process_log_event)
        self.event_engine.register(EVENT_CTA_LOG, self.process_cta_log_event)

    def unregister_event(self):
        """"""
        self.event_engine.unregister(EVENT_TICK, self.process_tick_event)
        self.event_engine.unregister(EVENT_TRADE, self.process_trade_event)
        self.event_engine.unregister(EVENT_LOG, self.process_log_event)
        self.event_engine.unregister(EVENT_CTA_LOG, self.process_cta_log_event)

    def process_tick_event(self, event: Event):
        """"""
        tickdata = event.data
        ticks = [{
            "measurement": "tick",
            "tags": {
                "symbol": tickdata.symbol,
                "exchange": tickdata.exchange.value,
            },
            "fields": {
                "last": float(tickdata.last_price),
                "ask": float(tickdata.ask_price_1),
                "bid": float(tickdata.bid_price_1),
                "volume": tickdata.volume,
            }
        }]

        self.influx_client.write_points(ticks, retention_policy=self.retention_policy_name)

    def process_trade_event(self, event: Event):
        """"""
        tradedata = event.data
        trades = [{
            "measurement": "trade",
            "tags": {
                "symbol": tradedata.symbol,
                "exchange": tradedata.exchange.value,
                "direction": tradedata.direction.value,
            },
            "fields": {
                "datetime": tradedata.datetime.strftime('%Y-%m-%dT%H:%M:%S'),
                "price": tradedata.price,
                "volume": tradedata.volume,
                "orderRef": tradedata.orderRef,
                "vt_orderid": tradedata.vt_orderid,
                "vt_tradeid": tradedata.vt_tradeid,
            }
        }]

        self.influx_client.write_points(trades, retention_policy=self.retention_policy_name)

    def process_log_event(self, event: Event):
        """"""
        logdata = event.data
        logs = [{
            "measurement": "log",
            "tags": {
                "level": logdata.level,
            },
            "fields": {
                "datetime": logdata.time.strftime('%Y-%m-%dT%H:%M:%S'),
                "msg": logdata.msg,
            }
        }]

        self.influx_client.write_points(logs, retention_policy=self.retention_policy_name)

    def process_cta_log_event(self, event: Event):
        """"""
        logdata = event.data
        logs = [{
            "measurement": "cta_log",
            "tags": {
                "level": logdata.level,
            },
            "fields": {
                "datetime": logdata.time.strftime('%Y-%m-%dT%H:%M:%S'),
                "msg": logdata.msg,
            }
        }]

        self.influx_client.write_points(logs, retention_policy=self.retention_policy_name)

    def close(self):
        """"""
        self.stop_recorder()
