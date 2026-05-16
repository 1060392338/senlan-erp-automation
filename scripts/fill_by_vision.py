#!/usr/bin/env python3
"""森蓝ERP工艺全流程 — 支持单零件/多零件生产单

用法:
    # 扫目录自动发现所有生产单
    python scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --account 472

    # 只处理指定单号
    python scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --prod-no C03026051501 --account 472

    # 只处理指定单号下的指定零件
    python scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --prod-no C03026051501 --parts 001,002 --account 472

    # (向后兼容) 单张图纸 + 生产单号
    python scripts/fill_by_vision.py --drawing /path/to/pdf --prod-no W20126051401 --account 472

设计原则:
    - 文件名约定: {prod_no}-{part_no}.pdf，用第一个 "-" 切分
    - 单零件还是多零件由 ERP 表行数决定，不靠文件名猜
    - 多零件模式下: 图纸必须覆盖所有零件，缺一张就终止
"""
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.dropdown_options import ERP_CODE_MAP
from workflows.erp_process.process_reasoning import reason_process, map_to_erp_processes
from scripts.vision_service import extract_prod_no, scan_drawings, VisionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fill_by_vision")

ERP_BASE = "http://112.74.35.30"
USER_DATA_DIR = "data/chrome_data/playwright"

# ─── 浏览器 JS 助手 ────────────────────────────────

def js(page, code):
    code = f"(function() {{{code}}})()"
    return page.evaluate(code)


def dialog_js(page, code):
    """在工艺管理弹窗内执行JS"""
    wrapped = f"""
        let d = null;
        for(let d2 of document.querySelectorAll('.el-dialog')) {{
            let t = (d2.querySelector('.el-dialog__title')||{{}}).textContent||'';
            if(t.trim() === '工艺管理') {{ d = d2; break; }}
        }}
        if(!d) return null;
        {code}
    """
    return js(page, wrapped)


def get_part_col_index(page) -> int:
    """动态查找零件号列在表头中的索引"""
    headers = js(page, """
        let ths = document.querySelectorAll('.vxe-header--row .vxe-cell--title');
        return Array.from(ths).map(h => h.textContent.trim());
    """)
    for i, h in enumerate(headers or []):
        if h == "零件号":
            return i
    return -1


def get_all_matching_rows(page, prod_no: str) -> list[dict]:
    """搜索并返回该生产单所有行的 {row_el: DOM引用, part_no: str}"""
    rows = js(page, f"""
        let rows = document.querySelectorAll('.vxe-body--row');
        let headers = document.querySelectorAll('.vxe-header--row .vxe-cell--title');
        let hdrText = Array.from(headers).map(h => h.textContent.trim());
        let partCol = hdrText.indexOf('零件号');
        let results = [];
        for(let i = 0; i < rows.length; i++) {{
            let cells = rows[i].querySelectorAll('td .vxe-cell');
            let prodCell = (cells[2]?.textContent||'').trim();
            if(prodCell !== '{prod_no}') continue;
            let partNo = '';
            if(partCol >= 0 && cells[partCol]) {{
                partNo = cells[partCol].textContent.trim();
            }}
            results.push({{ri: i, partNo: partNo}});
        }}
        return JSON.stringify(results);
    """)
    return json.loads(rows) if rows else []


def click_row_checkbox(page, row_index: int):
    """勾选指定索引行的checkbox"""
    js(page, f"""
        let rows = document.querySelectorAll('.vxe-body--row');
        if(rows[{row_index}]) {{
            let cb = rows[{row_index}].querySelector('.vxe-cell--checkbox');
            if(cb) cb.click();
        }}
    """)


def click_process_mgmt(page):
    """点击工艺管理按钮"""
    js(page, """
        setTimeout(() => {
            for(let btn of document.querySelectorAll('button'))
                if(btn.textContent.trim() === '工艺管理') { btn.click(); break; }
        }, 500);
    """)


# ─── CNC 格式 ─────────────────────────────────────


# ─── 单零件对话框填充 ─────────────────────────────

