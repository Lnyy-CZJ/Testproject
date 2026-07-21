import pytest
import requests
import json
import os
import sys
import allure
# 将项目根目录添加到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from testdata.URL import login_URL

# 登录测试类-参数化
@allure.epic("用户管理接口测试")
@allure.feature("用户管理登陆接口测试")
@allure.story("用户登录")
class TestLogin:
    # 已知账号密码登录测试点
    def test_login(self, login_test_data_params):
        """直接使用login_test_data_params fixture获取测试数据"""
        # 从fixture获取测试数据
        type = login_test_data_params["type"]
        accounts = login_test_data_params["accounts"]
        pwd = login_test_data_params["pwd"]
        code = login_test_data_params["code"]
        msg = login_test_data_params["msg"]
        allure_title = login_test_data_params["allure_title"]
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": accounts,
            "pwd":  pwd,
            "type": type
        }
        try:
            response = requests.post(url, params=params, data=data)
            #print(response.json())
            assert response.json()["code"] == code
            assert response.json()["msg"] == msg
            # 根据实际结果动态设置标题
            allure.dynamic.title(f"登录测试点 -{allure_title}")
        except AssertionError:
            print(f"登录测试失败，type={type}, accounts={accounts}, pwd={pwd}, code={code}, msg={msg}")
            raise
        

# 运行测试
if __name__ == '__main__':
    # __file__ 变量会自动获取当前文件的完整路径，这样无论从哪个目录运行都能找到正确的文件
    pytest.main(["-s", __file__])

"""
# 登录测试类-非参数化
class TestLogin:
    # 登录成功
    def test_loginsuccess_01(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj11",
            "pwd":  "czj111",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == 0
        assert response.json()["msg"] == "登录成功"
    
    # 登录失败-密码错误
    def test_loginfail_02(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj11",
            "pwd":  "czj1112",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -4
        assert response.json()["msg"] == "密码错误"
    
     # 登录失败-账号不存在
    def test_loginfail_03(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj112",
            "pwd":  "czj111",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -3
        assert response.json()["msg"] == "登录帐号不存在"
    
     # 登录失败-账号为空
    def test_loginfail_04(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "",
            "pwd":  "czj111",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -1
        assert response.json()["msg"] == "登录账号不能为空"
    
     # 登录失败-密码为空
    def test_loginfail_05(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj11",
            "pwd":  "",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -1
        assert response.json()["msg"] == "密码格式 6~18 个字符之间"
    
     # 登录失败-账号密码都为空
    def test_loginfail_06(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "",
            "pwd":  "",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -1
        assert response.json()["msg"] == "登录账号不能为空"

    #账号或包含特殊字符
    def test_loginfail_07(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj11@",
            "pwd":  "czj111",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -3
        assert response.json()["msg"] == "登录帐号不存在"
    
    #密码包含特殊字符
    def test_loginfail_08(self):
        url = login_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "accounts": "czj11",
            "pwd":  "czj111@",
            "type": "username"
        }
        response = requests.post(url, params=params, data=data)
        print(response.json())
        assert response.json()["code"] == -4
        assert response.json()["msg"] == "密码错误"
"""


