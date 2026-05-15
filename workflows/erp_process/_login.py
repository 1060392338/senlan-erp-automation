"""ERP 登录公共逻辑 — 被 node_login 和 node_erp_reconnect 共享"""

import logging
import time

log = logging.getLogger("erp_login")


def fill_login_form(page, erp_url: str, username: str, password: str) -> None:
    """导航到 ERP 登录页，填充用户名密码并提交。不抛异常。"""
    try:
        page.get(f"{erp_url.rstrip('/')}/Login?ReturnUrl=%2F")
        page.wait.doc_loaded(timeout=15)
        log.info("ERP 登录页面加载完成")
    except Exception as e:
        log.warning(f"导航到 ERP 页面失败: {e}")

    # ── 填写用户名 ──
    try:
        username_input = (
            page.ele('@name=username') or
            page.ele('@name=user') or
            page.ele('@id=username') or
            page.ele('@placeholder=用户名') or
            page.ele('@placeholder=账号')
        )
        if username_input:
            username_input.input(username)
            log.info("用户名已填入")
        else:
            log.warning("未找到用户名输入框")
    except Exception as e:
        log.warning(f"填入用户名失败: {e}")

    # ── 填写密码 ──
    try:
        password_input = (
            page.ele('@name=password') or
            page.ele('@name=pwd') or
            page.ele('@id=password') or
            page.ele('@placeholder=密码') or
            page.ele('@placeholder=口令')
        )
        if password_input:
            password_input.input(password)
            log.info("密码已填入")
        else:
            log.warning("未找到密码输入框")
    except Exception as e:
        log.warning(f"填入密码失败: {e}")

    # ── 点击登录按钮 ──
    try:
        login_btn = (
            page.ele('t:span@@class=login') or  # 实际: <span class="login">登录</span>
            page.ele('@value=登录') or
            page.ele('@value=登 录') or
            page.ele('t:button@@text()=登录') or
            page.ele('@type=submit') or
            page.ele('tag:button@@text()=登录')
        )
        if login_btn:
            login_btn.click()
            log.info("已点击登录按钮")
            page.wait.doc_loaded(timeout=10)
        else:
            log.warning("未找到登录按钮，尝试按 Enter 提交")
            page.run_js("document.querySelector('form')?.requestSubmit()")
    except Exception as e:
        log.warning(f"点击登录按钮失败: {e}")


def verify_login(page, erp_url: str) -> bool:
    """验证登录是否成功。返回 True/False。"""
    try:
        page.wait.doc_loaded(timeout=10)
        time.sleep(2)  # 等待SPA加载
        page_text = page.html
        page_url = page.url
        page_title = page.title

        # 检查页面内容包含登录后特有元素
        if any(kw in page_text for kw in ["退出", "注销", "工作台", "个人资料", "修改密码"]):
            log.info("ERP 登录验证成功 — 页面包含登录后关键字")
            return True

        # 检查 URL 跳转
        if page_url and "login" not in page_url.lower() and page_url != erp_url:
            log.info(f"ERP 登录验证成功 — URL 已跳转: {page_url}")
            return True

        # 检查页面标题
        if "登录" not in page_title:
            log.info(f"ERP 登录验证成功 — 页面标题: {page_title}")
            return True

        # 检查标题栏 - 尝试找用户名称/ID
        user_span = page.ele('@@text()=472')
        if user_span:
            log.info("ERP 登录验证成功 — 找到用户ID")
            return True

        log.warning("ERP 登录验证失败 — 页面仍处于登录状态或未跳转")
        return False
    except Exception as e:
        log.warning(f"登录验证异常: {e}")
        return False
