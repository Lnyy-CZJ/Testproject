# -*- coding: utf-8 -*-
# -------------------------------
# @文件：constants_path.py
# @时间：2026/3/22 15:20
# @作者：chenzj
# @功能描述：路径常量
# -------------------------------
import os

# 项目根目录
BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 测试用例目录
CASE_PATH = os.path.join(BASE_PATH, 'test_case')
# 测试数据目录
DATA_PATH = os.path.join(BASE_PATH, 'testdata')
# 框架配置文件路径
CONFIG_PATH = os.path.join(BASE_PATH, 'config/config.yaml')
# 日志文件路径
LOG_PATH = os.path.join(BASE_PATH, 'result/logs')
# 测试执行过程中截图文件存放
IMG_PATH = os.path.join(BASE_PATH, 'result/screenshot')
# 测试报告路径
REPORT_PATH = os.path.join(BASE_PATH, 'allure-report')