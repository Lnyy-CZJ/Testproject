# TODO-pytest-yaml 项目 Code Wiki

## 1. 项目概述

这是一个基于 pytest + Allure 的接口自动化测试框架，采用 YAML 数据驱动模式，支持软断言、日志跟踪、数据缓存等特性。

**主要特性：**
- 📊 YAML 数据驱动测试
- 📝 完整的日志追踪系统（带 trace_id）
- ✅ 软断言支持
- 📈 Allure 测试报告
- 🔄 数据缓存机制
- 🔒 线程安全设计

---

## 2. 项目目录结构

```
TODO-pytest-yaml/
├── config/                  # 配置文件目录
│   ├── config.yaml         # 主配置文件
│   └── constants_path.py   # 路径常量定义
├── test_case/              # 测试用例目录
│   ├── test_case_login_yaml.py       # 登录接口测试（YAML驱动）
│   ├── test_case_goodsdetail_yaml.py # 商品详情测试（YAML驱动）
│   ├── test_case_login.py            # 登录接口测试
│   └── test_case_goodsdetail.py      # 商品详情测试
├── testdata/               # 测试数据目录
│   ├── logindata.yaml      # 登录测试数据
│   ├── goodsdata.yaml      # 商品详情测试数据
│   ├── yamldata_manager.py # YAML 数据管理器
│   ├── URL.py              # URL 管理
│   └── __init__.py
├── utils/                  # 工具类目录
│   ├── asserts/            # 断言模块
│   │   ├── assert_core.py  # 核心断言
│   │   ├── soft_assert.py  # 软断言
│   │   └── assert_manager.py # 断言管理器
│   ├── basicUtils/         # 基础工具
│   │   └── times.py        # 时间工具
│   ├── log.py              # 日志管理
│   ├── http_request.py     # HTTP 请求封装
│   └── data_manager.py     # 数据管理（Excel/YAML）
├── result/                 # 结果输出目录
│   └── logs/               # 日志文件
├── allure-results/         # Allure 测试结果
├── allure-report/          # Allure 测试报告
├── temps/                  # 临时文件目录
├── conftest.py             # pytest 配置文件
├── pytest.ini              # pytest 配置
├── runtest.py              # 测试执行入口
├── setup_path.py           # 路径设置
└── environment.properties  # Allure 环境配置
```

---

## 3. 核心模块说明

### 3.1 路径管理模块

**文件：** [config/constants_path.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/config/constants_path.py)

**主要常量：**
```python
BASE_PATH       # 项目根目录
CASE_PATH       # 测试用例目录
DATA_PATH       # 测试数据目录
CONFIG_PATH     # 配置文件路径
LOG_PATH        # 日志文件路径
IMG_PATH        # 截图文件路径
REPORT_PATH     # 测试报告路径
```

---

### 3.2 日志管理模块

**文件：** [utils/log.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/log.py)

**核心功能：**
- 日志分级别输出（DEBUG/INFO/WARNING/ERROR）
- 自动日志文件按日期分类存储
- 自动清理过期日志（默认保存 5 天）
- trace_id 追踪机制，便于问题定位

**使用方法：**
```python
from utils.log import Log

Log.info("开始测试")
Log.debug("调试信息")
Log.error("错误信息")
```

**Trace ID 格式：** `REQ-YYYY-MM-DD-PID-0000`

---

### 3.3 HTTP 请求模块

**文件：** [utils/http_request.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/http_request.py)

**类：** `HttpRequest`

**主要方法：**
| 方法 | 说明 |
|------|------|
| `__init__(url, method, data, cookies, headers)` | 发起 HTTP 请求 |
| `get_json()` | 获取 JSON 响应 |
| `getText()` | 获取文本响应 |
| `get_code()` | 获取状态码 |
| `get_cookies()` | 获取 cookies |
| `get_response_time()` | 获取响应时间 |
| `get_headers()` | 获取响应头 |

**使用示例：**
```python
from utils.http_request import HttpRequest

response = HttpRequest(
    url="http://api.example.com/login",
    method="POST",
    data={"username": "test", "password": "123456"}
)
print(response.get_json())
```

---

### 3.4 断言模块

