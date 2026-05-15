"""
BrowserService — 浏览器工厂

支持：
- 单浏览器模式（默认，共享 Chrome 实例）
- 多会话模式（不同用户用不同的 Chrome 实例 + 端口 + 数据目录）
"""

import subprocess
import socket
import logging
from pathlib import Path
from typing import Optional
from DrissionPage import ChromiumPage, ChromiumOptions

log = logging.getLogger("browser_service")


class BrowserService:
    def __init__(
        self,
        chrome_data: str = "data/chrome_data",
        port: int = 9223,
    ):
        self._base_data = Path(chrome_data).expanduser().resolve()
        self._base_data.mkdir(parents=True, exist_ok=True)
        self._base_port = port
        self._pages: dict[str, ChromiumPage] = {}

    def get_page(self, session_id: Optional[str] = None) -> ChromiumPage:
        """
        获取浏览器页面。

        session_id=None: 共享实例（默认，现有行为不变）
        session_id=xxx:  独立实例，每个 session_id 拥有自己的 Chrome + 数据目录
                         不同用户传不同 session_id → 互不干扰
        """
        key = session_id or "__default__"

        # 已有实例 → 复用
        if key in self._pages:
            try:
                page = self._pages[key]
                if page.tabs:
                    return page.latest_tab
            except Exception:
                pass  # 实例已死，重新创建

        chrome_dir = self._base_data / (session_id or "")
        chrome_dir.mkdir(parents=True, exist_ok=True)
        port = self._base_port if not session_id else self._find_free_port(start=self._base_port)

        # 先尝试连接已有 Chrome（同 session_id 的旧实例可能还活着）
        if session_id:
            try:
                page = ChromiumPage(addr_or_opts=port)
                if page.tabs_count > 1:
                    page = page.latest_tab
                self._pages[key] = page
                return page
            except Exception:
                pass

        # 启动新 Chrome
        co = ChromiumOptions()
        co.set_argument("--remote-debugging-port", str(port))
        co.set_argument("--remote-allow-origins", "*")
        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_user_data_path(str(chrome_dir))
        page = ChromiumPage(addr_or_opts=co)
        self._pages[key] = page
        log.info(f"启动新 Chrome: port={port}, data={chrome_dir.name}, key={key}")
        return page

    def close(self, session_id: Optional[str] = None):
        """关闭指定会话或全部会话的浏览器实例"""
        if session_id:
            page = self._pages.pop(f"{session_id}", None)
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
        else:
            for key, page in list(self._pages.items()):
                try:
                    page.quit()
                except Exception:
                    pass
            self._pages.clear()

    def quit(self):
        """关闭所有浏览器实例并清理"""
        self.close(None)

    def cleanup_locks(self, session_id: Optional[str] = None):
        """清理 Chrome 锁文件"""
        chrome_dir = self._base_data / (session_id or "")
        subprocess.run(
            ["rm", "-f",
             str(chrome_dir / "SingletonLock"),
             str(chrome_dir / "SingletonSocket"),
             str(chrome_dir / "Default" / "LOCK")],
            capture_output=True,
        )

    @staticmethod
    def _find_free_port(start: int = 9300, max_tries: int = 100) -> int:
        """找到可用端口"""
        for port in range(start, start + max_tries):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return start