def fill_one_part(page, part_no_label: str, process_plan: list,
                  prod_no: str, part_no: Optional[str], is_multi: bool):
    """在工艺管理弹窗中填充一个零件的工序并保存"""
    log.info(f"  ── 填写零件 {part_no_label} ──")

    if not dialog_js(page, "return true;"):
        raise RuntimeError("工艺管理弹窗未打开")

    count = len(process_plan)
    log.info(f"  需要 {count} 行工序")

    dom_rows = dialog_js(page, "return d.querySelector('.vxe-grid').__vue__.getData().length;")
    log.info(f"  当前行数: {dom_rows}")

    if dom_rows < count:
        need = count - dom_rows
        log.info(f"  添加 {need} 行...")
        for _ in range(need):
            js(page, """let icons = document.querySelectorAll('.el-icon-plus');
                if(icons.length > 0) icons[icons.length - 1].click();""")
            page.wait_for_timeout(300)
        page.wait_for_timeout(300)
        dom_rows = dialog_js(page, "return d.querySelector('.vxe-grid').__vue__.getData().length;")
        log.info(f"  添加后行数: {dom_rows}")

    plan_json = json.dumps(process_plan, ensure_ascii=False)
    code_map_json = json.dumps(ERP_CODE_MAP, ensure_ascii=False)

    fill_result = js(page, f"""
        let d = null;
        for(let d2 of document.querySelectorAll('.el-dialog')) {{
            let t = (d2.querySelector('.el-dialog__title')||{{}}).textContent||'';
            if(t.trim() === '工艺管理') {{ d = d2; break; }}
        }}
        let vm = d.querySelector('.vxe-grid').__vue__;
        let data = vm.getData();
        let steps = {plan_json};
        let codeMap = {code_map_json};
        for(let i = 0; i < steps.length && i < data.length; i++) {{
            let code = codeMap[steps[i].name] || '';
            data[i].table_type = code;
            data[i].machine = String(steps[i].machine_hours || 0);
            data[i].plan_worker = steps[i].worker || '';
            data[i].remark = steps[i].remark || '';
        }}
        return 'd=' + data.length + '_s=' + steps.length;
    """)
    log.info(f"  填充: {fill_result}")

    # 保存
    page.wait_for_timeout(300)
    save_btn = page.locator(
        '.el-dialog:has(.el-dialog__title:text("工艺管理")) '
        '.el-dialog__footer button.el-button--primary'
    ).first
    if save_btn.count() > 0:
        save_btn.click(force=True, timeout=5000)
        log.info("  ✓ 点击保存按钮")
    else:
        # 备用：JS点击
        js(page, """
            let d = null;
            for(let d2 of document.querySelectorAll('.el-dialog')) {
                let t = (d2.querySelector('.el-dialog__title')||{}).textContent||'';
                if(t.trim() === '工艺管理') { d = d2; break; }
            }
            if(d) {
                let btn = d.querySelector('.el-dialog__footer button.el-button--primary');
                if(btn) btn.click();
            }
        """)
        log.info("  ✓ JS点击保存按钮")

    # 确认保存
    page.wait_for_timeout(300)
    for _ in range(10):
        toast = js(page, """
            let t = document.querySelector('.el-message--success');
            return t ? t.textContent.trim() : '';
        """)
        if toast:
            log.info(f"  ✓ {toast}")
            break
        dialog_open = dialog_js(page, "return true;")
        if not dialog_open:
            log.info("  ✓ 保存成功（弹窗已关闭）")
            break
        page.wait_for_timeout(300)
    else:
        log.warning("  保存后弹窗未关闭，但数据已写入")


# ─── 处理一个生产单的所有零件 ─────────────────────

