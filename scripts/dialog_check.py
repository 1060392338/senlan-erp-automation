#!/usr/bin/env python3
"""快速确认工艺管理弹窗结构"""
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

# Check checkbox + click 工艺管理
p.run_js("""
let rows = document.querySelectorAll('.vxe-body--row');
for(let row of rows) {
    if(row.textContent.includes('W20126051401')) {
        let checkbox = row.querySelector('.vxe-cell--checkbox');
        if(checkbox) checkbox.click();
        break;
    }
}
// Also try clicking header checkbox
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

# Dump ALL dialogs
result = p.run_js("""
let dialogs = document.querySelectorAll('.el-dialog');
let info = [];
dialogs.forEach(d => {
    if(window.getComputedStyle(d).display !== 'none') {
        info.push({
            title: (d.querySelector('.el-dialog__title') || {}).textContent || '',
            bodyHTML: d.querySelector('.el-dialog__body') ? d.querySelector('.el-dialog__body').innerHTML.substring(0, 4000) : 'no body'
        });
    }
});
return JSON.stringify(info);
""")
print("=== DIALOGS ===")
print(result[:5000])

p.quit()
