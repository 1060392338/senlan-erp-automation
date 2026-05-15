#!/usr/bin/env python3
"""独立：登录ERP → 搜索W20126051401 → 打开工艺管理 → 按AI生成的3道工序填表 → 保存"""
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
# 根据STRIPPER RING图纸分析 → 3道工序
PROCESS_STEPS = [
    {"name": "数控精车", "hours": 2.5, "worker": "Takisawa", 
     "remark": "车外圆、内孔、端面。S7(54-56HRC)，单边留0.3mm余量。Ra0.8。"},
    {"name": "慢走丝", "hours": 3.0, "worker": "Sodick",
     "remark": "割2×Ø10.47精孔、3.05mm槽。公差±0.005。Ra0.63。割1修2。"},
    {"name": "镜面放电", "hours": 4.0, "worker": "Sodick AM45L",
     "remark": "精加工细部特征。电极损耗<0.5%，镜面Ra0.2。"},
]

# ── 1. 登录 ──
print("[1/8] 登录ERP...")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)
print(f"  ✓ 登录: {p.title[:40]}")

# ── 2. 导航 ──
print("[2/8] 导航到计划工艺...")
js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)
print(f"  URL: {p.url[:60]}")

# ── 3. 搜索 ──
print("[3/8] 搜索生产单...")
js(f"""
    let inp = document.querySelector('input[placeholder="请输入生产单号"]');
    if(inp) {{
        let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        ns.call(inp, '{PROD_NO}');
        inp.dispatchEvent(new Event('input', {{bubbles:true}}));
        inp.dispatchEvent(new Event('change', {{bubbles:true}}));
    }}
""")
time.sleep(0.5)
js("""
    let btns = document.querySelectorAll('button');
    for(let btn of btns) {
        for(let span of btn.querySelectorAll('span'))
            if(span.textContent.trim() === '查询') { btn.click(); return; }
    }
""")
time.sleep(3)

# Check table
has_order = js(f"document.body.innerText.includes('{PROD_NO}')")
print(f"  {'✓ 找到' if has_order else '✗ 未找到'} {PROD_NO}")

# ── 4. 勾选行 ──
print("[4/8] 勾选行...")
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

# ── 5. 打开工艺管理 ──
print("[5/8] 打开工艺管理...")
js("""
    let btns = document.querySelectorAll('button');
    for(let btn of btns) {
        for(let span of btn.querySelectorAll('span'))
            if(span.textContent.trim() === '工艺管理') { btn.click(); return; }
    }
""")
time.sleep(4)

# Verify dialog
dialog = js("""
    let dls = document.querySelectorAll('.el-dialog');
    for(let d of dls) {
        let title = (d.querySelector('.el-dialog__title')||{}).textContent||'';
        if(title.trim() === '工艺管理') return 'open';
    }
    return 'not found';
""")
print(f"  ✓ 弹窗: {dialog}")
if dialog != 'open':
    p.quit()
    exit(1)

# ── 6. 清空并添加3行 ──
print("[6/8] 设置工序行...")

# Delete existing rows
js("""
    let gridEl = document.querySelector('.vxe-grid');
    if(gridEl && gridEl.__vue__) {
        let vm = gridEl.__vue__;
        if(Array.isArray(vm.fullData)) {
            // Remove all existing rows
            while(vm.fullData.length > 0) {
                if(typeof vm.remove === 'function') vm.remove(vm.fullData[0]);
                else vm.fullData.pop();
            }
        }
    }
""")
time.sleep(1)

# Insert 3 rows
for i in range(3):
    js("""
        let gridEl = document.querySelector('.vxe-grid');
        if(gridEl && gridEl.__vue__) {
            let vm = gridEl.__vue__;
            if(typeof vm.insert === 'function') vm.insert({});
            else if(Array.isArray(vm.fullData)) vm.fullData.push({});
        }
    """)
    time.sleep(0.5)
    print(f"  添加行 {i+1}")

# ── 7. Fill each row ──
print("[7/8] 填写工序数据...")
time.sleep(1)
for idx, step in enumerate(PROCESS_STEPS):
    print(f"  行{idx+1}: {step['name']}")
    r = js(f"""
        let gridEl = document.querySelector('.vxe-grid');
        if(!gridEl || !gridEl.__vue__) return 'no_vue';
        let vm = gridEl.__vue__;
        let rows = vm.fullData || [];
        if(rows.length <= {idx}) return 'no_row_{idx}';
        let row = rows[{idx}];
        
        if(typeof vm.setCellValue === 'function') {{
            vm.setCellValue(row, 'table_type', '{step['name']}');
            vm.setCellValue(row, 'machine', {step['hours']});
            vm.setCellValue(row, 'remark', `{step['remark']}`);
            vm.setCellValue(row, 'plan_worker', '{step['worker']}');
            return 'ok';
        }}
        // Direct manipulation
        row['table_type'] = '{step['name']}';
        row['machine'] = {step['hours']};
        row['remark'] = `{step['remark']}`;
        row['plan_worker'] = '{step['worker']}';
        return 'direct_ok';
    """)
    print(f"    {r}")
    time.sleep(0.5)

# ── 8. 保存 ──
print("[8/8] 保存...")
time.sleep(1)
save_result = js("""
    let footer = document.querySelector('.el-dialog__footer');
    if(!footer) return 'no_footer';
    let btns = footer.querySelectorAll('button');
    for(let btn of btns) {
        let span = btn.querySelector('span');
        if(span && span.textContent.trim() === '保存' && btn.classList.contains('el-button--primary')) {
            btn.click();
            return 'saved';
        }
    }
    return 'save_not_found';
""")
print(f"  {'✓ 已保存' if 'saved' in save_result else f'✗ {save_result}'}")
time.sleep(3)

p.quit()
print("\nDONE")