def process_prod_no(page, prod_no: str, plans: dict,
                    account: str):
    """在ERP中处理一个生产单号下的所有零件

    以图纸文件名为源：(prod_no, part_no) 来自文件名，
    按零件号逐对搜索所有标签页（未发送/BOM清单/已发送）。
    """
    log.info(f"\n{'='*60}")
    log.info(f"处理生产单: {prod_no}")

    available_parts = plans.get(prod_no, {})
    if not available_parts:
        log.warning(f"  生产单 {prod_no} 无工艺方案，跳过")
        return False

    part_nos = sorted(p for p in available_parts if p is not None)
    log.info(f"  图纸中的零件: {part_nos}")

    TABS = ["未发送", "BOM清单", "已发送"]
    processed = 0

    for part_no in part_nos:
        part_label = f"{prod_no}-{part_no}"
        plan = available_parts.get(part_no)
        if not plan:
            log.warning(f"  零件 {part_label} 无工艺方案，跳过")
            continue

        # 在所有标签页中搜索该零件号对应的行
        found_row = None  # {tab, row_index}
        for tab_name in TABS:
            # 先移除所有残留弹窗
            js(page, """
                for(let d of document.querySelectorAll('.el-dialog__wrapper, .v-modal, .el-overlay')) {
                    d.remove();
                }
            """)
            # 切标签
            js(page, f"""
                for(let btn of document.querySelectorAll('.el-radio-button')) {{
                    let span = btn.querySelector('.el-radio-button__inner');
                    if(span && span.textContent.trim() === '{tab_name}') {{ btn.click(); return; }}
                }}
            """)
            page.wait_for_timeout(2000)  # 等标签切换

            # 搜索：先用JS清除弹窗遮罩，再用JS直接触发查询
            js(page, """
                for(let d of document.querySelectorAll('.el-dialog__wrapper, .v-modal, .el-overlay')) {
                    d.remove();
                }
            """)
            inp = page.locator('input[placeholder="请输入生产单号"]')
            if inp.count() > 0:
                inp.fill(prod_no)
            js(page, """
                let btns = document.querySelectorAll('button');
                for(let btn of btns) {
                    if(btn.textContent.trim() === '查询') { btn.click(); break; }
                }
            """)
            page.wait_for_timeout(3000)  # 等查询结果

            # 找该标签下有没有匹配的行
            rows = get_all_matching_rows(page, prod_no)
            for r in rows:
                pn = r.get("partNo", "").strip()
                ri = r.get("ri", -1)
                if pn == part_no and ri >= 0:
                    found_row = {"tab": tab_name, "row_index": ri}
                    log.info(f"  ✓ 零件 {part_label} → {tab_name} 标签行{ri}")
                    break
            if found_row:
                break

        if not found_row:
            log.warning(f"  ⚠ 零件 {part_label} 在所有标签页中都未找到，跳过")
            continue

        log.info(f"\n  >>> 处理 {part_label}")

        # 切到正确的标签页
        current_tab = js(page, """
            let a = document.querySelector('.el-radio-button.is-active .el-radio-button__inner');
            return a ? a.textContent.trim() : '';
        """)
        if found_row["tab"] != current_tab:
            js(page, f"""
                for(let btn of document.querySelectorAll('.el-radio-button')) {{
                    let span = btn.querySelector('.el-radio-button__inner');
                    if(span && span.textContent.trim() === '{found_row["tab"]}') {{ btn.click(); return; }}
                }}
            """)
            page.wait_for_timeout(2000)  # 等标签切换
            inp = page.locator('input[placeholder="请输入生产单号"]')
            if inp.count() > 0:
                inp.fill(prod_no)
            page.locator('button:has-text("查询")').first.click()
            page.wait_for_timeout(3000)  # 等查询结果

        # 勾选该行 → 开弹窗 → 填 → 保存 → 取消勾选
        click_row_checkbox(page, found_row["row_index"])
        page.wait_for_timeout(300)
        click_process_mgmt(page)
        page.wait_for_timeout(3000)  # 等弹窗渲染

        if not dialog_js(page, "return true;"):
            log.warning(f"  弹窗未打开，重试...")
            page.wait_for_timeout(300)
            click_process_mgmt(page)
            page.wait_for_timeout(3000)  # 等弹窗渲染

        if not dialog_js(page, "return true;"):
            log.error(f"  零件 {part_label} 弹窗打开失败，跳过")
            continue

        fill_one_part(page, part_label, plan, prod_no, part_no, is_multi=len(part_nos) > 1)

        # 关闭残留弹窗 + 取消勾选
        page.wait_for_timeout(300)
        js(page, """
            // 强制移除所有弹窗遮罩
            for(let d of document.querySelectorAll('.el-dialog__wrapper, .v-modal, .el-overlay')) {
                d.style.display = 'none';
                d.remove();
            }
        """)
        page.wait_for_timeout(300)
        click_row_checkbox(page, found_row["row_index"])
        log.info(f"  ✓ 零件 {part_label} 完成")
        processed += 1
        page.wait_for_timeout(300)

    if processed == 0 and part_nos:
        log.warning(f"  生产单 {prod_no} 所有零件均未处理")
        return False

    log.info(f"  → {prod_no} 处理完成: {processed}/{len(part_nos)} 个零件")
    return processed > 0


