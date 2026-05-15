#!/usr/bin/env python3
"""ERP填工艺完整流程"""
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
    """Execute JS and return result"""
    return p.run_js(code)

def wait(s=1.5):
    time.sleep(s)

# ── Step 1: Login ──
print("=== STEP 1: 登录ERP ===")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
wait(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
wait(3)
print(f"  ✓ 登录成功: {p.title}")

# ── Step 2: Navigate to 计划工艺 ──
print("\n=== STEP 2: 导航到计划工艺 ===")
js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
wait(4)
print(f"  ✓ URL: {p.url[:80]}")

# ── Step 3: Search for W20126051401 ──
print("\n=== STEP 3: 搜索生产单 ===")

# Fill production order number
r = js("""
let inputs = document.querySelectorAll('input[placeholder="请输入生产单号"]');
if(inputs.length > 0) {
    let inp = inputs[0];
    let nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSetter.call(inp, 'W20126051401');
    inp.dispatchEvent(new Event('input', {bubbles: true}));
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    return 'filled:' + inp.value;
}
// Try broader search
let allInputs = document.querySelectorAll('input.el-input__inner');
for(let inp of allInputs) {
    let plc = inp.placeholder || '';
    if(plc.includes('生产')) {
        nativeSetter.call(inp, 'W20126051401');
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        return 'filled(alt):' + inp.value;
    }
}
return 'no input found';
""")
print(f"  ✓ 填写生产单号: {r}")

# Click 查询 button
r2 = js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    let spans = btn.querySelectorAll('span');
    for(let span of spans) {
        if(span.textContent.trim() === '查询') {
            btn.click();
            return 'clicked 查询';
        }
    }
}
return '查询 button not found';
""")
print(f"  ✓ 点击查询: {r2}")
wait(3)

# Check results
r3 = js("""
let table = document.querySelector('.vxe-table--body-wrapper') || document.querySelector('.vxe-table--main-wrapper');
if(!table) return 'no table found';
// Get all rows
let rows = table.querySelectorAll('.vxe-body--row');
if(rows.length === 0) {
    // Check for empty state
    let empty = document.querySelector('.vxe-table--empty-content');
    if(empty) return 'empty: ' + empty.textContent.trim();
    return 'no rows found';
}
let data = [];
rows.forEach(row => {
    let cells = row.querySelectorAll('td');
    let rowData = [];
    cells.forEach(cell => rowData.push(cell.textContent.trim()));
    data.push(rowData.join(' | '));
});
return JSON.stringify(data);
""")
print(f"  ✓ 查询结果: {r3[:500]}")

# ── Step 4: If found, click row to open 工艺管理 ──
print("\n=== STEP 4: 工艺管理 ===")
if 'W20126051401' in r3:
    print("  ✓ 找到生产单，打开工艺管理...")
    # Click the 工艺管理 button in that row
    r4 = js("""
    let table = document.querySelector('.vxe-table--body-wrapper');
    let rows = table.querySelectorAll('.vxe-body--row');
    for(let row of rows) {
        if(row.textContent.includes('W20126051401')) {
            // Find the edit/工艺管理 button in action column
            let btns = row.querySelectorAll('button, i');
            for(let btn of btns) {
                let txt = btn.textContent.trim();
                let cls = btn.className || '';
                if(txt.includes('工艺') || txt.includes('编辑') || cls.includes('edit') || cls.includes('tool')) {
                    btn.click();
                    return 'clicked:' + (txt || cls);
                }
            }
            return 'no action button in row';
        }
    }
    return 'row not found';
    """)
    print(f"  {r4}")
    wait(2)
else:
    print("  ✗ 生产单W20126051401不存在！需先创建销售订单")
    # Let's check what order numbers ARE in the table
    r5 = js("""
    let table = document.querySelector('.vxe-table--body-wrapper');
    if(!table) return 'no table';
    let rows = table.querySelectorAll('.vxe-body--row');
    let orderNos = [];
    rows.forEach(row => {
        let cells = row.querySelectorAll('td');
        if(cells.length > 2) orderNos.push(cells[2].textContent.trim());
    });
    return JSON.stringify(orderNos.slice(0,10));
    """)
    print(f"  ℹ 当前表中生产单号: {r5[:300]}")

# ── Step 5: Check dialog appearance ──
wait(2)
dialog_check = js("""
let dialogs = document.querySelectorAll('.el-dialog');
let info = [];
dialogs.forEach(d => {
    let visible = window.getComputedStyle(d).display !== 'none' && !d.className.includes('__close');
    if(visible) {
        info.push({
            class: d.className.substring(0,50),
            title: (d.querySelector('.el-dialog__title') || {}).textContent || '',
            bodyLength: (d.querySelector('.el-dialog__body') || {}).innerHTML?.length || 0
        });
    }
});
return JSON.stringify(info);
""")
print(f"\n  ℹ 对话框: {dialog_check[:300]}")

p.quit()
print("\nDONE")
