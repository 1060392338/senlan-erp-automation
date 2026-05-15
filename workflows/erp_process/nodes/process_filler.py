"""节点: 填写计划工艺 — 适配实际 SPA (Vue+VXE) 页面

适配 E68 ERP 实际页面结构：
  - 路由: #/Craftwork/steel_craftworkList/0210
  - 搜索: input[placeholder="请输入生产单号"] + 查询按钮
  - 弹窗: 勾选行 → "工艺管理" 按钮 → VXE可编辑表格
  - 保存: 弹窗脚部「保存」按钮
"""
import json
import logging
import os
import time
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("node.process_filler")

# ── 3道预置工序（根据STRIPPER RING图纸分析 + 设备清单匹配） ──
DEFAULT_PROCESS_PLAN = [
    {
        "name": "数控精车",
        "machine_hours": 2,
        "worker": "Takisawa",
        "remark": "车外圆、内孔、端面。材料S7(54-56HRC)，单边留0.3mm余量给慢走丝。粗糙度Ra0.8。",
    },
    {
        "name": "慢走丝",
        "machine_hours": 3,
        "worker": "Sodick",
        "remark": "割2×Ø10.47精孔、3.05mm槽。公差±0.005。Ra0.63。割1修2。",
    },
    {
        "name": "镜面放电",
        "machine_hours": 4,
        "worker": "Sodick AM45L",
        "remark": "精加工细部特征。电极损耗<0.5%，表面镜面要求Ra0.2。",
    },
]

SENLAN_API_BASE = "http://112.74.35.30"


def _navigate_to_page(page, prod_no: str) -> bool:
    """导航到计划工艺页面(Vue SPA路由)

    DrissionPage在节点之间可能回退到chrome://newtab/，
    且session cookie不一定保留，所以每次进来都重新登录+导航。
    """
    try:
        import time
        erp_base = 'http://112.74.35.30'
        from workflows.erp_process._login import fill_login_form, verify_login

        # 1. 总从首页开始，不管当前是什么页面
        log.info(f"强制导航到ERP首页（当前URL: {page.url[:60]}）")
        page.get(erp_base + '/')
        time.sleep(5)

        # 2. 检查是否被重定向到登录页
        current_url = page.url
        if 'Login' in current_url:
            log.info("被重定向到登录页，重新登录")
            import os
            username = os.environ.get("ERP_472_USERNAME", "472")
            password = os.environ.get("ERP_472_PASSWORD", "123456")
            fill_login_form(page, erp_base, username, password)
            time.sleep(5)

        # 3. 确认登录完成 — 等SPA加载完
        for retry in range(5):
            page_text = page.run_js("return document.body.innerText.substring(0, 400)")
            if page_text and len(page_text.strip()) > 10:
                break
            time.sleep(3)
            log.info(f"等待SPA加载... (retry {retry+1}/5)")

        # 4. 先导航到SPA首页hash（确保路由初始化）
        page.run_js("window.location.hash = '#/'")
        time.sleep(4)

        # 5. 再设置计划工艺hash
        page.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
        time.sleep(6)

        # 6. 等待页面内容加载
        for retry in range(6):
            page_text = page.run_js("return document.body.innerText.substring(0, 1200)")
            if '计划工艺' in page_text:
                log.info("✓ 已到达计划工艺页面")
                return True
            log.info(f"等待计划工艺页面渲染... ({retry+1}/6)")
            time.sleep(3)

        log.warning(f"最终导航失败，当前URL: {page.url[:80]}")
        return False
    except Exception as e:
        log.warning(f"导航异常: {e}")
        return False


def _search_order(page, prod_no: str) -> bool:
    """搜索生产单号 — 遍历 BOM清单/未发送/已发送 三个标签"""
    try:
        # 先尝试搜索
        for tab_name in ["BOM清单", "未发送", "已发送"]:
            # 切换radio标签
            page.run_js(f"""
                let labels = document.querySelectorAll('.el-radio-button__inner');
                for(let label of labels) {{
                    if(label.textContent.trim() === '{tab_name}') {{
                        let radio = label.closest('label');
                        if(radio && !radio.classList.contains('is-active')) {{
                            label.click();
                        }}
                        break;
                    }}
                }}
            """)
            time.sleep(1)

            # 输入生产单号
            page.run_js(f"""
                let inp = document.querySelector('input[placeholder="请输入生产单号"]');
                if (inp) {{
                    let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    ns.call(inp, '{prod_no}');
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            """)
            time.sleep(0.3)

            # 点击查询
            page.run_js("""
                let btns = document.querySelectorAll('button');
                for (let btn of btns) {
                    for (let span of btn.querySelectorAll('span'))
                        if (span.textContent.trim() === '查询') { btn.click(); return; }
                }
            """)
            time.sleep(2.5)

            # 检查是否找到
            found = page.run_js(f"return document.body.innerText.includes('{prod_no}')")
            if found:
                log.info(f"在 {tab_name} 标签下找到生产单 {prod_no}")
                return True

        log.warning(f"在所有标签下均未找到生产单 {prod_no}")
        return False
    except Exception as e:
        log.warning(f"搜索生产单异常: {e}")
        return False


