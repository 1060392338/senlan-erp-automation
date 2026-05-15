#!/usr/bin/env python3
"""登录并获取ERP菜单结构"""
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

# Menu structure - find all a tags with their DOM hierarchy
seen = set()
a_els = p.eles('tag:a')
for a in a_els:
    t = a.text.strip()
    if t and len(t) > 1 and t not in seen:
        seen.add(t)
        try:
            parent = a.parent()
            parent_tag = parent.tag if parent else '?'
            parent_cls = parent.attr('class') or ''
            grandparent = parent.parent()
            gp_tag = grandparent.tag if grandparent else '?'
            gp_cls = grandparent.attr('class') or ''
            print(f'|{t}| p=<{parent_tag}> pc="{parent_cls[:30]}" gp=<{gp_tag}> gpc="{gp_cls[:30]}"')
        except:
            print(f'|{t}| (error getting parents)')

p.quit()
print("DONE")
