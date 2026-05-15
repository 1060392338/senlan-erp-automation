"""ServiceContainer — 每个 Agent 实例拥有独立的服务容器

替换全局 ServiceRegistry（单例）。每个 ERPProcessAgent 实例创建自己的
ServiceContainer，包含独立的 KB、Template、Drawing 服务。
多 Bot 场景：Bot A 和 Bot B 各自持有独立的 ServiceContainer 实例。
"""

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("service_container")


class ServiceContainerError(Exception):
    """服务容器异常"""


class ServiceContainer:
    """每个 Agent 实例持有独立的 ServiceContainer
    
    用法：
        container = ServiceContainer(config)
        container.kb          # KBService 实例
        container.template    # TemplateService 实例
        container.drawing     # DrawingRegistry 实例
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._kb = None
        self._template = None
        self._drawing = None
        log.info("ServiceContainer 已创建")

    @property
    def kb(self):
        from services.kb_service import KBService
        if self._kb is None:
            # 检查是否启用了知识库（默认跳过，因HuggingFace被墙）
            kb_cfg = self._config.get("services", {}).get("kb", {})
            if kb_cfg.get("enabled", False) is not True:
                log.info("知识库已禁用（config.services.kb.enabled != true），跳过初始化")
                self._kb = None
                return self._kb
            kb_dir = kb_cfg.get("data_dir", "data/documents/")
            idx_dir = kb_cfg.get("index_dir", "data/vector_index/")
            try:
                self._kb = KBService(data_dir=kb_dir, index_dir=idx_dir)
            except Exception as e:
                log.warning(f"知识库初始化失败: {e}")
                self._kb = None
        return self._kb

    @property
    def template(self):
        from services.template_service import TemplateService
        if self._template is None:
            self._template = TemplateService()
        return self._template

    @property
    def drawing(self):
        from services.drawing_registry import DrawingRegistry
        if self._drawing is None:
            self._drawing = DrawingRegistry(self.kb) if self.kb else None
        return self._drawing

    def list(self) -> list[str]:
        services = []
        if self._kb:
            services.append("kb")
        if self._template:
            services.append("template")
        if self._drawing:
            services.append("drawing")
        return services

    def close(self):
        """释放所有服务资源"""
        self._kb = None
        self._template = None
        self._drawing = None
        log.info("ServiceContainer 资源已释放")
