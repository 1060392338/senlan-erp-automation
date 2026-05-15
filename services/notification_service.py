"""
NotificationService — 飞书消息通知

支持两种模式：
  1. Webhook 模式：简单 POST JSON 到飞书机器人 Webhook URL
  2. API 模式：通过飞书开放平台 API 发送格式化消息（需 app_id/app_secret）

每个租户可独立配置通知目标。
"""

import json
import logging
from typing import Optional

log = logging.getLogger("notification")


class FeishuNotifier:
    """飞书消息发送（同时支持 Webhook 和 API 两种模式）"""

    def __init__(self, config: dict):
        self._webhook_url = config.get("webhook_url", "")
        self._app_id = config.get("app_id", "")
        self._app_secret = config.get("app_secret", "")
        self._default_open_id = config.get("default_open_id", "")
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ── 发送消息入口 ──

    def send_text(self, text: str, open_id: Optional[str] = None) -> bool:
        """发送纯文本消息"""
        if self._webhook_url:
            return self._send_webhook({"msg_type": "text", "content": {"text": text}})
        return self._send_api(open_id or self._default_open_id, "text", {"text": text})

    def send_card(self, title: str, content: str, color: str = "blue") -> bool:
        """发送卡片消息（带格式）"""
        card = self._build_card(title, content, color)
        if self._webhook_url:
            return self._send_webhook({"msg_type": "interactive", "card": card})
        return self._send_api(
            self._default_open_id, "interactive", card
        )

    # ── 工作流专用通知 ──

    def notify_workflow_start(self, tenant_name: str, part_name: str) -> bool:
        return self.send_card(
            f"🚀 工艺工作流开始",
            f"**租户**: {tenant_name}\n**零件**: {part_name}\n**状态**: 正在登录 ERP…",
            "blue",
        )

    def notify_phase1_complete(self, tenant_name: str, prod_no: str) -> bool:
        return self.send_card(
            f"✅ Phase 1 完成",
            f"**租户**: {tenant_name}\n**生产单号**: {prod_no}\n手动运行 `--resume` 继续 AI 推理",
            "green",
        )

    def notify_cnc_ready(self, tenant_name: str, prod_no: str) -> bool:
        return self.send_card(
            f"🤖 CNC 代码待审核",
            f"**租户**: {tenant_name}\n**生产单号**: {prod_no}\nCNC 代码已生成，请人工审核后确认继续",
            "orange",
        )

    def notify_workflow_complete(self, tenant_name: str, prod_no: str) -> bool:
        return self.send_card(
            f"✅ 工作流完成",
            f"**租户**: {tenant_name}\n**生产单号**: {prod_no}\n计划工艺 + CNC 代码已回填 ERP",
            "green",
        )

    def notify_error(self, tenant_name: str, prod_no: str, error: str) -> bool:
        return self.send_card(
            f"❌ 工作流出错",
            f"**租户**: {tenant_name}\n**生产单号**: {prod_no}\n**错误**: {error}",
            "red",
        )

    # ── 内部实现 ──

    def _send_webhook(self, payload: dict) -> bool:
        if not self._webhook_url:
            return False
        try:
            import requests
            resp = requests.post(self._webhook_url, json=payload, timeout=10)
            ok = resp.status_code == 200
            if not ok:
                log.warning(f"飞书 Webhook 发送失败: {resp.status_code}")
            return ok
        except Exception as e:
            log.warning(f"飞书 Webhook 异常: {e}")
            return False

    def _send_api(self, open_id: str, msg_type: str, content: dict) -> bool:
        if not open_id or not self._app_id:
            return False
        try:
            import requests
            token = self._get_token()
            if not token:
                return False
            resp = requests.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": open_id,
                    "msg_type": msg_type,
                    "content": json.dumps(content) if isinstance(content, dict) else content,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            log.warning(f"飞书 API 发送失败: {e}")
            return False

    def _get_token(self) -> Optional[str]:
        """获取飞书 tenant_access_token（含 2h 过期自动刷新）"""
        import time
        now = time.time()
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token
        try:
            import requests
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 0:
                self._token = data["tenant_access_token"]
                expire = data.get("expire", 7200)
                self._token_expiry = now + expire - 600
                return self._token
            else:
                log.warning(f"飞书 token 刷新失败: {data.get('msg')}")
                return None
        except Exception as e:
            log.warning(f"飞书 token 获取失败: {e}")
            return None

    @staticmethod
    def _build_card(title: str, content: str, color: str = "blue") -> dict:
        color_map = {"blue": "blue", "green": "green", "red": "red", "orange": "orange"}
        return {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color_map.get(color, "blue"),
            },
            "elements": [{"tag": "markdown", "content": content}],
        }
