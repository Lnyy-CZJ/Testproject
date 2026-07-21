import pytest
import requests
import os
import sys
import allure

# 将项目根目录添加到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from testdata.URL import Goodsdetail_URL
from conftest import load_test_data

# 商品详情测试类-参数化
@allure.epic("商品管理接口测试")
@allure.feature("商品详情测试1")
@allure.story("商品详情测试2")
class TestGoodsdetail:
    
    @pytest.mark.parametrize("goods_test_data_params", load_test_data("goodsdata.json", "goodsdata"), indirect=True)
    # 参数1: fixture的名称，必须和conftest中的fixture名称一致
    # 参数2: 测试数据列表,从goodsdata.json文件加载所有测试数据,每一条数据包含: [goods_id, code, msg, allure_title]
    # 参数3: indirect=True 是关键！,表示参数要传递给fixture处理，而不是直接传给测试函数
    # 参数4: ids,测试用例的显示名称（可选）,使用lambda函数从每条数据的第四个元素（描述）生成测试名称,ids=[f"测试用例_{i+1}" for i in range(len(load_test_data("goodsdata.json", "goodsdata")))]
    def test_goods_detail(self, goods_test_data_params):
        """直接使用goods_test_data_params fixture获取测试数据"""
        # 从fixture获取测试数据
        goods_id = goods_test_data_params["goods_id"]
        code = goods_test_data_params["code"]
        msg = goods_test_data_params["msg"]
        allure_title = goods_test_data_params["allure_title"]
        
        url = Goodsdetail_URL
        params = {
            "application": "web",
            "application_client_type": "PC"
        }
        data = { 
            "goods_id": goods_id
        }
        
        try:
            response = requests.post(url, params=params, data=data)
            # 断言
            assert response.json()["code"] == code
            assert response.json()["msg"] == msg
            # 根据实际结果动态设置标题
            allure.dynamic.title(f"商品详情测试点 -{allure_title}")
        except AssertionError:
            print(f"商品详情测试失败, goods_id={goods_id}, code={code}, msg={msg}")
            raise

# 运行测试
if __name__ == '__main__':
    # __file__ 变量会自动获取当前文件的完整路径，这样无论从哪个目录运行都能找到正确的文件
    pytest.main(["-s", __file__])
