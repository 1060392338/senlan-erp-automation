"""节点: 填写 CNC 代码到计划工序 — 适配实际 SPA 页面

流程：
  1. 导航到计划工艺 → 搜索生产单号 → 打开工艺管理弹窗
  2. 在 VXE 表格中找到 数控精车 和 镜面放电 行
  3. 通过 VXE API 或细胞交互填入 CNC 代码到 工艺要求 字段
  4. 保存并发送
"""
import logging
import time
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("node.routing_filler")

# ── 辅助函数 ──

def _navigate(page):
    """导航到计划工艺页面（复用 process_filler 的健壮逻辑）"""
    try:
        from workflows.erp_process.nodes.process_filler import _navigate_to_page
        return _navigate_to_page(page, "")
    except Exception as e:
        log.warning(f"导航异常: {e}")
        return False


def _search_order(page, prod_no: str):
    """搜索生产单号（复用 process_filler 的 BOM清单遍历逻辑）"""
    try:
        from workflows.erp_process.nodes.process_filler import _search_order as _robust_search
        return _robust_search(page, prod_no)
    except Exception as e:
        log.warning(f"搜索异常: {e}")
        return False


def _open_dialog(page, prod_no: str):
    """勾选行 → 打开工艺管理弹窗（复用 process_filler 的头checkbox逻辑）"""
    try:
        from workflows.erp_process.nodes.process_filler import _select_and_open_dialog
        return _select_and_open_dialog(page, prod_no)
    except Exception as e:
        log.warning(f"打开弹窗异常: {e}")
        return False


def _set_cnc_cell_value(page, row_idx: int, field: str, value: str):
    """通过 VXE DOM 交互设置单元格值（不依赖 __vue__ 数据模型）"""
    escaped = value.replace('`', '\\`').replace('${', '\\${').replace('\\', '\\\\')
    truncated = escaped[:2000]

    result = page.run_js(f"""
        // 在弹窗内找 VXE 表格
        let dialog = document.querySelector('.el-dialog');
        if (!dialog) return 'no_dialog';
        let gridEl = dialog.querySelector('.vxe-grid');
        if (!gridEl) return 'no_grid';

        // 方法1: 尝试 __vue__ API
        if (gridEl.__vue__) {{
            let vm = gridEl.__vue__;
            if (typeof vm.setCellValue === 'function') {{
                let rows = vm.fullData || vm.tableData || [];
                if (rows.length > {row_idx}) {{
                    vm.setCellValue(rows[{row_idx}], '{field}', `{truncated}`);
                    return 'vue_api_ok';
                }}
            }}
            if (Array.isArray(vm.fullData) && vm.fullData.length > {row_idx}) {{
                vm.fullData[{row_idx}]['{field}'] = `{truncated}`;
                return 'vue_direct_ok';
            }}
        }}

        // 方法2: 找到第 {row_idx} 行的第 {field} 列，双击编辑
        let bodyTable = dialog.querySelector('.vxe-table--body-wrapper table');
        if (!bodyTable) return 'no_body_table';
        let bodyRows = bodyTable.querySelectorAll('.vxe-body--row');
        if (bodyRows.length <= {row_idx}) return 'row_overflow_' + bodyRows.length;
        
        let targetRow = bodyRows[{row_idx}];
        // 找 field 对应的列
        let headerTable = dialog.querySelector('.vxe-table--header-wrapper table');
        let fieldIdx = -1;
        if (headerTable) {{
            let headerCells = headerTable.querySelectorAll('th');
            headerCells.forEach((th, i) => {{
                let attr = th.getAttribute('data-field');
                if (attr === '{field}') fieldIdx = i;
            }});
        }}
        if (fieldIdx < 0) return 'field_not_found';
        
        let tds = targetRow.querySelectorAll('td');
        if (tds.length <= fieldIdx) return 'td_overflow';
        let targetCell = tds[fieldIdx];
        
        // 双击进入编辑模式
        targetCell.dispatchEvent(new MouseEvent('dblclick', {{bubbles: true, detail: 2}}));
        return 'dblclick_ok';
    """)
    return result


def _save_dialog(page):
    """点击保存"""
    try:
        r = page.run_js("""
            let footer = document.querySelector('.el-dialog__footer');
            if (!footer) return 'no_footer';
            let btns = footer.querySelectorAll('button');
            for (let btn of btns) {
                let span = btn.querySelector('span');
                if (span && span.textContent.trim() === '保存' && btn.classList.contains('el-button--primary')) {
                    btn.click();
                    return 'save_clicked';
                }
            }
            return 'save_not_found';
        """)
        time.sleep(3)
        return 'save_clicked' in r
    except Exception:
        return False


# ── 主节点 ──

