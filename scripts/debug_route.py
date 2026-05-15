#!/usr/bin/env python3
"""Debug: 点击计划工艺并检查路由"""
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

# Expand 计划管理
p.run_js("""
let items = document.querySelectorAll('.menu-wrapper');
for(let item of items) {
    if(item.textContent.trim() === '计划管理' && !item.classList.contains('nest-menu')) {
        item.click();
        return 'expanded';
    }
}
return 'not found';
""")
time.sleep(1.5)

# Find the link href for 计划工艺
href = p.run_js("""
let items = document.querySelectorAll('.nest-menu');
for(let item of items) {
    if(item.textContent.trim().includes('计划工艺')) {
        let a = item.querySelector('a');
        if(a) return 'href:' + (a.getAttribute('href') || 'none') + '|text:' + a.textContent.trim();
        return 'no a tag found';
    }
}
return 'not found';
""")
print("计划工艺 link:", href)

# Also check for any click event on the DIV
click_info = p.run_js("""
let items = document.querySelectorAll('.nest-menu');
for(let item of items) {
    if(item.textContent.trim().includes('计划工艺')) {
        let listeners = getEventListeners ? getEventListeners(item) : [];
        return 'listeners:' + Object.keys(listeners).join(',');
    }
}
return 'no listener info';
""")
print("Click info:", click_info)

# Try clicking the a tag inside the div
p.run_js("""
let items = document.querySelectorAll('.nest-menu');
for(let item of items) {
    if(item.textContent.trim().includes('计划工艺')) {
        let a = item.querySelector('a');
        if(a) { a.click(); return 'clicked a'; }
        item.click();
        return 'clicked div';
    }
}
return 'not found';
""")
time.sleep(2)
print(f"URL after click: {p.url[:80]}")

# Check URL hash
hash_val = p.run_js("return window.location.hash")
print(f"Hash: {hash_val}")

# Check page title/content
content = p.run_js("return document.body.innerText.substring(0, 500)")
print(f"Body: {content[:300]}")

# Try ALL possible routes
routes = [
    '#/process/plan', '#/processPlan', '#/plan/process', '#/plan',
    '#/planning/process', '#/process_plan', '#/production/process',
    '#/planProcess', '#/Plan/ProcessPlan', '/Plan/ProcessPlan'
]
for route in routes:
    p.run_js(f"window.location.hash = '{route}'")
    time.sleep(1.5)
    title = p.run_js("return document.title")
    body_preview = p.run_js("return document.body.innerText.substring(0, 100)")
    print(f"  Route {route}: {body_preview[:60]}")

p.quit()
