#!/usr/bin/env python3
"""获取完整菜单层次结构"""
import time, sys
sys.path.insert(0, '.')
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_user_data_path('/tmp/senlan_chrome_472')
co.set_argument('--remote-allow-origins=*')
co.set_argument('--no-sandbox')
co.set_argument('--window-size=1920,1080')
co.set_timeouts(base=8, page_load=10, script=5)
p = ChromiumPage(co)

p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)

# Find all inline menus (sub-menus) and their parent list items
# Structure: ul.el-menu > li > div.menu-wrapper (parent) 
#          : ul.el-menu--inline > li > div.menu-wrapper.nest-menu > a (child)

# First, find all top-level menu items (that are NOT nest-menu)
top_menus = p.eles('.menu-wrapper')
for m in top_menus:
    cls = m.attr('class') or ''
    txt = m.text.strip()
    if txt:
        is_nest = 'nest-menu' in cls
        marker = '  ' if is_nest else '*'
        print(f'{marker} {txt} | class={cls[:40]}')

p.quit()
print("DONE")