def node_fill_routing(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """填入 CNC 代码到计划工序 → 通知完成"""
    ctx = config["configurable"]["ctx"]
    prod_no = state.get("prod_no", "W20126051401")
    cnc_code = state.get("cnc_code", {})

    if not prod_no:
        log.warning("缺少生产单号")
        return {"routing_saved": False, "cnc_saved": False}

    log.info(f"=== 填写 CNC 代码到计划工序: prod_no={prod_no} ===")

    # ── 1. 获取页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取页面失败: {e}")
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30}

    # ── 2. 导航到计划工艺页面 ──
    if not _navigate(page):
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30,
                "errors": ["导航失败"]}

    # ── 3. 搜索生产单 ──
    if not _search_order(page, prod_no):
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30,
                "errors": ["搜索失败"]}

    # ── 4. 打开工艺管理弹窗 ──
    if not _open_dialog(page, prod_no):
        return {"routing_saved": False, "cnc_saved": False, "checkpoint": 30,
                "errors": ["打开弹窗失败"]}

    # ── 5. 获取表格行索引 ──
    rows_info = page.run_js("""
        let gridEl = document.querySelector('.vxe-grid');
        if (!gridEl || !gridEl.__vue__) return 'no_vue';
        let vm = gridEl.__vue__;
        let rows = vm.fullData || vm.tableData || [];
        let info = [];
        rows.forEach((r, i) => {
            info.push({idx: i, table_type: r.table_type || ''});
        });
        return JSON.stringify(info);
    """)
    log.info(f"表格行: {rows_info[:300]}")

    # ── 6. 填入 CNC 代码 ──
    saved = False
    rnc_saved = False
    edm_saved = False

    takisawa_code = (cnc_code.get("takisawa_nex108") or
                     cnc_code.get("takisawa") or "")
    sodick_code = (cnc_code.get("sodick_ad32ls") or
                   cnc_code.get("sodick") or "")

    # 获取每行的工序名称列表
    try:
        import json as _json
        rows_list = _json.loads(rows_info) if isinstance(rows_info, str) and rows_info.startswith('[') else []
    except Exception:
        rows_list = []

    lathe_idx = None
    edm_idx = None
    for r in rows_list:
        name = (r.get("table_type") or "").strip()
        if "数控精车" in name:
            lathe_idx = r["idx"]
        elif "镜面放电" in name:
            edm_idx = r["idx"]

    # 填入数控精车 CNC 代码
    if lathe_idx is not None and takisawa_code:
        code_summary = takisawa_code[:500]  # 只取关键信息
        log.info(f"填入数控精车 CNC 代码 (行 {lathe_idx})")
        r1 = _set_cnc_cell_value(page, lathe_idx, "remark",
                                  f"[CNC代码 - TAKISAWA NEX108]\n{code_summary}")
        log.info(f"  数控精车: {r1}")
        rnc_saved = 'ok' in r1 or 'direct_ok' in r1
    else:
        log.info(f"跳过数控精车: lathe_idx={lathe_idx}, code_len={len(takisawa_code)}")

    # 填入镜面放电 CNC 代码
    if edm_idx is not None and sodick_code:
        code_summary = sodick_code[:500]
        log.info(f"填入镜面放电 CNC 代码 (行 {edm_idx})")
        r2 = _set_cnc_cell_value(page, edm_idx, "remark",
                                  f"[CNC代码 - Sodick AD32LS]\n{code_summary}")
        log.info(f"  镜面放电: {r2}")
        edm_saved = 'ok' in r2 or 'direct_ok' in r2
    else:
        log.info(f"跳过镜面放电: edm_idx={edm_idx}, code_len={len(sodick_code)}")

    # ── 7. 提交编辑 + 保存 ──
    page.run_js("""
        let gridEl = document.querySelector('.vxe-grid');
        if (gridEl && gridEl.__vue__) {
            let vm = gridEl.__vue__;
            if (typeof vm.commitEdit === 'function') vm.commitEdit();
        }
    """)
    time.sleep(1)

    saved = _save_dialog(page)

    # ── 8. 飞书通知 ──
    try:
        from services.feishu_notifier import FeishuNotifier
        notifier = FeishuNotifier()
        feishu_webhook = ctx.erp_config.get("feishu_webhook", "")
        part_name = state.get("part_info", {}).get("name", "STRIPPER RING")

        summary_lines = [
            f"✅ 森蓝ERP · 计划工艺填写完成",
            f"━━━━━━━━━━━━━━━━",
            f"📦 生产单号: {prod_no}",
            f"🔩 零件名称: {part_name}",
            f"📋 工序: 数控精车 {'✓' if lathe_idx is not None else '✗'} / "
            f"镜面放电 {'✓' if edm_idx is not None else '✗'}",
            f"💾 保存: {'成功' if saved else '失败'}",
        ]
        if feishu_webhook:
            notifier.send_text(feishu_webhook, "\n".join(summary_lines))
            log.info("飞书通知已发送")
    except Exception as e:
        log.warning(f"飞书通知失败: {e}")

    log.info(f"CNC代码填写完成: rnc={rnc_saved}, edm={edm_saved}, save={saved}")
    return {"routing_saved": saved, "cnc_saved": rnc_saved or edm_saved, "checkpoint": 30}
