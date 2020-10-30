#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2020/10/28 0028 11:34
# @Author  : Hadrianl 
# @File    : widget


from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtWidgets, QtCore
from ..engine import APP_NAME


class InfluxRecorder(QtWidgets.QWidget):
    """"""

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine):
        """"""
        super().__init__()

        self.main_engine = main_engine
        self.event_engine = event_engine

        self.influx_record_engine = main_engine.get_engine(APP_NAME)

        self.init_ui()

    def init_ui(self):
        """"""
        self.setWindowTitle("InfluxRecorder")
        self.setFixedWidth(900)
        self.setFixedHeight(500)

        self.start_button = QtWidgets.QPushButton("启动")
        self.start_button.clicked.connect(self.start_recorder)

        self.stop_button = QtWidgets.QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_recorder)
        self.stop_button.setEnabled(False)

        for button in [self.start_button, self.stop_button]:
            hint = button.sizeHint()
            button.setFixedHeight(hint.height() * 2)
            button.setFixedWidth(hint.width() * 4)

        self.host_line = QtWidgets.QLineEdit(self.influx_record_engine.host)
        self.host_line.setFixedWidth(300)

        self.port_line = QtWidgets.QLineEdit(str(self.influx_record_engine.port))
        self.port_line.setFixedWidth(300)

        self.user_line = QtWidgets.QLineEdit(self.influx_record_engine.user)
        self.user_line.setFixedWidth(300)

        self.password_line = QtWidgets.QLineEdit(self.influx_record_engine.password)
        self.password_line.setFixedWidth(300)
        self.password_line.setEchoMode(QtWidgets.QLineEdit.Password)

        form = QtWidgets.QFormLayout()
        form.addRow("influxdb主机", self.host_line)
        form.addRow("influxdb端口", self.port_line)
        form.addRow("influxdb用户名", self.user_line)
        form.addRow("influxdb密码", self.password_line)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addLayout(form)
        hbox.addWidget(self.start_button)
        hbox.addWidget(self.stop_button)
        hbox.addStretch()

        vbox = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox)
        # vbox.addWidget(self.log_monitor)

        self.setLayout(vbox)

    def start_recorder(self):
        """"""
        host = self.host_line.text()
        port = int(self.port_line.text())
        user = self.user_line.text()
        password = self.password_line.text()

        self.influx_record_engine.start_recorder(host, port, user, password)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_recorder(self):
        """"""
        self.influx_record_engine.stop_recorder()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
