import pytest
import allure
import sys
import os
# 获取项目根目录（假设当前文件在 utils 目录下）
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # 向上到项目根目录
# 将项目根目录添加到 Python 路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from utils.http_request import HttpRequest
from utils.asserts.assert_manager import AssertManager
from testdata.yamldata_manager import YAMLDataManager

# 登录测试类-参数化
@allure.epic("商品管理接口测试")
@allure.feature("商品详情测试1")
@allure.story("商品详情测试2")
# 商品详情测试类-非参数化
class TestGoodsdetail:
    data_manager = YAMLDataManager()
    cases = data_manager.get_cases("testdata/goodsdata.yaml", "goods_cases")
    
    @pytest.mark.parametrize("case", cases)
    def test_goods_detail(self, case):
        case_id = case["case_id"]
        description = case["description"]
        requestdata = case["requestdata"]
        assertion = case["assertion"]
        goods_URL = case["goods_URL"]
        headers = case["headers"]
        
        try:
            response = HttpRequest(goods_URL,method="POST", headers=headers, data=requestdata)
            #print(response.json())
            am = AssertManager(soft=True)
            am.equal(response.get_json()["code"], assertion["stock_code"])
            am.equal(response.get_json()["msg"], assertion["prompt_msg"])
            am.assert_all()
            # 根据实际结果动态设置标题
            allure.dynamic.title(f"{case_id}-{description}")
        except AssertionError:
            print(f"商品详情测试失败，case_id={case_id}")
            raise
        

# 运行测试
if __name__ == '__main__':
    # __file__ 变量会自动获取当前文件的完整路径，这样无论从哪个目录运行都能找到正确的文件
    pytest.main(["-s", __file__])


    
