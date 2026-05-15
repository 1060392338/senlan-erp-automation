#!/usr/bin/env python3
"""找到并点击工艺管理入口"""
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

# Navigate
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
""")
time.sleep(0.5)

# Click 查询
p.run_js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    for(let span of btn.querySelectorAll('span')) {
        if(span.textContent.trim() === '查询') {
            btn.click(); return;
         }
    }
}
""")
time.sleep(3)

# NOW inspect the matched row structure
result = p.run_js("""
let rows = document.querySelectorAll('.vxe-body--row');
for(let row of rows) {
    if(row.textContent.includes('W20126051401')) {
        // Dump all interactive elements in this row
        let cells = row.querySelectorAll('td');
        let info = [];
        cells.forEach((cell, idx) => {
            let html = cell.innerHTML.substring(0, 200);
            let txt = cell.textContent.trim().substring(0,30);
            info.push({col: idx, text: txt, html: html});
        });
        return JSON.stringify(info);
    }
}
return 'row not found';
""")
print("=== ROW STRUCTURE ===")
print(result[:3000])

# Also find any 工艺管理 button anywhere on the page
btn_info = p.run_js("""
let btns = [];
document.querySelectorAll('button').forEach(btn => {
    let txt = btn.textContent.trim();
    let cls = btn.className || '';
    let outer = btn.outerHTML.substring(0, 200);
    if(txt.includes('工艺')) {
        btns.push({text: txt, class: cls, html: outer});
    }
});
return JSON.stringify(btns);
""")
print("\n=== 工艺 BUTTONS ===")
print(btn_info[:2000])

p.quit()
