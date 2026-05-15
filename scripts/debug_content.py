#!/usr/bin/env python3
"""Debug: 计划工艺页面结构"""
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

# Go to 计划工艺
p.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)

# Get all text from the content area (not sidebar)
content = p.run_js("""
// Try to find the main content area
let main = document.querySelector('.main-container') || document.querySelector('.app-main') || document.querySelector('#app') || document.body;
// Get all text from main excluding sidebar
let sidebar = main.querySelector('.sidebar-container');
let text = main.innerText;
if(sidebar) {
    let sideText = sidebar.innerText;
    text = text.replace(sideText, '');
}
// Filter to meaningful lines
return text.split('\\n').map(l=>l.trim()).filter(l=>l.length>2).slice(0,50).join('\\n');
""")
print("=== CONTENT AREA ===")
print(content[:1000])

# Get ALL HTML of main content area
html_snippet = p.run_js("""
let main = document.querySelector('.main-container');
if(!main) main = document.querySelector('.app-main');
if(!main) main = document.body;
return main.innerHTML.substring(0, 3000);
""")
print("\n=== MAIN HTML ===")
print(html_snippet[:1500])

# Look for router-view or page content wrapper
wrapper = p.run_js("""
let views = document.querySelectorAll('[class*=view], [class*=page], [class*=content], .app-main, .main-container');
let info = [];
views.forEach(v => {
    let cls = v.className;
    let children = v.children.length;
    let txt = (v.innerText || '').trim().substring(0,60);
    info.push({class: cls, children, text: txt});
});
return JSON.stringify(info);
""")
print("\n=== PAGE WRAPPERS ===")
print(wrapper[:800])

p.quit()
