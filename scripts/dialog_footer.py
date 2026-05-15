#!/usr/bin/env python3
"""查看工艺管理弹窗脚部和按钮"""
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

p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)
p.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)

# Search
p.run_js("""
let inp = document.querySelector('input[placeholder="请输入生产单号"]');
if(inp) {
    let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    ns.call(inp, 'W20126051401');
    inp.dispatchEvent(new Event('input', {bubbles:true}));
    inp.dispatchEvent(new Event('change', {bubbles:true}));
}
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    for(let span of btn.querySelectorAll('span')) {
        if(span.textContent.trim() === '查询') { btn.click(); return; }
    }
}
""")
time.sleep(3)

# Check row + 工艺管理
p.run_js("""
let rows = document.querySelectorAll('.vxe-body--row');
for(let row of rows) {
    if(row.textContent.includes('W20126051401')) {
        let checkbox = row.querySelector('.vxe-cell--checkbox');
        if(checkbox) checkbox.click();
        break;
    }
}
""")
time.sleep(1)

p.run_js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    for(let span of btn.querySelectorAll('span')) {
        if(span.textContent.trim() === '工艺管理') { btn.click(); return; }
    }
}
""")
time.sleep(3)

# Get dialog FULL outerHTML including footer
result = p.run_js("""
let dialogs = document.querySelectorAll('.el-dialog');
for(let d of dialogs) {
    let title = (d.querySelector('.el-dialog__title') || {}).textContent || '';
    if(title.trim() === '工艺管理') {
        return d.outerHTML;
    }
}
return 'not found';
""")
print("=== FULL DIALOG OUTER HTML ===")
print(result[-3000:])  # Show the last 3000 chars for footer/buttons

p.quit()
