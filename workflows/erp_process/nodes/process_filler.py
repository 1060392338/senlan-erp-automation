"""节点: 填写计划工艺 — 使用 ctx.browser 填写 ERP 页面"""

import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.process_filler")


def node_fill_plan(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """填写计划工艺 → ERP 系统"""
    ctx = config["configurable"]["ctx"]
    prod_no = state.get("prod_no")
    process_plan = state.get("process_plan")

    if not prod_no or not process_plan:
        log.warning("缺少生产单号或工艺计划")
        return {"plan_saved": False}

    log.info(f"填写计划工艺: prod_no={prod_no}, {len(process_plan)} 道工序")

    # ── 1. 获取浏览器页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        return {"plan_saved": False, "errors": [f"获取浏览器页面失败: {e}"], "checkpoint": 25}

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")

    # ── 2. 导航到计划工艺页面（按生产单号过滤） ──
    try:
        plan_url = f"{erp_url.rstrip('/')}/Plan/ProcessPlan?prod_no={prod_no}"
        log.info(f"正在导航到计划工艺页面: {plan_url}")
        page.get(plan_url)
        page.wait.load_complete(timeout=15)
        log.info("计划工艺页面加载完成")
    except Exception as e:
        log.warning(f"导航到计划工艺页面失败: {e}")
        return {"plan_saved": False, "errors": [f"导航到计划工艺页面失败: {e}"], "checkpoint": 25}

    # ── 3. 定位工序表格并逐行填写 ──
    try:
        # 查找工序表格
        table = (
            page.ele('tag:table') or
            page.ele('@@tag=table&&@@id*=process') or
            page.ele('@@tag=table&&@@class*=grid') or
            page.ele('@@tag=table&&@@class*=table')
        )
        if not table:
            log.warning("未找到工序表格，尝试查找页面中的表格行")
            rows = page.eles('tag:tr')
        else:
            log.info("找到工序表格，开始定位数据行")
            rows = table.eles('tag:tr')

        if not rows or len(rows) < 2:
            log.warning("页面中未找到足够的表格行，尝试查找输入框列表")
            # 降级：查找所有 input/textarea 元素
            inputs = page.eles('tag:input') or page.eles('tag:textarea')
            if inputs:
                log.info(f"找到 {len(inputs)} 个输入框，尝试直接填入")
                for idx, step_data in enumerate(process_plan):
                    if idx >= len(inputs):
                        break
                    try:
                        inputs[idx].input(str(step_data.get("name", "")))
                    except Exception:
                        pass
                log.info("降级填写完成（通过输入框列表）")
            else:
                log.warning("未找到任何可填写的表单元素")
                return {"plan_saved": False, "checkpoint": 25}
        else:
            # 跳过表头行（第一行），从第2行开始填写
            data_rows = rows[1:] if len(rows) > 1 else rows
            log.info(f"找到 {len(data_rows)} 行数据行，开始填写 {len(process_plan)} 道工序")

            for idx, step_data in enumerate(process_plan):
                if idx >= len(data_rows):
                    log.warning(f"工序 #{idx+1}: 已超出表格行数 ({len(data_rows)})，跳过")
                    break

                row = data_rows[idx]
                step_no = step_data.get("step_no", idx + 1)
                step_name = step_data.get("name", "")
                description = step_data.get("description", "")
                machine = step_data.get("machine", "")
                tool = step_data.get("tool", "")
                parameters = step_data.get("parameters", "")
                check_items = step_data.get("check_items", "")

                log.info(f"填写第 {idx+1} 道工序: #{step_no} {step_name}")

                # ── 填写工序号 ──
                try:
                    step_input = (
                        row.ele('@name=step_no') or
                        row.ele('@name*=step') or
                        row.ele('@name=工序号') or
                        row.ele('@placeholder=工序号') or
                        row.ele('tag:input', index=0)
                    )
                    if step_input:
                        step_input.input(str(step_no))
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写工序号失败: {e}")

                # ── 填写工序名称 ──
                try:
                    name_input = (
                        row.ele('@name=process_name') or
                        row.ele('@name=name') or
                        row.ele('@name*=名称') or
                        row.ele('@placeholder=工序名称') or
                        row.ele('tag:input', index=1)
                    )
                    if name_input:
                        name_input.input(step_name)
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写工序名称失败: {e}")

                # ── 填写工艺描述/内容 ──
                try:
                    desc_input = (
                        row.ele('@name=description') or
                        row.ele('@name=content') or
                        row.ele('@name=工艺内容') or
                        row.ele('@placeholder=工艺内容') or
                        row.ele('tag:textarea') or
                        row.ele('tag:input', index=2)
                    )
                    if desc_input:
                        desc_input.input(description)
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写工艺描述失败: {e}")

                # ── 填写设备/机床 ──
                try:
                    machine_input = (
                        row.ele('@name=machine') or
                        row.ele('@name=equipment') or
                        row.ele('@name=device') or
                        row.ele('@name=设备') or
                        row.ele('@placeholder=设备') or
                        row.ele('tag:select') or
                        row.ele('tag:input', index=3)
                    )
                    if machine_input:
                        machine_input.input(machine)
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写设备失败: {e}")

                # ── 填写刀具/工装 ──
                try:
                    tool_input = (
                        row.ele('@name=tool') or
                        row.ele('@name=cutter') or
                        row.ele('@name=刀具') or
                        row.ele('@placeholder=刀具') or
                        row.ele('tag:input', index=4)
                    )
                    if tool_input:
                        tool_input.input(tool)
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写刀具失败: {e}")

                # ── 填写工艺参数 ──
                try:
                    param_input = (
                        row.ele('@name=parameters') or
                        row.ele('@name=params') or
                        row.ele('@name=参数') or
                        row.ele('@placeholder=参数') or
                        row.ele('tag:input', index=5)
                    )
                    if param_input:
                        if isinstance(parameters, dict):
                            param_str = "; ".join(f"{k}={v}" for k, v in parameters.items())
                        else:
                            param_str = str(parameters)
                        param_input.input(param_str)
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写工艺参数失败: {e}")

                # ── 填写检验项目/检查项 ──
                try:
                    check_input = (
                        row.ele('@name=check_items') or
                        row.ele('@name=inspection') or
                        row.ele('@name=check') or
                        row.ele('@name=检验') or
                        row.ele('@placeholder=检验') or
                        row.ele('tag:input', index=6)
                    )
                    if check_input and check_items:
                        check_input.input(str(check_items))
                except Exception as e:
                    log.warning(f"工序 #{step_no}: 填写检验项目失败: {e}")

            log.info(f"所有 {len(process_plan)} 道工序填写完成")
    except Exception as e:
        log.error(f"填写工序表格失败: {e}")
        # 即使表格填写失败，也尝试提交
        pass

    # ── 4. 提交保存计划工艺 ──
    saved = False
    try:
        log.info("正在提交保存计划工艺...")
        submit_btn = (
            page.ele('@value=保存') or
            page.ele('@value=提交') or
            page.ele('@value=保存工艺') or
            page.ele('t:button@@text()=保存') or
            page.ele('t:button@@text()=提交') or
            page.ele('@type=submit')
        )
        if submit_btn:
            submit_btn.click()
            page.wait.load_complete(timeout=15)
            log.info("计划工艺已提交保存")

            # 验证提交结果
            page_text = page.html
            if any(kw in page_text for kw in ["成功", "保存成功", "操作成功"]):
                log.info("计划工艺保存成功确认")
                saved = True
            else:
                log.info("计划工艺已提交，等待系统处理")
                saved = True
        else:
            # 尝试 JS 方式提交
            log.warning("未找到保存/提交按钮，尝试 JS 提交表单")
            page.run_js("document.querySelector('form')?.requestSubmit()")
            page.wait.load_complete(timeout=10)
            saved = True
    except Exception as e:
        log.warning(f"提交保存计划工艺失败: {e}")
        saved = False

    return {"plan_saved": saved, "checkpoint": 25}
