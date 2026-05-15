"""节点: 创建销售订单 — 使用 ctx.browser + ctx.erp_config"""

import logging
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.sales_order")


def node_create_order(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """新建销售订单 → 获取生产单号"""
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})

    log.info(
        f"创建销售订单: {input_data.get('part_name', '')} "
        f"x {input_data.get('qty', 1)}, "
        f"tenant={ctx.tenant_id}"
    )

    # ── 1. 获取浏览器页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        # 降级：使用模拟生产单号
        prod_no = f"PO-{input_data.get('part_name','')[:4]}-{ctx.run_id[-4:].upper()}"
        return {"prod_no": prod_no, "checkpoint": 8}

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")
    order_create_url = f"{erp_url.rstrip('/')}/Sales/OrderCreate"

    # ── 2. 导航到销售订单创建页面 ──
    try:
        log.info(f"导航到销售订单创建页: {order_create_url}")
        page.get(order_create_url)
        page.wait.load_complete(timeout=15)
        log.info("销售订单页面加载完成")
    except Exception as e:
        log.warning(f"导航到销售订单创建页失败: {e}")

    # ── 3. 获取表单字段值 ──
    part_name = input_data.get("part_name", "")
    qty = str(input_data.get("qty", 1))
    deadline = input_data.get("deadline", "")
    customer = input_data.get("customer", "")

    # ── 4. 填写客户/产品/数量/交期等字段 ──
    try:
        # 客户名称
        customer_input = (
            page.ele('@name=customer') or
            page.ele('@name=customer_name') or
            page.ele('@placeholder=客户') or
            page.ele('@@tag=label&&text()=客户')  # 通过 label 关联
        )
        if customer_input:
            customer_input.input(customer)
            log.info(f"客户名称已填入: {customer}")
        else:
            log.warning("未找到客户名称输入框")
    except Exception as e:
        log.warning(f"填入客户名称失败: {e}")

    try:
        # 产品名称/描述
        product_input = (
            page.ele('@name=product') or
            page.ele('@name=product_name') or
            page.ele('@name=part_name') or
            page.ele('@placeholder=产品') or
            page.ele('@placeholder=零件名称')
        )
        if product_input:
            product_input.input(part_name)
            log.info(f"产品名称已填入: {part_name}")
        else:
            log.warning("未找到产品名称输入框")
    except Exception as e:
        log.warning(f"填入产品名称失败: {e}")

    try:
        # 数量
        qty_input = (
            page.ele('@name=quantity') or
            page.ele('@name=qty') or
            page.ele('@name=count') or
            page.ele('@placeholder=数量')
        )
        if qty_input:
            qty_input.input(qty)
            log.info(f"数量已填入: {qty}")
        else:
            log.warning("未找到数量输入框")
    except Exception as e:
        log.warning(f"填入数量失败: {e}")

    try:
        # 交期/截止日期
        if deadline:
            deadline_input = (
                page.ele('@name=deadline') or
                page.ele('@name=delivery_date') or
                page.ele('@name=due_date') or
                page.ele('@placeholder=交期') or
                page.ele('@placeholder=交货日期')
            )
            if deadline_input:
                deadline_input.input(deadline)
                log.info(f"交期已填入: {deadline}")
            else:
                log.warning("未找到交期输入框")
    except Exception as e:
        log.warning(f"填入交期失败: {e}")

    # ── 5. 提交订单 ──
    prod_no = None
    try:
        submit_btn = (
            page.ele('@value=提交') or
            page.ele('@value=保存') or
            page.ele('@value=创建') or
            page.ele('t:button@@text()=提交') or
            page.ele('t:button@@text()=保存') or
            page.ele('@type=submit')
        )
        if submit_btn:
            submit_btn.click()
            log.info("已点击提交按钮")
            page.wait.load_complete(timeout=15)
        else:
            log.warning("未找到提交按钮")
    except Exception as e:
        log.warning(f"点击提交按钮失败: {e}")

    # ── 6. 从响应页面提取生产单号 ──
    try:
        page.wait.load_complete(timeout=10)
        page_text = page.html
        page_url = page.url

        log.info(f"提交后页面 URL: {page_url}")

        # 尝试多种方式提取 prod_no
        # 方式1: 从 URL 参数中提取
        if "prod_no=" in page_url:
            prod_no = page_url.split("prod_no=")[1].split("&")[0]
            log.info(f"从 URL 提取生产单号: {prod_no}")

        # 方式2: 从页面中查找生产单号显示区域
        if not prod_no:
            prod_no_elem = (
                page.ele('@name=prod_no') or
                page.ele('@id=prod_no') or
                page.ele('@@text()=生产单号')
            )
            if prod_no_elem:
                # 找到生产单号标签旁边的值
                parent = prod_no_elem.parent()
                if parent:
                    next_ele = parent.ele('tag:span') or parent.ele('tag:input')
                    if next_ele:
                        prod_no = next_ele.text or next_ele.value
                        log.info(f"从页面元素提取生产单号: {prod_no}")

        # 方式3: 从页面文本中正则提取
        if not prod_no:
            import re
            match = re.search(r'[Pp][Oo][-_]?\d{6,}', page_text)
            if match:
                prod_no = match.group(0)
                log.info(f"从页面文本正则提取生产单号: {prod_no}")

        # 方式4: 如果还是没有，检查成功提示
        if not prod_no:
            if any(kw in page_text for kw in ["成功", "保存成功", "提交成功", "创建成功"]):
                log.info("订单提交成功，但未能提取具体生产单号")
            else:
                log.warning("订单提交后未找到成功标识，页面内容可能不完整")
    except Exception as e:
        log.warning(f"提取生产单号失败: {e}")

    # ── 7. 最终降级 ──
    if not isinstance(prod_no, str):
        prod_no = f"PO-{part_name[:4]}-{ctx.run_id[-4:].upper()}"
        log.warning(f"未能从 ERP 页面提取生产单号，使用降级生成: {prod_no}")

    return {"prod_no": prod_no, "checkpoint": 8}