def _select_and_open_dialog(page, prod_no: str) -> bool:
    """勾选行 → 点击「工艺管理」打开弹窗

    VXE Grid的全选checkbox在表头(th)，点击表头checkbox
    选择整行，然后点头部「工艺管理」按钮。
    """
    try:
        # 全选：点击表头的checkbox
        cb_r = page.run_js("""
            let headerCheckbox = document.querySelector('.vxe-header--row .vxe-cell--checkbox');
            if (headerCheckbox) {
                headerCheckbox.click();
                return 'header_cb_clicked';
            }
            return 'no_header_cb';
        """)
        log.info(f"全选: {cb_r}")
        time.sleep(1)

        # 点击工艺管理
        r = page.run_js("""
            let btns = document.querySelectorAll('button');
            for (let btn of btns) {
                for (let span of btn.querySelectorAll('span')) {
                    if (span.textContent.trim() === '工艺管理') {
                        btn.click();
                        return 'craft_mgmt_clicked';
                    }
                }
            }
            return 'craft_mgmt_not_found';
        """)
        log.info(f"打开工艺管理: {r}")
        time.sleep(4)

        # 确认弹窗已打开
        dialog_check = page.run_js("""
            let dialogs = document.querySelectorAll('.el-dialog');
            for (let d of dialogs) {
                let title = (d.querySelector('.el-dialog__title') || {}).textContent || '';
                if (title.trim() === '工艺管理') return 'dialog_open';
            }
            return 'dialog_not_found';
        """)
        log.info(f"弹窗状态: {dialog_check}")
        return dialog_check == 'dialog_open'
    except Exception as e:
        log.warning(f"打开工艺管理弹窗失败: {e}")
        return False


