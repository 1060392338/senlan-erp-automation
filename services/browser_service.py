"""BrowserService — Playwright 浏览器工厂（替代旧 DrissionPage 版）

支持：
- 单浏览器模式（默认，共享 Chrome 实例）
- 多会话模式（每个 run_id 独立 persistent_context + user_data_dir）
"""

import logging
import hashlib
import os
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

log = logging.getLogger("browser_service")

ERP_BASE = "http://112.74.35.30"


def _patch_page(page):
    """给 Playwright Page 注入 DrissionPage 兼容方法

    让旧节点代码（process_filler.py / routing_filler.py）无需修改即可运行。
    """
    import types

    # run_js(code) → evaluate() 支持 return 和箭头函数
    def _run_js(self, code):
        # 如果有 return 或包含 =>，包装成 IIFE
        if 'return ' in code or '=>' in code:
            code = f"(function() {{{code}}})()"
        return self.evaluate(code)

    # ele(selector) → locator 的第一匹配
    def _ele(self, selector):
        return self.locator(selector).first

    # eles(selector) → 元素列表，每个有 .text 属性
    def _eles(self, selector):
        return self.locator(selector).all()

    # url 和 title 用 Playwright 原生方法，不覆写
    # DrissionPage 的 .html 用 .content() 替代
    # 兼容用法: page.content() 即可

    # wait.doc_loaded(timeout)
    def _wait_doc_loaded(self, timeout=15):
        self.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)

    # get(url) → goto
    def _get(self, url):
        self.goto(url, wait_until="domcontentloaded")

    page.run_js = types.MethodType(_run_js, page)
    page.ele = types.MethodType(_ele, page)
    page.eles = types.MethodType(_eles, page)
    page.get = types.MethodType(_get, page)
    page.wait = types.SimpleNamespace()
    page.wait.doc_loaded = types.MethodType(_wait_doc_loaded, page)


class BrowserService:
    """Playwright 浏览器工厂

    兼容旧接口：
    - get_page(session_id) → Page 对象
    - close() 释放资源
    """

    def __init__(
        self,
        chrome_data: str = "data/chrome_data",
        port: int = 9223,
    ):
        self._base_data = Path(chrome_data).expanduser().resolve()
        self._base_data.mkdir(parents=True, exist_ok=True)
        self._base_port = port
        self._pw: Optional = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._pages: dict[str, Page] = {}

    def get_page(self, session_id: Optional[str] = None) -> Page:
        """获取 Playwright Page（兼容旧接口返回 Page）

        session_id 用于多会话隔离，首次创建后复用。
        """
        if not session_id:
            session_id = "default"

        if session_id in self._pages:
            return self._pages[session_id]

        # 首次创建该 session 的浏览器
        if self._pw is None:
            self._pw = sync_playwright().start()

        # 每个 session 用独立 user_data_dir
        user_dir = str(self._base_data / f"playwright_{session_id}")
        Path(user_dir).mkdir(parents=True, exist_ok=True)

        try:
            context = self._pw.chromium.launch_persistent_context(
                user_data_dir=user_dir,
                channel="chrome",
                headless=False,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
        except Exception as e:
            log.warning(f"创建 persistent_context 失败: {e}")
            # fallback: 用普通 context
            browser = self._pw.chromium.launch(
                headless=False,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

        page = context.pages[0] if context.pages else context.new_page()
        # 注入 DrissionPage 兼容方法
        _patch_page(page)
        self._context = context
        self._page = page
        self._pages[session_id] = page
        log.info(f"Playwright 浏览器已启动: session={session_id}")
        return page

    def close(self, session_id: Optional[str] = None):
        """释放资源"""
        if session_id and session_id in self._pages:
            try:
                self._pages[session_id].close()
            except Exception:
                pass
            del self._pages[session_id]
            return

        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pages.clear()
        log.info("BrowserService 资源已释放")
