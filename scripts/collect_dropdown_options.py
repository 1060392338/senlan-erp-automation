#!/usr/bin/env python3
"""从弹窗表头提取所有工序选项并对比现有映射表"""
import json, logging, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("collect")

ERP_BASE = "http://112.74.35.30"
USER_DATA_DIR = "data/chrome_data/playwright"

def run():
    from playwright.sync_api import sync_playwright as _pw
    uname = os.environ.get("ERP_USERNAME", "472")
    passwd = os.environ.get("ERP_PASSWORD", "123456")

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

        prod_no = "W20126051401"
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
            if page.evaluate(f"""(p) => {{
                for(let r of document.querySelectorAll('.vxe-body--row'))
                    if((r.textContent||'').includes(p)) return true;
                return false;
            }}""", prod_no): break

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
        time.sleep(5)

        # 从VXE表头提取选项
        header_title = page.evaluate("""() => {
            let dlg = null;
            document.querySelectorAll('.el-dialog').forEach(d => {
                if((d.querySelector('.el-dialog__title')||{}).textContent.trim() === '工艺管理')
                    dlg = d;
            });
            let headers = dlg.querySelectorAll('.vxe-header--row .vxe-header--column');
            for(let h of headers) {
                let title = h.getAttribute('title') || (h.querySelector('.vxe-cell--title')||{}).textContent || '';
                if(title.includes('工序') || title.includes('平面磨床')) return title;
            }
            return 'not_found';
        }""")

        log.info(f"表头原始文本:\n{repr(header_title)}\n")

        # 解析选项
        # 格式: "选项1 选项2 选项3...\\n      工序"
        # 去掉最后的\\n+空格+工序
        raw = header_title
        if '工序' in raw:
            raw = raw.split('工序')[0]
        # 按空格分割，但注意有的选项名含空格（如"内外圆磨"之间无空格）
        # 从原始文本观察，是用空格分隔的
        options = [o.strip() for o in raw.replace('\n', ' ').split() if o.strip()]
        
        log.info(f"解析到 {len(options)} 个工序选项:")
        for i, opt in enumerate(options, 1):
            log.info(f"  {i:2d}. {opt}")

        # 对比现有ERP_CODE_MAP
        existing_options = set(options)
        
        # 现有映射表中的ERP名字
        ERP_CODE_MAP_NAMES = [
            "平面磨床", "车床", "外协铣床", "深孔钻", "大水磨", "热处理", "出货全检", "生产入库", "枪钻",
            "慢走丝", "中走丝", "快走丝", "镜面放电", "内外圆磨", "外协省模", "冲子内圆磨", "表面处理",
            "小车床", "冲子机", "委外", "无心研磨", "滚齿加工", "成品采购", "坐标磨",
            "运费", "喷砂", "雕刻", "打头", "外发全加工", "委外制作电极", "抛光",
            "晒纹", "烧焊", "扣款", "打孔", "高频", "珩磨", "委外拆电极",
            "CNC精锣", "半成品采购", "数控精车", "数控粗车", "铣床",
            "省模", "CNC粗锣", "3D打印", "委外模具设计", "模具采购", "全加工",
        ]
        existing_map_names = set(ERP_CODE_MAP_NAMES)
        
        new_options = existing_options - existing_map_names
        missing_options = existing_map_names - existing_options
        
        log.info(f"\n现有映射表已有: {len(existing_map_names & existing_options)}/{len(existing_options)} 个选项")
        if new_options:
            log.info(f"\n新发现的选项(映射表里没有): {sorted(new_options)}")
        if missing_options:
            log.info(f"\n映射表有但弹窗没找到: {sorted(missing_options)}")
            # "委外制作电极" vs "委外制作电极" - 检查是否同名不同格式
            for m in sorted(missing_options):
                for o in sorted(existing_options):
                    if m in o or o in m:
                        log.info(f"  '{m}' 可能对应 '{o}'")

        # 保存结果
        result = {
            "dropdown_options": sorted(options),
            "count": len(options),
            "new_vs_existing": {
                "existing_in_dropdown": sorted(existing_map_names & existing_options),
                "new_options_not_in_map": sorted(new_options),
                "map_has_but_dropdown_missing": sorted(missing_options),
            }
        }
        with open("data/dropdown_options.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log.info("\n已保存到 data/dropdown_options.json")

        print("\n" + "="*70)
        print(f"✅ 工序下拉选项共 {len(options)} 个:")
        cols = 5
        for i in range(0, len(options), cols):
            chunk = options[i:i+cols]
            print(f"  {''.join(f'{o:12s}' for o in chunk)}")
        if new_options:
            print(f"\n⚠️ 新发现(映射表未覆盖): {sorted(new_options)}")
        print("="*70)

    finally:
        try: ctx.close()
        except: pass
        try: pw.stop()
        except: pass

if __name__ == "__main__":
    run()
