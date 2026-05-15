"""节点: 填写计划工序（CNC 代码） + 飞书通知完成

选择关联的生产单号，在数控精车和镜面放电两道工序填入 CNC 代码。
"""

import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.routing_filler")


def node_fill_routing(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """填入 CNC 代码到计划工序 → 通知完成"""
    ctx = config["configurable"]["ctx"]
    prod_no = state.get("prod_no")
    cnc_code = state.get("cnc_code")

    if not prod_no or not cnc_code:
        log.warning("缺少生产单号或 CNC 代码")
        return {"routing_saved": False, "cnc_saved": False}

    log.info(f"填写计划工序 CNC: prod_no={prod_no}")

    # ── 1. 获取浏览器页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30}

    erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")
    takisawa_code = cnc_code.get("takisawa_nex108", "")
    sodick_params = cnc_code.get("sodick_ad32ls", {})

    # ── 2. 导航到计划工序页面（按生产单号过滤） ──
    try:
        routing_url = f"{erp_url.rstrip('/')}/Plan/ProcessRouting?prod_no={prod_no}"
        log.info(f"正在导航到计划工序页面: {routing_url}")
        page.get(routing_url)
        page.wait.load_complete(timeout=15)
        log.info("计划工序页面加载完成")
    except Exception as e:
        log.warning(f"导航到计划工序页面失败: {e}")
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30}

    # ── 3. 查找并选择关联的生产单号（prod_no） ──
    routing_saved = False
    cnc_saved = False

    try:
        # 查找生产单号输入/选择区域
        prod_no_input = (
            page.ele('@name=prod_no') or
            page.ele('@name=order_no') or
            page.ele('@name=生产单号') or
            page.ele('@placeholder=生产单号')
        )
        if prod_no_input:
            prod_no_input.input(str(prod_no))
            log.info(f"已按生产单号 {prod_no} 查询")
            page.wait.load_complete(timeout=8)
        else:
            log.info("已按生产单号 URL 参数过滤，继续查找工序行")
    except Exception as e:
        log.warning(f"选择生产单号失败: {e}")

    # ── 4. 填入数控精车工序（TAKISAWA CNC 代码） ──
    if takisawa_code:
        try:
            log.info("正在查找数控精车工序行...")
            lathe_row = (
                page.ele('@@text()=数控精车') or
                page.ele('@@text()=精车') or
                page.ele('@@text()=CNC车') or
                page.ele('@@text()=数控车') or
                page.ele('@@text()=TAKISAWA') or
                page.ele('@@text()=NEX108')
            )
            if lathe_row:
                parent = lathe_row.parent()
                log.info("找到数控精车工序行，正在填入 CNC 代码")

                # 尝试多种方式定位代码输入框
                cnc_input = (
                    parent.ele('@name=cnc_code') or
                    parent.ele('@name=lathe_code') or
                    parent.ele('@name=nc_code') or
                    parent.ele('@name=program') or
                    parent.ele('@name*=code') or
                    parent.ele('tag:textarea') or
                    parent.ele('tag:input@@type=text')
                )
                if cnc_input:
                    cnc_input.input(str(takisawa_code))
                    log.info(f"TAKISAWA CNC 代码已填入（{len(str(takisawa_code))} 字符）")
                    cnc_saved = True
                else:
                    log.warning("数控精车工序未找到 CNC 代码输入框")
                    # 降级：在当前行附近查找 textarea
                    try:
                        textareas = parent.eles('tag:textarea')
                        if textareas:
                            textareas[0].input(str(takisawa_code))
                            log.info("通过 textarea 降级填入 CNC 代码成功")
                            cnc_saved = True
                    except Exception:
                        pass
            else:
                log.warning("未找到数控精车工序行，跳过 CNC 代码填入")
        except Exception as e:
            log.warning(f"填入数控精车 CNC 代码失败: {e}")
    else:
        log.info("没有 TAKISAWA CNC 代码数据，跳过数控精车工序")

    # ── 5. 填入镜面放电工序（SODICK EDM 参数） ──
    if sodick_params and isinstance(sodick_params, dict):
        try:
            log.info("正在查找镜面放电工序行...")
            edm_row = (
                page.ele('@@text()=镜面放电') or
                page.ele('@@text()=放电') or
                page.ele('@@text()=EDM') or
                page.ele('@@text()=镜面') or
                page.ele('@@text()=SODICK') or
                page.ele('@@text()=AD32LS')
            )
            if edm_row:
                parent = edm_row.parent()
                log.info(f"找到镜面放电工序行，正在填入 EDM 参数: {sodick_params}")

                # 逐字段填入 EDM 参数
                param_fields_filled = 0
                for param_key, param_value in sodick_params.items():
                    try:
                        param_input = (
                            parent.ele(f'@name={param_key}') or
                            parent.ele(f'@name*={param_key}') or
                            parent.ele(f'@placeholder={param_key}') or
                            parent.ele(f'@id={param_key}')
                        )
                        if param_input:
                            param_input.input(str(param_value))
                            param_fields_filled += 1
                    except Exception:
                        continue

                # 如果没有命名字段，尝试用 textarea 填入完整参数
                if param_fields_filled == 0:
                    try:
                        param_textarea = (
                            parent.ele('tag:textarea') or
                            parent.ele('tag:input@@type=text', index=0)
                        )
                        if param_textarea:
                            param_str = "; ".join(f"{k}={v}" for k, v in sodick_params.items())
                            param_textarea.input(param_str)
                            param_fields_filled = 1
                    except Exception:
                        pass

                log.info(f"镜面放电参数已填入（{param_fields_filled} 个字段）")
                if param_fields_filled > 0:
                    cnc_saved = True
            else:
                log.warning("未找到镜面放电工序行，跳过 EDM 参数填入")
        except Exception as e:
            log.warning(f"填入镜面放电 EDM 参数失败: {e}")
    else:
        log.info("没有 SODICK EDM 参数数据，跳过镜面放电工序")

    # ── 6. 提交保存计划工序 ──
    try:
        log.info("正在提交保存计划工序...")
        submit_btn = (
            page.ele('@value=保存') or
            page.ele('@value=提交') or
            page.ele('@value=保存工序') or
            page.ele('t:button@@text()=保存') or
            page.ele('t:button@@text()=提交') or
            page.ele('@type=submit')
        )
        if submit_btn:
            submit_btn.click()
            page.wait.load_complete(timeout=15)
            log.info("计划工序 CNC 代码已提交保存")
            routing_saved = True
        else:
            # JS 降级提交
            log.warning("未找到保存/提交按钮，尝试 JS 提交")
            page.run_js("document.querySelector('form')?.requestSubmit()")
            page.wait.load_complete(timeout=10)
            routing_saved = True
    except Exception as e:
        log.warning(f"提交保存计划工序失败: {e}")
        routing_saved = False

    log.info(f"计划工序填写完成: routing_saved={routing_saved}, cnc_saved={cnc_saved}")

    # 飞书通知：工作流完成
    notify_on = ctx.tenant_config.get("notify_on", [])
    if ctx.notifier and "workflow_complete" in notify_on:
        try:
            ctx.notifier.notify_workflow_complete(ctx.display_name, prod_no)
        except Exception as e:
            log.warning(f"飞书通知失败: {e}")

    return {"routing_saved": routing_saved, "cnc_saved": cnc_saved, "checkpoint": 30}