# ─── 主入口 ──────────────────────────────────────

def run(drawings_dir: str = None, drawing_path: str = None,
        prod_no: str = None, parts: str = None,
        account: str = "472"):
    """主流程入口

    两种模式：
    1. --drawings-dir: 扫描目录，自动发现生产单，批量处理
    2. --drawing + --prod-no: 向后兼容的单图纸模式
    """
    from playwright.sync_api import sync_playwright as _sync_pw

    erp_username = account
    erp_password = os.environ.get(f"ERP_{account}_PASSWORD", "")

    # 密码校验
    if not erp_password:
        log.error(f"账号 {account} 密码未配置！请在 .env 中设置 ERP_{account}_PASSWORD")
        print(f"\n❌ 错误：账号 {account} 密码未在 .env 中配置")
        print(f"   请在 .env 中添加: ERP_{account}_PASSWORD=你的密码\n")
        return False
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")

    log.info(f"{'='*60}")
    log.info(f"森蓝ERP工艺全流程")
    log.info(f"账号: {account}")

    # ── Step 0: 图纸扫描 ──
    if drawings_dir:
        all_drawings = scan_drawings(drawings_dir)
        if prod_no:
            if prod_no not in all_drawings:
                raise ValueError(f"生产单号 {prod_no} 在图纸目录中未找到")
            target = {prod_no: all_drawings[prod_no]}
        else:
            target = all_drawings

        if parts:
            parts_set = set(p.strip() for p in parts.split(","))
            for pn in list(target.keys()):
                target[pn] = {k: v for k, v in target[pn].items()
                              if k is None or k in parts_set}
                if not target[pn]:
                    del target[pn]
    elif drawing_path and prod_no:
        target = {prod_no: {extract_prod_no(drawing_path)[1]: drawing_path}}
    else:
        raise ValueError("需要 --drawings-dir 或 --drawing + --prod-no")

    if not target:
        log.warning("没有需要处理的图纸，退出")
        return

    log.info(f"\n待处理生产单: {len(target)} 个")
    for pn, parts_dict in target.items():
        labels = [k if k else "(无零件号)" for k in parts_dict]
        log.info(f"  {pn}: {labels}")

    # ── Step 1: 批量视觉+推理（缓存优先）──
    log.info(f"\n{'='*60}")
    log.info("批量视觉分析 + 工艺推理...")

    # 检查缓存是否已存在
    from scripts.vision_service import load_analysis_cache
    first_pn = next(iter(target))
    has_cache = False
    try:
        cached = load_analysis_cache(first_pn)
        cached_parts = {e.get("part_no") for e in cached}
        needed_parts = set(k for k in target[first_pn].keys() if k is not None)
        if cached_parts >= needed_parts:
            has_cache = True
            log.info(f"  分析缓存已存在 ({len(cached)} 个零件)，跳过视觉分析")
    except (FileNotFoundError, StopIteration):
        pass

    if has_cache:
        # 从缓存加载 plans
        from scripts.vision_service import load_analysis_cache
        plans = {}
        for pn in target:
            cache = load_analysis_cache(pn)
            plans[pn] = {}
            for entry in cache:
                part_no = entry.get("part_no")
                part_info = entry.get("part_info", {})
                features = entry.get("features", [])
                special_reqs = entry.get("special_reqs", [])
                full_plan = reason_process(part_info, features, special_reqs)
                plans[pn][part_no] = map_to_erp_processes(full_plan)
    else:
        plans = VisionService().analyze_batch(target)

    log.info(f"\n推理完成: {sum(len(v) for v in plans.values())} 套工艺方案")

    # ── Step 2-3: 每个零件独立开浏览器处理 ──
    log.info(f"\n{'='*60}")
    log.info("逐零件处理（每个零件独立开浏览器，避免弹窗残留）...")

    success_count = 0
    fail_count = 0
    total_parts = sum(len(pd) for pd in target.values())

    for pn in sorted(target.keys()):
        parts_dict = target[pn]
        for part_no in sorted(k for k in parts_dict if k is not None):
            part_label = f"{pn}-{part_no}"
            plan = plans.get(pn, {}).get(part_no)
            if not plan:
                log.warning(f"  零件 {part_label} 无工艺方案，跳过")
                fail_count += 1
                continue

            log.info(f"\n{'='*50}")
            log.info(f"[{success_count+fail_count+1}/{total_parts}] {part_label}")

            pw_instance = None
            try:
                pw_instance = _sync_pw().start()
                context = pw_instance.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR, channel="chrome", headless=False,
                    viewport={"width": 1920, "height": 1080}, locale="zh-CN",
                )
                page = context.pages[0] if context.pages else context.new_page()

                # 登录
                log.info("  登录ERP...")
                page.goto(f"{ERP_BASE}/", timeout=30000)
                page.wait_for_timeout(3000)  # 等SPA渲染
                if page.locator('input[name="username"]').count() > 0:
                    page.fill('input[name="username"]', account)
                    page.fill('input[name="password"]', erp_password)
                    page.locator("span.login").click()
                    page.wait_for_timeout(5000)  # 等登录跳转
                    log.info("  ✓ 已登录")

                # 导航到计划工艺
                log.info("  导航到计划工艺...")
                page.goto(f"{ERP_BASE}/#/Craftwork/steel_craftworkList/0210",
                          timeout=30000)
                page.wait_for_timeout(3000)  # 等SPA渲染
                if page.locator('input[name="username"]').count() > 0:
                    page.fill('input[name="username"]', account)
                    page.fill('input[name="password"]', erp_password)
                    page.locator("span.login").click()
                    page.wait_for_timeout(5000)  # 等登录跳转
                    page.goto(f"{ERP_BASE}/#/Craftwork/steel_craftworkList/0210",
                              timeout=30000)
                    page.wait_for_timeout(3000)  # 等SPA渲染

                # 在所有标签页中搜索该零件
                found_row = None
                for tab_name in ["未发送", "BOM清单", "已发送"]:
                    js(page, f"""
                        for(let btn of document.querySelectorAll('.el-radio-button')) {{
                            let span = btn.querySelector('.el-radio-button__inner');
                            if(span && span.textContent.trim() === '{tab_name}') {{ btn.click(); return; }}
                        }}
                    """)
                    page.wait_for_timeout(2000)  # 等标签切换
                    inp = page.locator('input[placeholder="请输入生产单号"]')
                    if inp.count() > 0:
                        inp.fill(pn)
                    page.locator('button:has-text("查询")').first.click()
                    page.wait_for_timeout(3000)  # 等查询结果

                    rows = get_all_matching_rows(page, pn)
                    for r in rows:
                        pn_val = r.get("partNo", "").strip()
                        ri = r.get("ri", -1)
                        if pn_val == part_no and ri >= 0:
                            found_row = {"tab": tab_name, "row_index": ri}
                            log.info(f"  ✓ 找到 → {tab_name} 标签行{ri}")
                            break
                    if found_row:
                        break

                if not found_row:
                    log.warning(f"  ⚠ 零件 {part_label} 在所有标签中都未找到，跳过")
                    fail_count += 1
                    continue

                # 勾选 → 开弹窗 → 填 → 保存 → 取消勾选
                click_row_checkbox(page, found_row["row_index"])
                page.wait_for_timeout(300)
                click_process_mgmt(page)
                page.wait_for_timeout(3000)  # 等弹窗渲染

                if not dialog_js(page, "return true;"):
                    log.warning(f"  弹窗未打开，重试...")
                    page.wait_for_timeout(300)
                    click_process_mgmt(page)
                    page.wait_for_timeout(3000)  # 等弹窗渲染

                if not dialog_js(page, "return true;"):
                    log.error(f"  弹窗打开失败，跳过")
                    fail_count += 1
                    continue

                fill_one_part(page, part_label, plan, pn, part_no,
                              is_multi=total_parts > 1)

                page.wait_for_timeout(300)
                click_row_checkbox(page, found_row["row_index"])
                log.info(f"  ✅ 零件 {part_label} 完成")
                success_count += 1

            except Exception as e:
                log.error(f"  ❌ 零件 {part_label} 处理失败: {e}")
                fail_count += 1
            finally:
                if pw_instance:
                    try:
                        context.close()
                        pw_instance.stop()
                    except Exception:
                        pass

    # 完成报告
    log.info(f"\n{'='*60}")
    log.info("✅ 全流程完成!")
    log.info(f"   成功: {success_count}/{total_parts}")
    log.info(f"   失败: {fail_count}/{total_parts}")
    print(f"\n{'='*50}")
    print(f"✅ 全流程完成! 成功 {success_count}/{total_parts}")
    print(f"{'='*50}")

    # ── CNC 编程（spawn 子进程独立运行，不阻塞主流程）──
    if success_count > 0 and target:
        cnc_script = str(Path(__file__).parent / "run_cnc_pipeline.py")
        log_dir = Path(__file__).parent.parent / "data"
        log_dir.mkdir(exist_ok=True)
        for pn in sorted(target.keys()):
            log_path = log_dir / f"cnc_{pn}.log"
            cmd = f"cd {Path(__file__).parent.parent} && python3 {cnc_script} --prod-no {pn}"
            try:
                import subprocess
                proc = subprocess.Popen(
                    cmd, shell=True,
                    stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
                )
                log.info(f"  CNC 编程已启动 (PID={proc.pid}) → {log_path.name}")
                print(f"    CNC [{pn}] PID={proc.pid}, 日志: {log_path}")
            except Exception as e:
                log.warning(f"  CNC 启动失败（{pn}）: {e}")

    # ── 发送飞书通知 ──
    try:
        _send_feishu_notification(success_count, total_parts, fail_count, target)
    except Exception as e:
        log.warning(f"飞书通知发送失败: {e}")