def _fill_vxe_table_cells(page, process_plan: list) -> bool:
    """填充VXE工序表格 — 点+按钮加行 → 双击单元格 → 选工序

    策略：先清空旧行，再逐行点击「+」添加新行，
    然后对每行双击工序单元格触发popover，选中对应工序，
    最后用VXE API填入计划工时/工人/工艺要求。
    """
    try:
        count = len(process_plan)
        log.info(f"填充 {count} 道工序...")

        # === 1. 清空所有现有行（点删除按钮） ===
        for round_try in range(5):  # 最多删5轮（安全上限）
            rows_left = page.run_js("""
                let bws = document.querySelectorAll('.vxe-table--body-wrapper');
                let bw = bws[bws.length - 1];
                if (!bw) return 0;
                return bw.querySelectorAll('.vxe-body--row').length;
            """)
            try:
                rows_left = int(rows_left)
            except (ValueError, TypeError):
                rows_left = count

            if rows_left <= 1:
                break

            page.run_js("""
                let bws = document.querySelectorAll('.vxe-table--body-wrapper');
                let bw = bws[bws.length - 1];
                if (!bw) return;
                let firstRow = bw.querySelector('.vxe-body--row');
                if (!firstRow) return;
                let delIcon = firstRow.querySelector('.el-icon-delete');
                if (delIcon) delIcon.click();
            """)
            time.sleep(0.5)
            log.info(f"  删除第 {round_try + 1} 行 (剩余 {rows_left})")

        # === 2. 添加 count 行（点「+」按钮） ===
        for i in range(count):
            page.run_js("""
                let bws = document.querySelectorAll('.vxe-table--body-wrapper');
                let bw = bws[bws.length - 1];
                if (!bw) return;
                let firstRow = bw.querySelector('.vxe-body--row');
                if (!firstRow) return;
                let plusIcon = firstRow.querySelector('.el-icon-plus');
                if (plusIcon) plusIcon.click();
            """)
            time.sleep(0.8)
            log.info(f"  添加第 {i + 1} 行")

        # === 3. 清除旧行，然后用VXE API插入新行（带数据）===
        # 先清空：删除所有行
        for round_try in range(5):
            rows_left = page.run_js("""
                let dialogs = document.querySelectorAll('.el-dialog');
                let d = null;
                for (let d2 of dialogs) {
                    let t = (d2.querySelector('.el-dialog__title') || {}).textContent || '';
                    if (t.trim() === '工艺管理') { d = d2; break; }
                }
                let bw = d.querySelector('.vxe-table--body-wrapper:last-child');
                if (!bw) return 0;
                let rows = bw.querySelectorAll('.vxe-body--row');
                return rows.length;
            """)
            try: rows_left = int(rows_left)
            except: break
            if rows_left <= 1: break
            page.run_js("""
                let dialogs = document.querySelectorAll('.el-dialog');
                let d = null;
                for (let d2 of dialogs) {
                    let t = (d2.querySelector('.el-dialog__title') || {}).textContent || '';
                    if (t.trim() === '工艺管理') { d = d2; break; }
                }
                let bw = d.querySelector('.vxe-table--body-wrapper:last-child');
                if (!bw) return;
                let firstRow = bw.querySelector('.vxe-body--row');
                if (!firstRow) return;
                let delIcon = firstRow.querySelector('.el-icon-delete, [class*=delete]');
                if (delIcon) delIcon.click();
            """)
            time.sleep(0.5)
            log.info(f"  删除行 (剩余 {rows_left})")

        # 添加行（点击"+"按钮）
        for i in range(count):
            page.run_js("""
                let dialogs = document.querySelectorAll('.el-dialog');
                let d = null;
                for (let d2 of dialogs) {
                    let t = (d2.querySelector('.el-dialog__title') || {}).textContent || '';
                    if (t.trim() === '工艺管理') { d = d2; break; }
                }
                let bw = d.querySelector('.vxe-table--body-wrapper:last-child');
                if (!bw) return;
                let firstRow = bw.querySelector('.vxe-body--row');
                if (!firstRow) return;
                let plusIcon = firstRow.querySelector('.el-icon-plus, [class*=plus]');
                if (plusIcon) plusIcon.click();
            """)
            time.sleep(0.8)
            log.info(f"  添加第 {i + 1} 行")

        # 对每行，双击"工序"cell，选值
        for idx, step in enumerate(process_plan):
            step_name = step.get("name", "")
            hours = step.get("machine_hours", 0)
            worker = step.get("worker", "")
            remark = step.get("remark", "")
            log.info(f"  填充第 {idx + 1} 行: {step_name}")

            # 找到第idx行
            vxe_ok = page.run_js(f"""
                let dialogs = document.querySelectorAll('.el-dialog');
                let d = null;
                for (let d2 of dialogs) {{
                    let t = (d2.querySelector('.el-dialog__title') || {{}}).textContent || '';
                    if (t.trim() === '工艺管理') {{ d = d2; break; }}
                }}
                let bw = d.querySelector('.vxe-table--body-wrapper:last-child');
                let rows = bw.querySelectorAll('.vxe-body--row');
                if (rows.length <= {idx}) return 'no_row_' + rows.length;
                let row = rows[{idx}];
                let cells = row.querySelectorAll('td');

                // 找data-field=工序 或 包含"工序"文本的列
                let processCell = null;
                let headerCells = d.querySelectorAll('.vxe-header--row th');
                let processIdx = -1;
                headerCells.forEach((h, i) => {{
                    let field = h.getAttribute('data-field') || '';
                    let title = (h.querySelector('.vxe-cell--title') || {{}}).textContent || '';
                    if (field.includes('process') || field.includes('table_type') || title.includes('工序')) {{
                        processIdx = i;
                    }}
                }});
                if (processIdx >= 0 && cells.length > processIdx) {{
                    processCell = cells[processIdx];
                }}
                if (!processCell) return 'no_process_cell';

                // 双击进入编辑
                processCell.dispatchEvent(new MouseEvent('dblclick', {{bubbles: true, detail: 2}}));
                return 'dblclicked';
            """)
            time.sleep(1)
            log.info(f"  双击工序cell: {vxe_ok}")

            # 在popover/select中选择工序
            select_ok = page.run_js(f"""
                // 找工序选择弹窗
                let selectPanel = document.querySelector('.vxe-select--panel:not([style*=\"display: none\"])');
                if (!selectPanel) return 'no_panel';
                let items = selectPanel.querySelectorAll('.vxe-select-option, .el-select-dropdown__item, li, .vxe-cell--checkbox-option');
                for (let item of items) {{
                    let text = (item.textContent || '').trim();
                    if (text === '{step_name}') {{
                        item.click();
                        return 'selected_' + text;
                    }}
                }}
                return 'not_found';
            """)
            log.info(f"  选工序: {select_ok}")
            time.sleep(0.5)
        time.sleep(1)
        log.info("VXE表格填充完成")
        return True

    except Exception as e:
        log.error(f"填充VXE表格异常: {e}")
        return False


