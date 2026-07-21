# -*- coding: utf-8 -*-
# -------------------------------
# @文件：http_request.py
# @时间：2026/3/22 14:02
# @作者：chenzj
# @功能描述：封装的 http 请求类
# -------------------------------
import requests
import allure
import json
import sys
import os
# 获取项目根目录（假设当前文件在 utils 目录下）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # 向上到项目根目录
# 将项目根目录添加到 Python 路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.log import Log


class HttpRequest:

    @allure.step("发起请求")
    def __init__(self, url: str, method: str, data=None, cookies: dict = None, headers: dict = None):
        """
        :param url:请求的 url
        :param method: 请求方式 get post
        :param data: 请求参数
        :param cookies: 请求的 cookies
        :param headers: 请求的 header
        """
        if data:
            if isinstance(data, str):
                data = json.loads(data)
        try:
            if method.upper() == "GET":
                self.res = requests.session().get(url=url, params=data, headers=headers, cookies=cookies)
            elif method.upper() == "POST":
                self.res = requests.session().post(url=url, json=data, headers=headers, cookies=cookies)
            else:
                Log.error(f"请求类未添加对应请求方式{method}")
            with allure.step("请求日志"):
                Log.debug("-------------------------------------------------------------------------------------------")
                Log.debug("请求信息:")
                Log.debug(f"---request_url:---{self.res.request.url}")
                Log.debug(f"---request_headers:---{self.res.request.headers}")
                Log.debug(f"---request_body:---{self.res.request.body}")
                Log.debug(f"---request_cookies:---{self.res.cookies}")
                Log.debug(f"---request_method:---{self.res.request.method}")
                Log.debug(f"---request_data:---{data}")
                Log.debug("响应信息:")
                Log.debug(f"---response_code:---{self.res.status_code}")
                Log.debug(f"---response_headers:---{self.res.headers}")
                Log.debug(f"---response_body:---{self.res.text}")   
                Log.debug("-------------------------------------------------------------------------------------------")
        except Exception:
            Log.error(Exception)
            raise Exception("请求异常请检查")

    # 获取请求的cookies
    def get_cookies(self):
        return self.res.cookies

    # 获取接口返回的json对象
    def get_json(self):
        return self.res.json()

    # 获取接口返回的json对象
    def getText(self):
        return self.res.text

    # 获取接口的返回的code
    def get_code(self):
        return self.res.status_code

    # 获取接口的全部响应时间
    def get_response_time(self):
        return self.res.elapsed.total_seconds()

    # 获取接口返回值的 heaader
    def get_headers(self):
        return self.res.headers
