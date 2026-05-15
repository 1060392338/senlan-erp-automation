#!/usr/bin/env python3
"""修复版：找到W20126051401并填工艺"""
import time, sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_user_data_path('/tmp/senlan_chrome_472')
co.set_argument('--remote-allow-origins=*')
co.set_argument('--no-sandbox')
co.set_argument('--window-size=1920,1080')
co.set_timeouts(base=8, page_load=10, script=5)
p = ChromiumPage(co)

def js(code):
    return p.run_js(code)

PROD_NO = "W20126051401"
STEPS = [
    {"name":"数控精车","hours":2.5,"worker":"Takisawa",
     "remark":"车外圆、内孔、端面。S7(54-56HRC)，单边留0.3mm余量。Ra0.8。"},
    {"name":"慢走丝","hours":3.0,"worker":"Sodick",
     "remark":"割2×Ø10.47精孔、3.05mm槽。公差±0.005。Ra0.63。割1修2。"},
    {"name":"镜面放电","hours":4.0,"worker":"Sodick AM45L",
     "remark":"精加工细部特征。电极损耗<0.5%，镜面Ra0.2。"},
]

# ── 1. 登录 ──
print("[1] 登录...")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)

# ── 2. 导航 ──
print("[2] 导航到计划工艺...")
js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)

# ── 3. 检查页面完整内容 ──
print("[3] 检查页面...")
page_text = js("return document.body.innerText.substring(0, 2000)")
print(f"  页面内容预览: {page_text[:200]}")
has_prod = PROD_NO in page_text
print(f"  W20126051401在页面可见文字中: {has_prod}")

# ── 4. 切换radio到所有tab ──
print("[4] 遍历radio标签...")
for tab_name in ["BOM清单", "未发送", "已发送"]:
    r = js(f"""
        let labels = document.querySelectorAll('.el-radio-button__inner');
        for(let label of labels) {{
            if(label.textContent.trim() === '{tab_name}') {{
                let radio = label.closest('label');
                if(radio && !radio.classList.contains('is-active')) {{
                    label.click();
                    return 'clicked {tab_name}';
                }}
                return 'already active {tab_name}';
            }}
        }}
        return 'not found {tab_name}';
    """)
    print(f"  {r}")
    time.sleep(1)

    # Search after each tab switch
    js(f"""
        let inp = document.querySelector('input[placeholder="请输入生产单号"]');
        if(inp) {{
            let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            ns.call(inp, '{PROD_NO}');
            inp.dispatchEvent(new Event('input', {{bubbles:true}}));
            inp.dispatchEvent(new Event('change', {{bubbles:true}}));
        }}
    """)
    time.sleep(0.3)
    js("""
        let btns = document.querySelectorAll('button');
        for(let btn of btns) {
            for(let span of btn.querySelectorAll('span'))
                if(span.textContent.trim() === '查询') { btn.click(); return; }
        }
    """)
    time.sleep(2)
    
    found = js(f"return document.body.innerText.includes('{PROD_NO}')")
    print(f"    结果: {'✓ 找到' if found else '✗ 未找到'}")
    if found:
        print(f"    在 {tab_name} 标签下找到!")
        break

# ── 5. 如果3个tab都找不到，直接JS注入搜索 ──
has_prod = js(f"return document.body.innerText.includes('{PROD_NO}')")
if not has_prod:
    print("[4b] 直接设置搜索框并回车...")
    js(f"""
        let inp = document.querySelector('input[placeholder="请输入生产单号"]');
        if(inp) {{
            let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            ns.call(inp, '{PROD_NO}');
            inp.dispatchEvent(new Event('input', {{bubbles:true}}));
            inp.dispatchEvent(new Event('change', {{bubbles:true}}));
            // Try Enter key
            inp.dispatchEvent(new KeyboardEvent('keyup', {{key:'Enter', keyCode:13, bubbles:true}}));
        }}
        // Also try clicking search icon/button by class
        let qBtns = document.querySelectorAll('.el-button--primary .el-icon-search');
        qBtns.forEach(btn => btn.closest('button')?.click());
    """)
    time.sleep(3)
    has_prod = js(f"return document.body.innerText.includes('{PROD_NO}')")
    print(f"    结果: {'✓ 找到' if has_prod else '✗ 未找到'}")

