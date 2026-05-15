"""
TenantContext — 租户配置工厂

接收原始租户配置 dict，返回展平后的纯字典。
所有值必须是可序列化的（str/int/bool/list/dict）。

使用:
    tenant_cfg = build_tenant_config(raw_config)
    state["tenant_config"] = tenant_cfg
    # node 中: state["tenant_config"]["erp"]["username"]
"""


def build_tenant_config(raw: dict) -> dict:
    """从原始配置构建不可变租户配置字典"""
    return {
        "id": raw.get("id", "default"),
        "display_name": raw.get("display_name", raw.get("id", "default")),
        "enabled": raw.get("enabled", True),
        "erp": dict(raw.get("erp", {})),
        "drawing_dir": raw.get("drawing_dir", "data/drawings/"),
        "feishu": dict(raw.get("feishu", {})),
        "notify_on": list(raw.get("feishu", {}).get("notify_on", [])),
    }


def should_notify(tenant_config: dict, event: str) -> bool:
    """检查租户是否订阅了该通知事件"""
    return event in tenant_config.get("notify_on", [])
