# -*- coding: utf-8 -*-
# -------------------------------
# @文件：log.py
# @时间：2026/3/22 14:02
# @作者：chenzj
# @功能描述：二次封装的日志类
# -------------------------------
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import logging
import os
import shutil
import threading
from datetime import datetime
from contextvars import ContextVar

from utils.basicUtils.times import Times
from utils.data_manager import DataManager
from config import constants_path

# ===== 配置 =====
log_conf = DataManager().load_yaml_data(constants_path.CONFIG_PATH)['LOG_CONFIG']

logger = logging.getLogger("Log")
logger.setLevel(log_conf.get("LOG_LEVEL", "DEBUG"))

# ===== 锁 =====
_init_lock = threading.Lock()
_counter_lock = threading.Lock()

# ===== trace上下文 =====
trace_id_var = ContextVar("trace_id", default=None)

# ===== trace生成参数 =====
TRACE_PREFIX = "REQ"
_counter = 0
_last_date = None


# ==============================
# trace_id生成（唯一入口）
# ==============================
def get_trace_id():
    global _counter, _last_date

    trace_id = trace_id_var.get()
    if trace_id:
        return trace_id
    #当前日期
    today = datetime.now().strftime("%Y-%m-%d")
    #当前进程ID
    pid = os.getpid()

    with _counter_lock:
        if _last_date != today:
            _counter = 0
            _last_date = today

        _counter += 1
        current = _counter
    # 生成 trace_id
    # 格式：REQ-YYYY-MM-DD-PID_0000递增
    trace_id = f"{TRACE_PREFIX}-{today}-{pid}-{current:04d}"
    trace_id_var.set(trace_id)

    return trace_id


# ==============================
# 重置 trace（仅清空，不生成）
# ==============================
def reset_trace_id():
    trace_id_var.set(None)


# ==============================
# Filter 注入 trace_id
# ==============================
class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = get_trace_id()
        return True


# ==============================
# 日志目录管理
# ==============================
class LogStoragerPocess:

    @staticmethod
    def get_log_dir():
        today = Times.custom_time('%Y%m%d')
        log_dir = os.path.join(constants_path.LOG_PATH, today)

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        save_day = log_conf.get('SAVE_DAY', 7)
        max_time = int(today) - save_day

        for folder in os.listdir(constants_path.LOG_PATH):
            if folder.isdigit() and int(folder) < max_time:
                shutil.rmtree(os.path.join(constants_path.LOG_PATH, folder))

        return log_dir


# ==============================
# 日志主类
# ==============================
class Log:
    __initialized = False

    @classmethod
    def _init_logger(cls):
        if cls.__initialized:
            return

        with _init_lock:
            if cls.__initialized:
                return

            log_dir = LogStoragerPocess.get_log_dir()

            all_log_file = os.path.join(log_dir, "all.log")
            error_log_file = os.path.join(log_dir, "error.log")

            formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | [%(trace_id)s] | %(message)s"
            )

            # 控制台
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            ch.setFormatter(formatter)
            ch.addFilter(TraceIdFilter())

            # 全量日志
            fh = logging.FileHandler(all_log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            fh.addFilter(TraceIdFilter())

            # error日志
            eh = logging.FileHandler(error_log_file, encoding='utf-8')
            eh.setLevel(logging.ERROR)
            eh.setFormatter(formatter)
            eh.addFilter(TraceIdFilter())

            logger.addHandler(ch)
            logger.addHandler(fh)
            logger.addHandler(eh)

            cls.__initialized = True

    @classmethod
    def info(cls, msg):
        cls._init_logger()
        logger.info(msg)

    @classmethod
    def debug(cls, msg):
        cls._init_logger()
        logger.debug(msg)

    @classmethod
    def error(cls, msg):
        cls._init_logger()
        logger.error(msg, exc_info=True)

    @classmethod
    def warning(cls, msg):
        cls._init_logger()
        logger.warning(msg)

"""
日志使用示例
from utils.log import Log

def test_xxx():
    Log.set_trace_id()   # 必须调用！

    Log.info("开始测试")

    ...
"""