**文件：**
- [utils/asserts/assert_core.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/asserts/assert_core.py) - 核心断言
- [utils/asserts/soft_assert.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/asserts/soft_assert.py) - 软断言
- [utils/asserts/assert_manager.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/asserts/assert_manager.py) - 断言管理器

**AssertManager 使用方法：**
```python
from utils.asserts.assert_manager import AssertManager

# 硬断言（失败立即停止）
am = AssertManager(soft=False)
am.equal(actual, expected, "描述")

# 软断言（收集所有失败后统一抛出）
am = AssertManager(soft=True)
am.equal(actual1, expected1)
am.equal(actual2, expected2)
am.assert_all()  # 统一断言
```

---

### 3.5 YAML 数据管理模块

**文件：** [testdata/yamldata_manager.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/testdata/yamldata_manager.py)

**类：** `YAMLDataManager`（单例模式）

**主要方法：**
| 方法 | 说明 |
|------|------|
| `get_common(file_path)` | 获取公共参数 |
| `get_cases(file_path, case_key)` | 获取测试用例（自动合并公共参数） |
| `clear_cache()` | 清除缓存 |

**YAML 数据格式示例：**
```yaml
case_common:  # 公共参数
  login_URL: "http://api.example.com/login"
  headers:
    "application": "web"

login_cases:  # 测试用例
  - case_id: login_001
    description: 登录成功
    requestdata:
      type: username
      accounts: czj11
      pwd: czj111
    assertion:
      status_code: 1
      prompt_msg: 登录成功
```

---

### 3.6 pytest 配置模块

**文件：** [conftest.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/conftest.py)

**主要 Fixtures：**
- `auto_trace`: 自动重置 trace_id
- `cache_data`: 数据缓存装饰器
- `load_test_data`: 通用测试数据加载函数
- `all_goods_test_data`: 商品测试数据
- `goods_test_data_params`: 商品参数化 Fixture
- `login_test_data_params`: 登录参数化 Fixture

---

### 3.7 时间工具模块

**文件：** [utils/basicUtils/times.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/basicUtils/times.py)

**类：** `Times`

**主要方法：**
| 方法 | 说明 |
|------|------|
| `timestamp()` | 获取时间戳 |
| `custom_time(model, num, time_delta)` | 自定义时间格式 |

**使用示例：**
```python
from utils.basicUtils.times import Times

Times.timestamp()  # 1234567890
Times.custom_time("%Y-%m-%d")  # "2026-03-22"
Times.custom_time("%Y-%m-%d", num=1)  # 明天
Times.custom_time("%H:%M", num=2, time_delta="hour")  # 2小时后
```

---

### 3.8 数据管理模块

**文件：** [utils/data_manager.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/utils/data_manager.py)

**类：** `DataManager`

**主要方法：**
| 方法 | 说明 |
|------|------|
| `get_data_from_excel(name, sheet_name)` | 从 Excel 获取全部数据 |
| `get_data_by_column_names(name, sheet_name, column_names)` | 按列名获取 Excel 数据 |
| `load_yaml_data(file_path)` | 加载 YAML 数据（带缓存） |

---

### 3.9 测试执行入口

**文件：** [runtest.py](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/runtest.py)

**功能：**
1. 执行 pytest 测试
2. 复制环境配置文件
3. 生成 Allure 报告
4. 可选在浏览器中打开报告

---

## 4. 配置文件说明

