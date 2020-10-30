#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2020/10/28 0028 9:30
# @Author  : Hadrianl 
# @File    : __init__.py


from pathlib import Path
from vnpy.trader.app import BaseApp
from .engine import InfluxRecorderEngine, APP_NAME


class InfluxRecordApp(BaseApp):
    """"""
    app_name = APP_NAME
    app_module = __module__
    app_path = Path(__file__).parent
    display_name = "InfluxRecorder"
    engine_class = InfluxRecorderEngine
    widget_name = "InfluxRecorder"
    icon_name = "influx.ico"