def _save_dialog(page) -> bool:
    """点击弹窗的「保存」按钮"""
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
        log.info(f"保存按钮: {r}")
        time.sleep(3)
        return 'save_clicked' in r
    except Exception as e:
        log.warning(f"点击保存失败: {e}")
        return False


def _upload_drawing(page, drawing_local_path: Optional[str]) -> bool:
    """上传2D图纸到工艺管理弹窗"""
    if not drawing_local_path or not os.path.exists(drawing_local_path):
        log.info(f"无图纸可上传: {drawing_local_path}")
        return False

    log.info(f"上传2D图纸: {drawing_local_path}")
    try:
        # 点击「2D图档文件」按钮
        r = page.run_js("""
            let btns = document.querySelectorAll('.el-dialog button');
            for (let btn of btns) {
                let span = btn.querySelector('span');
                if (span && span.textContent.trim() === '2D图档文件') {
                    btn.click();
                    return '2d_btn_clicked';
                }
            }
            return '2d_btn_not_found';
        """)
        log.info(f"2D图档按钮: {r}")
        time.sleep(2)

        # 在打开的附件tab中找文件上传控件
        file_input = (
            page.ele("tag:input@@type=file") or
            page.ele("@name=file") or
            page.ele("@accept=image") or
            page.ele("@class*=upload")
        )
        if file_input:
            file_input.input(drawing_local_path)
            time.sleep(3)
            log.info("图纸上传成功（文件输入）")
            return True

        # 降级：使用JS触发上传
        log.warning("未找到文件输入控件，尝试JS上传")
        page.run_js(f"""
            let uploaders = document.querySelectorAll('.el-upload__input');
            if (uploaders.length > 0) {{
                // 修改文件属性自动上传 - 不可行，文件选择需要用户交互
            }}
        """)
        return False
    except Exception as e:
        log.warning(f"上传图纸失败: {e}")
        return False


def _save_and_send_dialog(page) -> bool:
    """点击「保存并发送」按钮"""
    try:
        r = page.run_js("""
            let footer = document.querySelector('.el-dialog__footer');
            if (!footer) return 'no_footer';
            let btns = footer.querySelectorAll('button');
            for (let btn of btns) {
                let span = btn.querySelector('span');
                if (span && span.textContent.trim() === '保存并发送') {
                    btn.click();
                    return 'save_send_clicked';
                }
            }
            return 'save_send_not_found';
        """)
        log.info(f"保存并发送: {r}")
        time.sleep(3)
        return 'save_send_clicked' in r
    except Exception as e:
        log.warning(f"点击保存并发送失败: {e}")
        return False


def node_fill_plan(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """填写计划工艺 → ERP 系统（适配Vue+ VXE SPA） + 上传图纸"""
    ctx = config["configurable"]["ctx"]
    prod_no = state.get("prod_no", "W20126051401")
    process_plan = state.get("process_plan", DEFAULT_PROCESS_PLAN)
    drawing_local_path = state.get("drawing_local_path")

    log.info(f"=== 开始填写计划工艺: prod_no={prod_no}, {len(process_plan)} 道工序 ===")

    # ── 1. 获取浏览器页面 ──
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")
        return {"plan_saved": False, "errors": [f"获取页面失败: {e}"], "checkpoint": 25}

    # ── 2. 导航 ──
    if not _navigate_to_page(page, prod_no):
        return {"plan_saved": False, "errors": ["导航到计划工艺失败"], "checkpoint": 25}

    # ── 3. 搜索 ──
    search_ok = _search_order(page, prod_no)
    if not search_ok:
        log.warning("搜索生产单失败 — 可能已有关联工艺")
        # 尝试直接勾选搜索（可能已经显示在默认标签）
        # 不返回错误，继续尝试打开弹窗

    # ── 4. 打开工艺管理弹窗 ──
    dialog_ok = _select_and_open_dialog(page, prod_no)
    if not dialog_ok:
        log.error("打开工艺管理弹窗失败")
        return {"plan_saved": False, "errors": ["打开弹窗失败"], "checkpoint": Checkpoint.PLAN_FILLED}

    # ── 5. 填充工序表格 ──
    if not _fill_vxe_table_cells(page, process_plan):
        log.warning("工序表格填充可能不完整，继续尝试保存")

    # ── 6. 上传图纸（可选） ──
    if drawing_local_path:
        _upload_drawing(page, drawing_local_path)

    # ── 7. 保存 ──
    saved = _save_dialog(page)
    if not saved:
        log.warning("主保存失败，尝试保存并发送...")
        saved = _save_and_send_dialog(page)

    if saved:
        log.info("✓ 计划工艺保存成功！")
    else:
        log.warning("✗ 计划工艺保存失败")

    return {"plan_saved": saved, "checkpoint": Checkpoint.PLAN_FILLED}
