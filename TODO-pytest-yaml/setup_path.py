# -*- coding: utf-8 -*-
# -------------------------------
# @文件：setup_path.py
# @时间：2026/3/22 14:02
# @作者：chenzj
# @功能描述：路径添加类
#import setup_path  # 这会自动设置路径
# -------------------------------
import sys
import os

# 将当前目录添加到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)