#!/usr/bin/env python3
"""Debug: 计划工艺页面的搜索区域"""
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

# Get the full HTML of the main content section after the header tabs
html = p.run_js("""
let main = document.querySelector('.app-main') || document.querySelector('.el-main-layout');
if(!main) return document.body.innerHTML.substring(0, 5000);

// Skip the sidebar
let content = main.innerHTML;
return content.substring(0, 8000);
""")
print("=== FULL CONTENT HTML ===")
print(html)

p.quit()
