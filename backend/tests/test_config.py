"""配置读取单元测试。"""

from flow_agent.config.source_values import ConfigValues


def test_config_values_reads_only_explicit_config_mapping(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "false")
    values = ConfigValues(
        external_config={
            "channels": {
                "http_enabled": True,
                "http_port": 9900,
            },
            "jobs": {"max_async_workers": 3},
        },
        project_root=tmp_path,
    )

    assert values.get_bool(("channels", "http_enabled"), False) is True
    assert values.get_int(("channels", "http_port"), 0, minimum=1) == 9900
    assert values.get_int(("jobs", "max_async_workers"), 1, minimum=1) == 3
    assert values.env_bool("FLOW_AGENT_CHANNEL_HTTP_ENABLED", True) is True
