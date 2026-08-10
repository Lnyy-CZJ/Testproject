"""Truthy_ApiAutoTest2 平台接入壳服务包。

功能说明:
    提供薄 Web 层（Flask），把既有 pytest 接口自动化框架包装为
    平台可调用的服务：任务提交/取消/查询、结果与日志展示、用例库清单
    与 Allure 报告静态托管。本包只读复用 ``utils/custom`` 的加载器，
    不修改框架核心行为。
"""
