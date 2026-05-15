#!/usr/bin/env python3
"""直接登录+识别菜单"""
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

print("=== ALL VISIBLE TEXT ===")
all_els = p.eles('tag:*')
texts = set()
for el in all_els:
    txt = el.text.strip()
    if txt and len(txt) >= 2 and len(txt) <= 30 and txt not in texts:
        texts.add(txt)
        print(txt)

print("\n=== ALL LINKS ===")
for a in p.eles('tag:a'):
    txt = a.text.strip()
    href = a.attr('href') or ''
    if txt:
        print(f'  "{txt}" -> {href[:80]}')

print("\n=== SIDEBAR CHECK ===")
# Check for sidebar
for tag in ['div', 'aside', 'ul', 'nav']:
    els = p.eles(f'tag:{tag}')
    for el in els:
        cls = el.attr('class') or ''
        if any(k in cls for k in ['side', 'menu', 'nav', 'left', 'sidebar', 'layout']):
            txt = el.text.strip()[:100]
            print(f'  <{tag}> class={cls}: "{txt}"')

p.quit()
