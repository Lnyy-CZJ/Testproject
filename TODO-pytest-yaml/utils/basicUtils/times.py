# -*- coding: utf-8 -*-
# -------------------------------
# @文件：times.py
# @时间：2026/3/22 15:30
# @作者：chenzj
# @功能描述：时间处理工具类
# -------------------------------
import time
import datetime
from datetime import timedelta


class Times:

    # 获取时间戳
    @staticmethod #@staticmethod 是 Python 中的一个装饰器，用于声明一个方法为静态方法,以直接通过 Times.timestamp() 来获取当前时间戳，而无需先实例化 Times 对象。
    def timestamp() -> int:
        return int(time.time())

    # 自定义时间格式
    @staticmethod
    def custom_time(model, num=0, time_delta=None) -> str:
        """
        自定义时间计算工具
        :param model：时间格式模板，例如 "%Y-%m-%d %H:%M" 会返回类似 "2026-03-22 14:30" 的格式
        :param num：时间偏移量，默认为 0，可以是正数（未来）或负数（过去）
        :param time_delta：时间单位，可选 "hour"（小时）、"min"（分钟），默认 None 表示天数
        :return: 对应时间的字符串
        """
        #将输入的时间单位转为小写，确保后续比较时不受大小写影响。
        if time_delta:
            time_delta = time_delta.lower()
        if time_delta is None:
            res = datetime.datetime.now() + timedelta(days=num)
            return res.strftime(model)
        elif time_delta == 'hour':
            res = datetime.datetime.now() + timedelta(hours=num)
            return res.strftime(model)
        elif time_delta == 'min':
            res = datetime.datetime.now() + timedelta(minutes=num)
            return res.strftime(model)
        else:
            raise "time_delta参数异常！"