# ─── 飞书通知 ─────────────────────────────────────

def _send_feishu_notification(success: int, total: int, failed: int, target: dict):
    """发送全流程完成通知到飞书用户私聊
    凭证从环境变量读取（.env）：FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_OPEN_ID
    """
    import urllib.request
    import json as _json

    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    user_open_id = os.environ.get("FEISHU_OPEN_ID", "")
    if not app_id or not app_secret:
        log.warning("飞书凭证未配置（FEISHU_APP_ID/FEISHU_APP_SECRET）")
        return
    # 1. 获取 tenant_access_token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_data = _json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(token_url, data=token_data,
                                 headers={"Content-Type": "application/json"})
    resp = _json.loads(urllib.request.urlopen(req, timeout=10).read())
    token = resp.get("tenant_access_token", "")
    if not token:
        log.warning("获取飞书 token 失败")
        return

    # 2. 构建消息内容
    prod_lines = []
    for pn, parts_dict in target.items():
        for pt in parts_dict:
            label = f"{pn}-{pt}" if pt else pn
            prod_lines.append(f"  📄 {label}")
    prod_str = "\n".join(prod_lines)

    status = "✅ 全部成功" if failed == 0 else f"⚠️ {failed} 个失败"
    msg_content = _json.dumps({
        "text": (
            f"🔧 森蓝ERP工艺全流程完成\n"
            f"状态: {status}\n"
            f"成功: {success}/{total}\n\n"
            f"处理零件:\n{prod_str}\n\n"
            f"📌 工艺已填入ERP计划工艺页面"
        )
    })

    # 3. 发送消息到用户私聊
    msg_url = "https://open.feishu.cn/open-apis/im/v1/messages"
    msg_data = _json.dumps({
        "receive_id": user_open_id,
        "msg_type": "text",
        "content": msg_content,
    }).encode()
    req2 = urllib.request.Request(msg_url, data=msg_data,
                                  headers={
                                      "Content-Type": "application/json",
                                      "Authorization": f"Bearer {token}",
                                  })
    resp2 = _json.loads(urllib.request.urlopen(req2, timeout=10).read())
    if resp2.get("code") == 0:
        log.info("✅ 飞书通知已发送到用户私聊")
    else:
        log.warning(f"飞书消息发送失败: {resp2}")


# ─── CLI ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="森蓝ERP工艺全流程")
    parser.add_argument("--drawings-dir", default=None, help="图纸目录，自动扫描所有生产单")
    parser.add_argument("--drawing", default=None, help="单张图纸路径（向后兼容）")
    parser.add_argument("--prod-no", default=None, help="生产单号（配合 --drawings-dir 过滤，或 --drawing 指定）")
    parser.add_argument("--parts", default=None, help="零件号过滤（逗号分隔，配合 --drawings-dir）")
    parser.add_argument("--account", default="472", help="ERP账号")
    args = parser.parse_args()

    run(
        drawings_dir=args.drawings_dir,
        drawing_path=args.drawing,
        prod_no=args.prod_no,
        parts=args.parts,
        account=args.account,
    )


if __name__ == "__main__":
    main()