**文件：** [config/config.yaml](file:///c:/Users/CZJ/Desktop/测试面试相关/自动化测试（pytest）/pytestlearn/TODO-pytest-yaml/config/config.yaml)

```yaml
GLOBAL: pro  # 环境配置：uat/pro

LOG_CONFIG:  # 日志配置
  SAVE_DAY: 5           # 日志保存天数
  LOG_LEVEL: "DEBUG"    # 日志级别

SELENIUM_CONFIG:  # Selenium 配置（预留）
  WAIT_ELEMENT: 30
  POLL_ELEMENT: 1
  ALL_TIMEOUT: 45

PLAYWRIGHT_CONFIG:  # Playwright 配置（预留）
  TIMEOUT: 30
  POLL_TIME: 200

JENKINS_CONFIG:  # Jenkins 配置（预留）
  JENKINS_ACCOUNT: "demo"
  JENKINS_PWD: "demo"

MYSQl_CONFIG:  # MySQL 配置（预留）
  MYSQl_NAME_DEMO:
    HOST: 127.0.0.1
    PORT: 3306

REDIS_CONFIG:  # Redis 配置（预留）
  HOST: 127.0.0.1
  PORT: 6379

ROBOT_CONfIG:  # 钉钉机器人配置（预留）
  DEMO_ROBOT_NAME:
    url: "https://oapi.dingtalk.com/robot/send?..."
```

---

## 5. 编写测试用例

### 5.1 基础模板

```python
import pytest
import allure
from utils.http_request import HttpRequest
from utils.asserts.assert_manager import AssertManager
from testdata.yamldata_manager import YAMLDataManager

@allure.epic("模块名称")
@allure.feature("功能名称")
@allure.story("子功能名称")
class TestXXX:
    data_manager = YAMLDataManager()
    cases = data_manager.get_cases("testdata/xxx.yaml", "xxx_cases")
    
    @pytest.mark.parametrize("case", cases)
    def test_xxx(self, case):
        case_id = case["case_id"]
        description = case["description"]
        requestdata = case["requestdata"]
        assertion = case["assertion"]
        url = case["url"]
        headers = case["headers"]
        
        try:
            response = HttpRequest(url, method="POST", headers=headers, data=requestdata)
            
            am = AssertManager(soft=True)
            am.equal(response.get_json()["code"], assertion["status_code"])
            am.equal(response.get_json()["msg"], assertion["prompt_msg"])
            am.assert_all()
            
            allure.dynamic.title(f"{case_id}-{description}")
        except AssertionError:
            print(f"测试失败，case_id={case_id}")
            raise
```

### 5.2 YAML 测试数据编写

```yaml
case_common:
  url: "http://api.example.com/xxx"
  headers:
    "Content-Type": "application/json"

xxx_cases:
  - case_id: xxx_001
    description: 正常场景
    requestdata: {...}
    assertion: {...}
```

---

## 6. 运行测试

### 6.1 方式一：使用 runtest.py（推荐）

```bash
python runtest.py
```

**特点：**
- 自动生成 Allure 报告
- 自动复制环境配置
- 支持浏览器打开报告

### 6.2 方式二：直接运行 pytest

```bash
# 运行所有测试
pytest -vs

# 运行指定文件
pytest test_case/test_case_login_yaml.py -vs

# 生成 Allure 结果
pytest --alluredir=./allure-results

# 生成并打开 Allure 报告
allure generate allure-results -c -o allure-report
allure open allure-report
```

---

## 7. 依赖关系图

```
测试用例 (test_case/)
    ↓
YAML数据管理器 (yamldata_manager.py)
    ↓
HTTP请求 (http_request.py) ← 日志 (log.py)
    ↓
断言管理器 (assert_manager.py)
    ↓
核心断言 (assert_core.py) / 软断言 (soft_assert.py)
```

---

## 8. 技术栈

| 技术 | 用途 |
|------|------|
| pytest | 测试框架 |
| Allure | 测试报告 |
| requests | HTTP 请求 |
| PyYAML | YAML 解析 |
| pandas | Excel 数据处理（预留） |
| logging | 日志系统 |

---

## 9. 最佳实践

1. **数据与代码分离**：使用 YAML 管理测试数据
2. **软断言优先**：使用 `AssertManager(soft=True)` 收集所有断言结果
3. **日志追踪**：每条日志都带有 trace_id，便于问题定位
4. **缓存优化**：YAML 数据自动缓存，减少 IO 操作
5. **线程安全**：关键模块使用锁机制，支持并发执行

---

## 10. 扩展建议

- [ ] 增加数据库操作模块（MySQL/Redis 配置已预留）
- [ ] 增加钉钉/企业微信机器人通知
- [ ] 增加数据清理钩子
- [ ] 增加测试用例优先级标记
- [ ] 增加接口依赖支持（setup/teardown）

---

**项目维护者：** chenzj  
**创建时间：** 2026-03-22
