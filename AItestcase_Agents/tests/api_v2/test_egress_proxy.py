"""出口代理登记目标、DNS 重绑定和 SSRF 负向测试。"""

def test_proxy_only_finds_registered_host(monkeypatch):
    """完整 URL 中的未登记 Host 不得进入 DNS 或转发阶段。"""

    import importlib
    monkeypatch.setenv(
        "REGISTERED_TARGETS",
        '[{"target_id":"local","schemes":["http"],"hosts":["platform-gateway"],"ports":[80],"path_prefixes":["/api/v1/"],"allowed_cidrs":["172.16.0.0/12"]}]',
    )
    proxy_app = importlib.import_module("services.egress_proxy.app")
    assert proxy_app.find_target("http://platform-gateway/api/v1/health/live") is not None
    assert proxy_app.find_target("http://127.0.0.1/api/v1/health/live") is None
    assert proxy_app.find_target("http://169.254.169.254/latest/meta-data") is None
    assert proxy_app.find_target("http://platform-gateway.evil.test/api/v1/health/live") is None
