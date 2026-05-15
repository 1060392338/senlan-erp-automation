#!/usr/bin/env python3
"""登录ERP → 计划工艺 → 搜索生产单 → 工艺管理"""
import time, sys, json
sys.path.insert(0, '.')
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_user_data_path('/tmp/senlan_chrome_472')
co.set_argument('--remote-allow-origins=*')
co.set_argument('--no-sandbox')
co.set_argument('--window-size=1920,1080')
co.set_timeouts(base=8, page_load=10, script=5)
p = ChromiumPage(co)

def wait(n=1.5):
    time.sleep(n)

# ── Step 1: Login ──
print("=== 登录 ===")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
wait(3)
print(f"Title: {p.title} | URL: {p.url}")

# ── Step 2: Navigate to 计划工艺 via menu click ──
print("\n=== 导航到计划工艺 ===")

# Find and click "计划管理" parent menu  
# It should be a div.menu-wrapper that contains text "计划管理"
# First click the parent to expand sub-menu
menu_items = p.eles('.menu-wrapper')
plan_mgmt = None
for item in menu_items:
    txt = item.text.strip()
    if txt == '计划管理':
        plan_mgmt = item
        break

if plan_mgmt:
    print(f"找到计划管理: {plan_mgmt}")
    # Click to expand
    plan_mgmt.click()
    wait(2)
    print("已点击计划管理")
else:
    # Try to find by text
    try:
        plan_mgmt = p.ele('@@class=menu-wrapper@@text()=计划管理')
        plan_mgmt.click()
        wait(2)
        print("已点击计划管理 (via text find)")
    except Exception as e:
        print(f"找不到计划管理: {e}")

# Now find 计划工艺 submenu
try:
    process_plan = p.ele('@@class=menu-wrapper nest-menu@@text()=计划工艺')
    print(f"找到计划工艺: {process_plan}")
    process_plan.click()
    wait(2)
    print(f"导航后URL: {p.url}")
except Exception as e:
    print(f"找不到计划工艺: {e}")
    # Try to navigate via URL
    p.get('http://112.74.35.30/#/plan/process')
    # p.get('http://112.74.35.30/Plan/ProcessPlan')
    wait(3)
    print(f"Fallback URL: {p.url}")

# ── Step 3: Search for production order ──
print("\n=== 搜索生产单号 ===")

# Look for search input
try:
    search_input = p.ele('@placeholder=搜索') or p.ele('@placeholder=请输入') or p.ele('@placeholder=生产单号') or p.ele('@class*=el-input__inner')
    search_input_html = search_input.html
    print(f"Search input found")
    search_input.input('W20126051401')
    wait(1)
    # Press Enter to search
    p.run_js("arguments[0].dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13}))", search_input)
    wait(3)
    print("已搜索W20126051401")
except Exception as e:
    print(f"搜索框操作失败: {e}")
    # Dump inputs
    for inp in p.eles('tag:input'):
        plc = inp.attr('placeholder') or ''
        name = inp.attr('name') or ''
        cls = inp.attr('class') or ''
        if plc or name:
            print(f"  input: placeholder='{plc}' name='{name}' class='{cls[:30]}'")

# ── Step 4: Check results and try to find 工艺管理 button ──
wait(2)
try:
    page_text = p.html
    
    if 'W20126051401' in page_text:
        print("✓ 生产单W20126051401存在!")
    else:
        print("✗ 生产单W20126051401未找到")
    
    # Find 工艺管理 button
    for tag in ['button','span','div','a']:
        els = p.eles(f'tag:{tag}')
        for el in els:
            txt = el.text.strip()
            if '工艺' in txt or '管理' in txt:
                print(f"  可能按钮: <{tag}> text='{txt}' class='{el.attr('class') or ''}'")
    
    # Also dump table data
    tables = p.eles('tag:table')
    print(f"\n表格数: {len(tables)}")
    
except Exception as e:
    print(f"检查页面失败: {e}")

p.quit()
print("\nDONE")
