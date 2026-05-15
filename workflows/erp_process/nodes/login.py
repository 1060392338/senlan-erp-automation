"""节点: ERP 登录 — 使用 ctx.browser 获取页面"""

import logging
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process._login import fill_login_form, verify_login
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.login")


def node_login(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """登录 ERP 系统"""
    ctx = config["configurable"]["ctx"]
    page = ctx.browser.get_page(session_id=ctx.session_id)

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")
    username = ctx.erp_config.get("username", "")
    password = ctx.erp_config.get("password", "")

    log.info(
        f"ERP 登录: {erp_url} "
        f"user={username}, session={ctx.session_id}"
    )

    fill_login_form(page, erp_url, username, password)

    login_success = verify_login(page, erp_url)
    if not login_success:
        log.error("ERP 登录失败，工作流无法继续")
        return {
            "session_id": ctx.session_id,
            "errors": ["ERP 登录失败 — 页面仍处于登录状态或未跳转"],
"checkpoint": Checkpoint.LOGIN_DONE,
        }

    return {"session_id": ctx.session_id, "checkpoint": Checkpoint.LOGIN_DONE}
