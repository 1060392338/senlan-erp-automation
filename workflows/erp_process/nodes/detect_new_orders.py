"""节点: 检测新生产单 — 扫描计划工艺模块的发送时间字段

流程：
  1. 使用 ctx.browser 登录 ERP
  2. 导航到「计划管理 → 计划工艺」模块
  3. 查找「发送时间」字段，筛选今天的生产单
  4. 提取生产单号列表，返回 state
"""

import logging
import re
import time
from datetime import date
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("node.detect_new_orders")


def node_detect_new_orders(
    state: ERPState, config: RunnableConfig, services: Optional[dict] = None
) -> dict:
    """扫描计划工艺模块，检测今天的新生产单"""
    ctx = config["configurable"]["ctx"]
    log.info(f"检测新生产单: tenant={ctx.tenant_id}, session={ctx.session_id}")

    # ── 1. 获取浏览器页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        return {
            "new_orders": [],
            "pending_order_idx": 0,
            "checkpoint": Checkpoint.ORDERS_DETECTED,
            "errors": [f"获取浏览器页面失败: {e}"],
        }

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")

    # ── 2. 导航到计划工艺页面（Vue SPA 路由） ──
    # 实际路由: #/Craftwork/steel_craftworkList/0210
    navigate_ok = False
    try:
        page.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
        page.wait.doc_loaded(timeout=10)
        time.sleep(2)
        current_url = page.url
        if "Craftwork" in current_url or "0210" in current_url:
            navigate_ok = True
            log.info(f"计划工艺页面加载成功: {current_url}")
    except Exception as e:
        log.warning(f"SPA路由导航失败: {e}")

    # 降级：尝试点击菜单导航
    if not navigate_ok:
        try:
            log.info("哈希路由失败，尝试点击菜单导航")
            page.run_js("""
                // 展开计划管理
                let items = document.querySelectorAll('.menu-wrapper');
                for (let item of items) {
                    if (item.textContent.trim() === '计划管理' && !item.classList.contains('nest-menu')) {
                        item.click(); break;
                    }
                }
            """)
            time.sleep(1.5)
            page.run_js("""
                // 点击计划工艺
                let items = document.querySelectorAll('.nest-menu');
                for (let item of items) {
                    if (item.textContent.trim().includes('计划工艺')) {
                        let a = item.querySelector('a');
                        if (a) a.click(); else item.click();
                        break;
                    }
                }
            """)
            time.sleep(2)
            navigate_ok = True
            log.info("通过菜单导航到计划工艺成功")
        except Exception as e:
            log.warning(f"菜单导航失败: {e}")

    if not navigate_ok:
        log.error("无法导航到计划工艺页面")
        return {
            "new_orders": [],
            "pending_order_idx": 0,
            "checkpoint": Checkpoint.ORDERS_DETECTED,
            "errors": ["无法导航到计划工艺页面"],
        }

    # ── 3. 如果用户已指定生产单号，直接使用 ──
    input_data = state.get("input", {})
    if input_data.get("prod_no"):
        prod_no = input_data["prod_no"]
        log.info(f"用户已指定生产单号: {prod_no}，跳过自动扫描")
        return {
            "new_orders": [{"prod_no": prod_no}],
            "pending_order_idx": 0,
            "prod_no": prod_no,
            "checkpoint": Checkpoint.ORDERS_DETECTED,
        }

    # ── 4. 扫描今天的生产单 ──
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    today_short = today.strftime("%Y/%m/%d")
    log.info(f"筛选今天的生产单 (发送时间 = {today_str})")

    new_orders = []
    try:
        page.wait.doc_loaded(timeout=5)
        html = page.html

        # 尝试多种方式提取生产单号和发送时间
        # 方式1: 从表格行中提取
        rows = page.eles("tag:tr")
        for row in rows:
            try:
                row_text = row.text
                # 检查是否包含今天的日期
                if today_str in row_text or today_short in row_text:
                    # 提取生产单号（通常是字母+数字的组合）
                    prod_no_match = re.search(r'[A-Za-z]{2,}[-_]?\d{6,}', row_text)
                    if prod_no_match:
                        prod_no = prod_no_match.group(0)
                        new_orders.append({
                            "prod_no": prod_no,
                            "send_time": today_str,
                            "raw_text": row_text[:100],
                        })
                        log.info(f"检测到新生产单: {prod_no}")
            except Exception:
                continue

        # 方式2: 通过发送时间字段名查找
        send_time_elem = (
            page.ele("@name=发送时间") or
            page.ele("@name=send_time") or
            page.ele("@@text()=发送时间")
        )
        if send_time_elem and not new_orders:
            log.info("找到发送时间字段，尝试获取相邻数据")

    except Exception as e:
        log.warning(f"提取生产单数据失败: {e}")

    # ── 4. 如果没有找到新订单 ──
    if not new_orders:
        log.info(f"今天 ({today_str}) 没有新的生产单")
        return {
            "new_orders": [],
            "pending_order_idx": 0,
            "checkpoint": Checkpoint.ORDERS_DETECTED,
        }

    log.info(f"检测到 {len(new_orders)} 个新生产单")
    return {
        "new_orders": new_orders,
        "pending_order_idx": 0,
        "checkpoint": Checkpoint.ORDERS_DETECTED,
    }
