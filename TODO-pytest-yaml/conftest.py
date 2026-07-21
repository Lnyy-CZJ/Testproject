import json
import pytest
import os
import sys
import functools  # 用于装饰器
from pathlib import Path  # Python的路径处理
# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
from utils.log import reset_trace_id

# ==================== 日志管理：自动重置 trace_id ====================
@pytest.fixture(autouse=True)
def auto_trace():
    reset_trace_id()


# ==================== 第一部分：缓存装饰器 ====================
def cache_data(func):
    """改进版缓存装饰器"""
    cache = {}
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 处理不可哈希的参数
        try:
            # 尝试创建缓存键
            cache_key = (func.__name__, args, frozenset(kwargs.items()))
        except TypeError:
            # 如果失败，使用字符串表示
            cache_key = f"{func.__name__}_{str(args)}_{str(kwargs)}"
        
        if cache_key not in cache:
            cache[cache_key] = func(*args, **kwargs)
        
        return cache[cache_key]
    
    return wrapper

# ==================== 第二部分：通用数据加载函数 ====================
@cache_data  # 应用缓存装饰器
def load_test_data(file_name: str, data_key: str):
    """
    通用测试数据加载函数
    
    参数:
        file_name: JSON文件名 (如 "goodsdata.json")
        data_key: JSON文件中要提取的数据键名 (如 "goodsdata")
    
    返回:
        List[List]: 测试数据列表
    """
    # 构建完整的文件路径
    # Path(__file__).parent 获取当前文件的父目录
    # 然后拼接 testdata 目录和文件名
    file_path = Path(__file__).parent / "testdata" / file_name
    
    try:
        # 读取JSON文件
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)  # 解析JSON
            
        # 从JSON数据中提取指定键的数据
        # 使用.get()方法，如果键不存在返回空列表
        return data.get(data_key, [])
        
    except FileNotFoundError:
        # 文件不存在时跳过测试
        pytest.skip(f"测试数据文件不存在: {file_path}")
        return []
    except json.JSONDecodeError:
        # JSON格式错误时跳过测试
        pytest.skip(f"JSON格式错误: {file_path}")
        return []
    except Exception as e:
        # 其他异常也跳过测试
        pytest.skip(f"无法加载测试数据: {e}")
        return []

# ==================== 第三部分：基础Fixture ====================
@pytest.fixture(scope="session")  # session级别，整个测试会话只执行一次
def all_goods_test_data():
    """数据加载函数，在pytest收集测试时调用"""
    return load_test_data("goodsdata.json", "goodsdata")


# ==================== 第四部分：使用fixture + indirect参数化 ====================
# 商品详情测试用例参数化-最好是用这个方法
@pytest.fixture(scope="function")
def goods_test_data_params(request):
    """
    高级Fixture：处理参数化的测试数据
    
    作用：
    1. 接收 @pytest.mark.parametrize 传递的参数
    2. 将原始数据转换为字典格式
    3. 提供给测试函数使用
    
    参数说明：
    - request: pytest内置fixture，包含当前测试的请求信息
    - request.param: 当使用 indirect=True 时，这里接收参数化的数据
    
    工作原理：
    1. 当测试使用 @pytest.mark.parametrize 且 indirect=True 时
    2. pytest会将参数传递给这个fixture的request.param
    3. fixture处理数据并返回给测试函数
    
    返回数据格式：
    {
        "goods_id": "商品ID字符串",
        "code": 状态码整数,
        "msg": "消息字符串",
        "allure_title": "测试描述字符串"
    }
    """
    # 检查是否通过参数化传递了数据（request.param是否存在）
    if hasattr(request, 'param'):
        # 解包参数化传递的数据
        # 假设数据格式为: [goods_id, code, msg, allure_title]
        goods_id, code, msg, allure_title = request.param
        return {
            "goods_id": goods_id,
            "code": code,
            "msg": msg,
            "allure_title": allure_title
        }
    # 如果没有参数化数据（直接调用fixture的情况）
    # 返回一个空的字典或默认数据
    return {}

# 登录测试用例参数化，这个调用方法即使不运行测试也会加载数据文件
login_test_data = load_test_data("logindata.json", "logindata")
@pytest.fixture(scope="function", params=login_test_data)
def login_test_data_params(request):
    """
    高级Fixture：使用params参数直接参数化
    每个测试用例会执行所有参数组合
    """
    # 从params中获取当前测试数据
    type, accounts, pwd, code, msg, allure_title = request.param
    
    # 返回测试数据字典
    return {
        "type": type,
        "accounts": accounts,
        "pwd": pwd,
        "code": code,
        "msg": msg,
        "allure_title": allure_title
    }

# ==================== 第五部分：便利Fixture（这个可用于只执行特定用例） ====================
@pytest.fixture
def goods_test_cases(all_goods_test_data):
    """
    提供更友好的接口
    
    返回:
        字典形式的测试用例，键为用例标题
    """
    # 将用例转换为标题->用例的字典
    return {case["allure_title"]: case for case in all_goods_test_data}


@pytest.fixture
def get_goods_case_by_title(goods_test_cases):
    """
    按标题获取特定测试用例的工厂函数
    """
    def _get_case(title: str) -> Dict[str, Any]:
        """根据标题获取测试用例"""
        return goods_test_cases.get(title)
    
    return _get_case


#使用方法，终端运行pytest conftest.py::test_check_data -v -s
def test_check_data(all_goods_test_data):
    """临时测试函数查看数据"""
    print("=" * 50)
    print("查看 all_goods_test_data 数据:")
    print(f"数据类型: {type(all_goods_test_data)}")
    
    if isinstance(all_goods_test_data, list):
        print(f"列表长度: {len(all_goods_test_data)}")
        if all_goods_test_data:
            print("查看前3条数据:")
            print(json.dumps(all_goods_test_data[:3], indent=2, ensure_ascii=False))
    elif isinstance(all_goods_test_data, dict):
        print(f"字典键: {list(all_goods_test_data.keys())}")
        if all_goods_test_data:
            key = list(all_goods_test_data.keys())[0]
            print(f"键 '{key}' 对应的值:")
            print(json.dumps(all_goods_test_data[key], indent=2, ensure_ascii=False))
    print("=" * 50)
# 运行测试
if __name__ == '__main__':
    # __file__ 变量会自动获取当前文件的完整路径，这样无论从哪个目录运行都能找到正确的文件

    pytest.main(["-s", __file__])