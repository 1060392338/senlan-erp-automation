#!/usr/bin/env python3
"""ERP填工艺 — 完整流程"""
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

# ── 1. LOGIN ──
print("[1] 登录...")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)
print(f"  已登录: {p.title}")

# ── 2. NAVIGATE to 计划工艺 ──
print("[2] 导航到计划工艺...")
js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(3)
print(f"  URL: {p.url[:80]}")

# ── 3. Check page content ──
print("[3] 页面内容...")
body = js("return document.body.innerText.substring(0, 500)")
print(f"  {body[:300]}")

# ── 4. Search for production order ──
print("[4] 搜索W20126051401...")
# Find search input
search_result = js("""
// Try various selectors for search input
let selectors = [
    'input[placeholder*="搜索"]',
    'input[placeholder*="查询"]', 
    'input[placeholder*="生产单号"]',
    'input.el-input__inner'
];
for(let sel of selectors) {
    let inputs = document.querySelectorAll(sel);
    for(let inp of inputs) {
        if(inp.offsetParent !== null) { // visible
            return 'found:' + sel + '|plc:' + (inp.placeholder || '');
        }
    }
}
return 'no visible input found';
""")
print(f"  搜索框: {search_result}")

# Set search value and trigger
js_result = js("""
let inp = document.querySelector('input.el-input__inner') || document.querySelector('input[placeholder*="搜索"]');
if(!inp) return 'no input';
// Set value via native setter
let nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
nativeSetter.call(inp, 'W20126051401');
inp.dispatchEvent(new Event('input', {bubbles:true}));
inp.dispatchEvent(new Event('change', {bubbles:true}));
return 'set W20126051401';
""")
print(f"  搜索操作: {js_result}")
time.sleep(1)

# Click search button or press Enter
search_action = js("""
// Try find search button
let btns = document.querySelectorAll('button, span, i');
for(let btn of btns) {
    let txt = btn.textContent.trim();
    if(txt === '查询' || txt === '搜索' || btn.className.includes('search') || btn.className.includes('query')) {
        btn.click();
        return 'clicked:' + txt;
    }
}
// Try pressing Enter
let inp = document.querySelector('input.el-input__inner');
if(inp) {
    inp.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13}));
    return 'enter pressed';
}
return 'no action taken';
""")
print(f"  搜索触发: {search_action}")
time.sleep(3)

# Check if order exists
has_order = js("document.body.innerText.includes('W20126051401')")
print(f"  W20126051401存在: {has_order}")

# ── 5. List all interactive elements ──
print("[5] 页面元素...")
elements = js("""
let all = [];
document.querySelectorAll('button, a, input, select, textarea, i[class*=el-icon], span[class*=el-icon]').forEach(el => {
    let txt = el.textContent.trim().substring(0,30);
    let cls = el.className.substring(0,40);
    let plc = el.placeholder || '';
    let href = el.getAttribute('href') || '';
    if(txt || plc || href) {
        all.push({tag: el.tagName, text: txt, class: cls, placeholder: plc, href: href});
    }
});
return JSON.stringify(all.slice(0,60));
""")
print(f"  元素: {elements[:1000]}")

# ── 6. Try to find and click 工艺管理 ──
print("[6] 查找工艺管理按钮...")
btn_check = js("""
let btns = [];
document.querySelectorAll('*').forEach(el => {
    let txt = el.textContent.trim();
    if(txt.includes('工艺') || txt.includes('新增') || txt.includes('编辑')) {
        btns.push({tag: el.tagName, text: txt.substring(0,20), class: el.className.substring(0,30)});
    }
});
return JSON.stringify(btns.slice(0,20));
""")
print(f"  按钮: {btn_check[:500]}")

p.quit()
print("\nDONE")