if not has_prod:
    print("✗ 无法找到生产单，退出")
    p.quit()
    exit(1)

# ── 6. 勾选行 ──
print("[6] 勾选行并打开弹窗...")
js(f"""
    let rows = document.querySelectorAll('.vxe-body--row');
    for(let row of rows) {{
        if(row.textContent.includes('{PROD_NO}')) {{
            let cb = row.querySelector('.vxe-cell--checkbox');
            if(cb) cb.click();
            break;
        }}
    }}
""")
time.sleep(1)

js("""
    let btns = document.querySelectorAll('button');
    for(let btn of btns) {
        for(let span of btn.querySelectorAll('span'))
            if(span.textContent.trim() === '工艺管理') { btn.click(); return; }
    }
""")
time.sleep(4)

dialog = js("""
    let dls = document.querySelectorAll('.el-dialog');
    for(let d of dls) {
        let t = (d.querySelector('.el-dialog__title')||{}).textContent||'';
        if(t.trim() === '工艺管理') return 'open';
    }
    return 'not found';
""")
print(f"  弹窗: {dialog}")
if dialog != 'open': exit(1)

# ── 6.5 Re-initialize table ──
print("[6.5] 清空表格并重新初始化...")
js("""
    let gridEl = document.querySelector('.vxe-grid');
    if(!gridEl || !gridEl.__vue__) return;
    let vm = gridEl.__vue__;
    // Wait for grid to be ready
    setTimeout(() => {
        if(Array.isArray(vm.fullData)) {
            // Clear all
            while(vm.fullData.length > 0) {
                if(typeof vm.remove === 'function') vm.remove(vm.fullData[0]);
                else vm.fullData.splice(0, vm.fullData.length);
            }
        }
    }, 500);
""")
time.sleep(2)

# Try to use reload/recreate grid data
for i in range(3):
    r = js("""
        let gridEl = document.querySelector('.vxe-grid');
        if(!gridEl || !gridEl.__vue__) return 'no_vue';
        let vm = gridEl.__vue__;
        
        // VXE4+ uses different APIs - try tableData
        let data = vm.fullData || vm.tableData || [];
        
        // Try push a new row
        if(Array.isArray(data)) {
            data.push({});
            return 'pushed_' + data.length;
        }
        
        // Try reactive set
        if(vm.tableData === undefined && vm.fullData === undefined) {
            // Component not mounted yet
            return 'not_mounted';
        }
        return 'unknown_' + typeof data;
    """)
    print(f"  添加行{i+1}: {r}")
    time.sleep(0.8)

# Check rows count
cnt = js("return (document.querySelector('.vxe-grid').__vue__.fullData || []).length")
print(f"  VXE行数: {cnt}")

# ── 7. 填数据 ──
print("[7] 填表...")
for idx, step in enumerate(STEPS):
    r = js(f"""
        let vm = document.querySelector('.vxe-grid').__vue__;
        let rows = vm.fullData || vm.tableData || [];
        if(rows.length <= {idx}) return 'row_not_found_{idx}_of_{len(rows)}';
        let row = rows[{idx}];
        row.table_type = '{step['name']}';
        row.machine = {step['hours']};
        row.plan_worker = '{step['worker']}';
        row.remark = `{step['remark']}`;
        return 'filled_{step['name']}';
    """)
    print(f"  行{idx+1} {step['name']}: {r}")
    time.sleep(0.5)

# ── 8. 保存 ──
print("[8] 保存...")
time.sleep(1)
r = js("""
    let footer = document.querySelector('.el-dialog__footer');
    let btns = footer.querySelectorAll('button');
    for(let btn of btns) {
        let span = btn.querySelector('span');
        if(span && span.textContent.trim() === '保存' && btn.classList.contains('el-button--primary')) {
            btn.click(); return 'saved';
        }
    }
    return 'not_found';
""")
print(f"  {'✓ 已保存' if 'saved' in r else f'✗ {r}'}")
time.sleep(3)

p.quit()
print("\n✓ DONE")
