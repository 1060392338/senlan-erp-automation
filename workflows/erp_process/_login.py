"""ERP 登录公共逻辑 — Playwright 版（替代旧 DrissionPage 版）

被 node_login 和 node_erp_reconnect 共享。
"""

import logging
import os
import time

from playwright.sync_api import Page

log = logging.getLogger("erp_login")


def fill_login_form(page: Page, erp_url: str, username: str, password: str) -> None:
    """导航到 ERP 登录页，填充用户名密码并提交。不抛异常。"""
    try:
        page.goto(f"{erp_url.rstrip('/')}/Login?ReturnUrl=%2F",
                  wait_until="domcontentloaded", timeout=15000)
        log.info("ERP 登录页面加载完成")
    except Exception as e:
        log.warning(f"导航到 ERP 页面失败: {e}")

    time.sleep(2)

    # ── 填写用户名 ──
    try:
        username_input = page.locator('input[name="username"]').first
        if username_input.count() > 0:
            username_input.fill(username)
            log.info("用户名已填入")
        else:
            log.warning("未找到用户名输入框 (name=username)")
    except Exception as e:
        log.warning(f"填入用户名失败: {e}")

    # ── 填写密码 ──
    try:
        password_input = page.locator('input[name="password"]').first
        if password_input.count() > 0:
            password_input.fill(password)
            log.info("密码已填入")
        else:
            log.warning("未找到密码输入框 (name=password)")
    except Exception as e:
        log.warning(f"填入密码失败: {e}")

    # ── 点击登录按钮 ──
    try:
        login_btn = page.locator("span.login").first
        if login_btn.count() > 0:
            login_btn.click()
            log.info("已点击登录按钮")
            time.sleep(5)
        else:
            log.warning("未找到span.login，尝试按Enter")
            page.keyboard.press("Enter")
            time.sleep(5)
    except Exception as e:
        log.warning(f"点击登录按钮失败: {e}")


def verify_login(page: Page, erp_url: str) -> bool:
    """验证登录是否成功。返回 True/False。"""
    try:
        time.sleep(3)
        page_text = page.evaluate("document.body.innerText")
        page_url = page.url
        page_title = page.title()

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

        # 检查标题栏 - 找用户ID 473
        user_found = page.evaluate("""() => {
            for (let el of document.querySelectorAll('*')) {
                if (el.textContent && el.textContent.trim() === '473') return true;
            }
            return false;
        }""")
        if user_found:
            log.info("ERP 登录验证成功 — 找到用户ID 473")
            return True

        log.warning("ERP 登录验证失败 — 页面仍处于登录状态或未跳转")
        return False
    except Exception as e:
        log.warning(f"登录验证异常: {e}")
        return False
