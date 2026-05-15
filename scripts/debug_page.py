#!/usr/bin/env python3
"""Debug: 登录后查看页面状态"""
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

# ── Dump full page structure via JS ──
r = p.run_js("""
// Get all visible text
let body = document.body;
let textNodes = [];
let walker = document.createTreeWalker(body, 4, null, false);
let node;
while(node = walker.nextNode()) {
    let t = node.textContent.trim();
    if(t && t.length > 0 && t.length < 50) textNodes.push(t);
}
// Deduplicate but keep order
let seen = new Set();
return textNodes.filter(t => { if(seen.has(t)) return false; seen.add(t); return true; }).join('\\n');
""")
print("=== ALL VISIBLE TEXT ===")
print(r[:2000])

# ── Sidebar structure ──
r2 = p.run_js("""
let sidebar = document.querySelector('.el-menu') || document.querySelector('[class*=sidebar]') || document.querySelector('[class*=side]');
if(!sidebar) return 'No sidebar found';

// Get all li items in sidebar
let items = sidebar.querySelectorAll('li');
let result = [];
items.forEach(li => {
    let div = li.querySelector('.menu-wrapper');
    if(div) {
        let txt = div.textContent.trim();
        let isSub = div.classList.contains('nest-menu');
        let expanded = li.classList.contains('is-opened');
        result.push({text: txt.substring(0,30), isSub, expanded});
    }
});
return JSON.stringify(result);
""")
print("\n=== SIDEBAR ===")
print(r2)

# ── After clicking 计划管理, check submenu ──
print("\n=== CLICKING 计划管理 ===")
p.run_js("""
let items = document.querySelectorAll('.menu-wrapper');
for(let item of items) {
    if(item.textContent.trim() === '计划管理' && !item.classList.contains('nest-menu')) {
        item.click();
        return 'clicked';
    }
}
return 'not found';
""")
time.sleep(1.5)

r3 = p.run_js("""
let items = document.querySelectorAll('.el-menu--inline .menu-wrapper');
let result = [];
items.forEach(item => {
    result.push(item.textContent.trim().substring(0,30));
});
return JSON.stringify(result);
""")
print("Submenu items:", r3)

# ── Navigate via URL directly ──
print("\n=== DIRECT URL NAVIGATION ===")
# Try the Plan/ProcessPlan route
p.run_js("window.location.hash = '#/plan/process'")
time.sleep(2)
print(f"URL after hash change: {p.url[:80]}")
print(f"Title: {p.title}")

# Check page content
r4 = p.run_js("""
let body = document.body.innerText;
// Find all unique lines
let lines = body.split('\\n').map(l => l.trim()).filter(l => l.length > 0 && l.length < 80);
return [...new Set(lines)].join('\\n');
""")
print("\n=== PAGE AFTER NAV ===")
print(r4[:2000])

p.quit()
