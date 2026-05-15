"""节点: ERP 重新登录（Phase 3 入口）

Phase 1 和 Phase 3 之间可能隔很久，session 已过期，需重新登录。
"""

import logging
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process._login import fill_login_form, verify_login
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.erp_reconnect")


def node_erp_reconnect(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """Phase 3：重新登录 ERP 刷新 session cookie"""
    ctx = config["configurable"]["ctx"]

    log.info(
        f"ERP 重新登录: session={ctx.session_id}, "
        f"prod_no={state.get('prod_no')}"
    )

    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
        log.info("已获取浏览器页面，准备重新登录刷新 session")
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        return {"errors": [f"获取浏览器页面失败: {e}"], "checkpoint": Checkpoint.LOGIN_FAILED}

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")
    username = ctx.erp_config.get("username", "")
    password = ctx.erp_config.get("password", "")

    fill_login_form(page, erp_url, username, password)

    login_success = verify_login(page, erp_url)
    if not login_success:
        log.warning("重新登录失败，尝试继续执行（Phase 3 重连失败可能不影响后续操作）")

    # 导航到ERP首页，等待SPA完全加载，再设hash
    try:
        import time
        # 先导航到首页让SPA初始化
        page.get(erp_url.rstrip('/') + '/')
        time.sleep(4)

        # 然后设置SPA hash路由
        page.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
        time.sleep(4)

        # 验证是否真的在计划工艺页
        page_text = page.run_js("return document.body.innerText.substring(0, 800)")
        if '计划工艺' in page_text:
            log.info(f"✓ SPA hash导航成功到计划工艺页")
        else:
            log.warning(f"SPA hash未生效，当前页面URL: {page.url[:80]}, 内容: {page_text[:80]}")
            # fallback: 直接URL
            craft_url = f"{erp_url.rstrip('/')}/#/Craftwork/steel_craftworkList/0210"
            page.get(craft_url)
            time.sleep(5)
            page_text2 = page.run_js("return document.body.innerText.substring(0, 800)")
            log.info(f"fallback导航后URL: {page.url[:80]}, '计划工艺' in content: {'计划工艺' in page_text2}")
    except Exception as e:
        log.warning(f"导航到计划工艺页面失败: {e}")

    return {"checkpoint": Checkpoint.RECONNECTED}
