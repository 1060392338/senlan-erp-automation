#!/usr/bin/env python3
"""快速测试：process_filler 的导航和弹窗"""
import time, sys, os
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

# Login
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)

# Now simulate what process_filler does after erp_reconnect
# The page is at dashboard (#/dashboard)
print(f"1. Current URL: {p.url[:60]}")

# Navigate to plan process
js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)
print(f"2. After hash: {p.url[:60]}")

# Search
js("""
let inp = document.querySelector('input[placeholder="请输入生产单号"]');
if(inp) {
    let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    ns.call(inp, 'W20126051401');
    inp.dispatchEvent(new Event('input', {bubbles:true}));
    inp.dispatchEvent(new Event('change', {bubbles:true}));
}
""")
time.sleep(0.3)

# Try each tab + search
for tab in ["BOM清单", "未发送", "已发送"]:
    js(f"""
        let labels = document.querySelectorAll('.el-radio-button__inner');
        for(let label of labels) {{
            if(label.textContent.trim() === '{tab}') {{
                let radio = label.closest('label');
                if(radio && !radio.classList.contains('is-active')) label.click();
                break;
            }}
        }}
    """)
    time.sleep(1)
    
    js("""
        let btns = document.querySelectorAll('button');
        for(let btn of btns) {
            for(let span of btn.querySelectorAll('span'))
                if(span.textContent.trim() === '查询') { btn.click(); return; }
        }
    """)
    time.sleep(2.5)
    
    found = js(f"return document.body.innerText.includes('W20126051401')")
    print(f"   {tab}: {'✓' if found else '✗'}")

# Click checkbox
r = js("""
    let rows = document.querySelectorAll('.vxe-body--row');
    for(let row of rows) {
        if(row.textContent.includes('W20126051401')) {
            let cb = row.querySelector('.vxe-cell--checkbox');
            if(cb) { cb.click(); return 'checked'; }
            return 'no_cb';
        }
    }
    return 'no_row';
""")
print(f"3. Checkbox: {r}")

# Click craft mgmt button
r = js("""
    let btns = document.querySelectorAll('button');
    for(let btn of btns) {
        for(let span of btn.querySelectorAll('span'))
            if(span.textContent.trim() === '工艺管理') { btn.click(); return 'clicked'; }
    }
    return 'not_found';
""")
print(f"4. 工艺管理: {r}")
time.sleep(3)

# Check dialog
r = js("""
    let dls = document.querySelectorAll('.el-dialog');
    for(let d of dls) {
        let t = (d.querySelector('.el-dialog__title')||{}).textContent||'';
        if(t.trim() === '工艺管理') return 'open';
    }
    return 'not_found';
""")
print(f"5. 弹窗: {r}")

p.quit()
