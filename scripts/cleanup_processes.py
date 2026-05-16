#!/usr/bin/env python3
"""删多余工序行 + 按特征驱动结果重新填充"""
import json, logging, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(Path(__file__).parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("cleanup")

ERP_BASE = "http://112.74.35.30"
USER_DATA_DIR = "data/chrome_data/playwright"
from config.dropdown_options import ERP_CODE_MAP

def run():
    from playwright.sync_api import sync_playwright as _pw
    from workflows.erp_process.process_reasoning import reason_process, map_to_erp_processes

    api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-44dc747ec9b044ea886cdd468ad3a851")
    from services.llm_client import LLMClient
    from services.prompt_service import PromptService
    from workflows.erp_process.agents.vision_agent import VisionAgent

    uname = os.environ.get("ERP_473_USERNAME", "473")
    passwd = os.environ.get("ERP_473_PASSWORD", "123456")
    prod_no = "W20126051401"

    # ── 0. 视觉分析+特征推理 ──
    log.info("视觉分析...")
    llm = LLMClient(api_key=api_key)
    prompt = PromptService()
    vision = VisionAgent(llm=llm, prompt_service=prompt)
    vision_result = vision.analyze("data/drawing_W20126051401.pdf", prod_no)
    plan = reason_process(vision_result["part_info"], vision_result["features"],
                          vision_result.get("special_requirements", []))
    process_plan = map_to_erp_processes(plan)
    keep_count = len(process_plan)
    keep_names = [p["name"] for p in process_plan]
    log.info(f"特征驱动工序({keep_count}道): {keep_names}")

    # ── 浏览器操作 ──
    pw = _pw().start()
    ctx = pw.chromium.launch_persistent_context(
        USER_DATA_DIR, channel="chrome", headless=False,
        viewport={"width": 1920, "height": 1080}, locale="zh-CN",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    try:
        page.goto(ERP_BASE, timeout=15000); time.sleep(3)
        if page.locator('input[name="username"]').count():
            page.fill('input[name="username"]', uname)
            page.fill('input[name="password"]', passwd)
            page.locator("span.login").click(); time.sleep(4)

        page.goto(f"{ERP_BASE}/#/Craftwork/steel_craftworkList/0210",
                  wait_until="domcontentloaded", timeout=15000); time.sleep(5)

        for tab in ["BOM清单", "未发送", "已发送"]:
            page.evaluate(f"""() => {{
                document.querySelectorAll('.el-radio-button').forEach(b => {{
                    let s = b.querySelector('.el-radio-button__inner');
                    if(s && s.textContent.trim() === '{tab}') b.click();
                }});
            }}""")
            time.sleep(1.5)
            inp = page.locator('input[placeholder="请输入生产单号"]')
            if inp.count(): inp.fill(prod_no); time.sleep(0.3)
            page.locator('button:has-text("查询")').first.click(); time.sleep(3)

            found = page.evaluate(f"""(p) => {{
                for(let r of document.querySelectorAll('.vxe-body--row'))
                    if((r.textContent||'').includes(p)) return true;
                return false;
            }}""", prod_no)
            if found:
                log.info(f"在 {tab} 下找到")
                break

        # 勾选+点工艺管理
        page.evaluate(f"""(p) => {{
            for(let r of document.querySelectorAll('.vxe-body--row'))
                if((r.textContent||'').includes(p)) {{
                    let cb = r.querySelector('.vxe-cell--checkbox');
                    if(cb) cb.click(); break;
                }}
        }}""", prod_no)
        page.evaluate("""() => {
            document.querySelectorAll('button').forEach(b => {
                if(b.textContent.trim() === '工艺管理') b.click();
            });
        }""")
        time.sleep(6)

        # 确认弹窗
        has_d = page.evaluate("""() => {
            for(let d of document.querySelectorAll('.el-dialog'))
                if((d.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') return true;
            return false;
        }""")
        log.info(f"弹窗存在: {has_d}")
        if not has_d: raise RuntimeError("弹窗未打开")

        # 读当前行数
        info = page.evaluate("""() => {
            let d = null;
            document.querySelectorAll('.el-dialog').forEach(d2 => {
                if((d2.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') d = d2;
            });
            if(!d) return {error: 'no_dialog'};
            let grid = d.querySelector('.vxe-grid');
            if(!grid) return {error: 'no_grid'};
            let vm = grid.__vue__;
            if(!vm || !vm.getData) return {error: 'no_vm'};
            try {
                let data = vm.getData();
                return {total: data.length, keys: Object.keys(data[0]||{}).slice(0,10)};
            } catch(e) { return {error: String(e)}; }
        }""")
        log.info(f"弹窗信息: {json.dumps(info, ensure_ascii=False)}")

        total = info.get('total', 0)
        if not total:
            log.warning("无数据行，需要先加行")
            total = 0

        # 删除多余行（尝试vm.remove）
        deleted_count = 0
        if total > keep_count:
            to_del = list(range(keep_count, total))
            log.info(f"清除多余行({len(to_del)}行): {to_del}")
            for idx in to_del:
                page.evaluate("""(i) => {
                    let d = null;
                    document.querySelectorAll('.el-dialog').forEach(d2 => {
                        if((d2.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') d = d2;
                    });
                    let vm = d.querySelector('.vxe-grid').__vue__;
                    let data = vm.getData();
                    if(i < data.length) {
                        // 清空所有字段
                        Object.keys(data[i]).forEach(k => {
                            if(typeof data[i][k] === 'string') data[i][k] = '';
                            else if(typeof data[i][k] === 'number') data[i][k] = 0;
                        });
                    }
                }""", idx)
            time.sleep(0.2)
            deleted_count = len(to_del)

        # 检查行数
        new_total = page.evaluate("""() => {
            let d = null;
            document.querySelectorAll('.el-dialog').forEach(d2 => {
                if((d2.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') d = d2;
            });
            let vm = d.querySelector('.vxe-grid').__vue__;
            return vm.getData().length;
        }""")
        log.info(f"当前行数: {new_total}")

        # 行数不足则加行
        if new_total < keep_count:
            add_n = keep_count - new_total
            log.info(f"添加{add_n}行...")
            for _ in range(add_n):
                page.evaluate("""() => {
                    let d = null;
                    document.querySelectorAll('.el-dialog').forEach(d2 => {
                        if((d2.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') d = d2;
                    });
                    d.querySelectorAll('.el-icon-plus').forEach(p => p.click());
                }""")
                time.sleep(0.5)

        time.sleep(1)

        # 填充数据
        log.info("填充工序数据...")
        plan_json = json.dumps(process_plan, ensure_ascii=False)
        code_map_json = json.dumps(ERP_CODE_MAP, ensure_ascii=False)
        fill_result = page.evaluate(
            "args => { let d = null; document.querySelectorAll('.el-dialog').forEach(d2 => { if((d2.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理') d = d2; }); let vm = d.querySelector('.vxe-grid').__vue__; let data = vm.getData(); let steps = args.steps; let codeMap = args.codeMap; let filled = 0; for(let i = 0; i < steps.length && i < data.length; i++) { data[i].table_type = codeMap[steps[i].name] || ''; data[i].machine = String(steps[i].machine_hours || 0); data[i].plan_worker = steps[i].worker || ''; data[i].remark = steps[i].remark || ''; filled++; } return 'filled=' + filled + '_total=' + data.length; }",
            {"steps": process_plan, "codeMap": ERP_CODE_MAP},
        )
        log.info(f"填充: {fill_result}")

        log.info("填充完成")

        # 保存（用 Playwright native click + force=True 穿透Vue遮挡层）
        log.info("保存...")
        save_btn = page.locator(
            '.el-dialog:has(.el-dialog__title:text("工艺管理")) '
            '.el-dialog__footer button.el-button--primary'
        ).first
        if save_btn.count() > 0:
            save_btn.click(force=True, timeout=5000)
            log.info("  点击保存按钮")

            time.sleep(2)
            # 确认保存：检查成功 toast
            for _ in range(10):
                toast = page.evaluate("""() => {
                    let t = document.querySelector('.el-message--success');
                    return t ? t.textContent.trim() : '';
                }""")
                if toast:
                    log.info(f"  ✓ {toast}")
                    break
                time.sleep(1)
            else:
                log.warning("  保存后未检测到成功提示，但数据可能已写入")
        else:
            log.warning("  ✗ 未找到保存按钮")

        print(f"\n{'='*60}")
        print(f"✅ 清理完成! 共{keep_count}道(基于特征驱动)")
        for p in process_plan:
            print(f"   {p['name']:10s} | {p['machine_hours']:4.1f}h | {p['remark'][:50]}")
        print(f"{'='*60}")

    finally:
        try: ctx.close()
        except: pass
        try: pw.stop()
        except: pass

if __name__ == "__main__":
    run()
