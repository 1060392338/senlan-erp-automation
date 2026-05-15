"""
RequestContext — 请求级上下文

核心设计：
- 每个 agent.run() 创建一个 RequestContext
- run_id 隔离：每个 run 拥有独立的 LLMClient + BrowserService
- 共享服务（KB/Template）保持共享（只读，线程安全）
- node 函数通过 config['configurable']['ctx'] 获取

解决了：
1. ServiceRegistry 全局单例 → 多租户/多用户不可并行
2. _tenant 不可序列化塞进 TypedDict
3. 每个 node 自己 ServiceRegistry.get() 的分散获取
4. ChatHistoryService 管理多轮对话历史
5. user_id 为多用户隔离（多 Bot 场景：Bot A 只处理自己用户的会话）"""

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("context")


def _build_llm_client(tenant_config: dict, global_config: dict):
    """每个 run 创建独立的 LLMClient（不同租户可用不同模型/API Key）"""
    from services.llm_client import LLMClient

    env_prefix = tenant_config.get("env_prefix", "")
    services_cfg = global_config.get("services", {}).get("llm", {})

    # 优先用 env_prefix 从环境变量读 API Key
    api_key = tenant_config.get("api_key") or services_cfg.get("api_key", "")

    return LLMClient(
        base_url=services_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=api_key or None,
        default_model=services_cfg.get("default_model", "qwen-max"),
        vision_model=services_cfg.get("vision_model", "qwen-vl-max"),
    )


def _build_browser_service(tenant_config: dict, run_id: str, global_config: dict):
    """每个 run 创建独立的 BrowserService（端口+data-dir 隔离）"""
    from services.browser_service import BrowserService

    browser_cfg = global_config.get("services", {}).get("browser", {})
    base_port = browser_cfg.get("port", 9223)
    chrome_data = browser_cfg.get("chrome_data", "data/chrome_data")

    # 每个 run_id 从不同基端口分配，避免端口冲突
    import hashlib
    port_offset = int(hashlib.md5(run_id.encode()).hexdigest()[:4], 16) % 100
    port = base_port + port_offset

    return BrowserService(
        chrome_data=f"{chrome_data}/{run_id}",
        port=port,
    )


def _build_state_service(tenant_id: str, global_config: dict):
    """按 tenant_id 隔离 state 文件"""
    from services.state_service import StateService
    state_cfg = global_config.get("services", {}).get("state", {})
    return StateService(
        state_dir=state_cfg.get("state_dir", "data/states/"),
    )


@dataclass
class RequestContext:
    """
    单个请求的运行时上下文。
    每个 agent.run() 创建一个实例，node 函数通过 run config 获取。
    """

    run_id: str
    tenant_id: str
    user_id: str  # 多用户隔离：Bot A 的 user A1 / user A2
    tenant_config: dict  # 纯字典，可序列化
    global_config: dict  # 全局配置

    # 运行时服务实例（每个 run 独立）
    llm: object = field(default=None)
    browser: object = field(default=None)
    notifier: object = field(default=None)

    # 共享服务（通过引用传递，需线程安全）
    kb: object = field(default=None)
    template: object = field(default=None)
    drawing_registry: object = field(default=None)
    state: object = field(default=None)
    chat_history: object = field(default=None)  # ChatHistoryService 实例

    _services: dict = field(default_factory=dict)
    _closed: bool = field(default=False)

    @classmethod
    def create(
        cls,
        tenant_config: dict,
        run_id: str,
        global_config: dict,
        user_id: str = "default",
        shared_kb=None,
        shared_template=None,
        shared_drawing=None,
        chat_history=None,
    ) -> "RequestContext":
        """工厂方法：创建完整的请求上下文"""

        tenant_id = tenant_config.get("id", "default")
        log.info(f"创建 RequestContext: tenant={tenant_id}, user={user_id}, run_id={run_id}")

        # 独立服务
        llm = _build_llm_client(tenant_config, global_config)
        browser = _build_browser_service(tenant_config, run_id, global_config)
        state = _build_state_service(tenant_id, global_config)

        # 构建 notifier
        feishu_cfg = tenant_config.get("feishu", {})
        if feishu_cfg:
            global_feishu = global_config.get("services", {}).get("feishu", {})
            merged = {**global_feishu, **feishu_cfg}
            from services.notification_service import FeishuNotifier
            notifier = FeishuNotifier(merged)
        else:
            notifier = None

        return cls(
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_config=tenant_config,
            global_config=global_config,
            llm=llm,
            browser=browser,
            notifier=notifier,
            kb=shared_kb,
            template=shared_template,
            drawing_registry=shared_drawing,
            state=state,
            chat_history=chat_history,
        )

    @property
    def session_id(self) -> str:
        """浏览器会话隔离 key"""
        return f"{self.tenant_id}-{self.run_id}"

    @property
    def display_name(self) -> str:
        return self.tenant_config.get("display_name", self.tenant_id)

    @property
    def erp_config(self) -> dict:
        return self.tenant_config.get("erp", {})

    @property
    def should_notify(self) -> bool:
        """是否有飞书通知配置"""
        return self.notifier is not None

    def get_service(self, name: str):
        """按需获取服务（兼容旧模式）"""
        if name not in self._services:
            from services import ServiceRegistry
            self._services[name] = ServiceRegistry.get(name)
        return self._services[name]

    def close(self):
        """释放资源"""
        if self._closed:
            return
        self._closed = True
        try:
            if self.browser:
                self.browser.close()
                log.info(f"浏览器资源已释放: run_id={self.run_id}")
        except Exception as e:
            log.warning(f"释放浏览器资源失败: {e}")
