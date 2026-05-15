#!/usr/bin/env python3
"""探索森蓝ERP页面结构"""
import sys, time, json, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DrissionPage import ChromiumPage, ChromiumOptions

USER_DATA_DIR = '/tmp/senlan_chrome_472'
ERP_URL = 'http://112.74.35.30/'
USERNAME = '472'
PASSWORD = '123456'

co = ChromiumOptions()
co.set_user_data_path(USER_DATA_DIR)
co.set_argument('--remote-allow-origins=*')
co.set_argument('--no-sandbox')
co.set_argument('--disable-gpu')
co.set_argument('--window-size=1920,1080')
co.set_timeouts(base=10, page_load=15, script=10)

page = ChromiumPage(co)

def explore_page(label):
    print(f"\n=== {label} ===")
    print(f"  URL: {page.url}")
    print(f"  Title: {page.title}")
    try:
        # Dump all interactive elements
        for tag in ['button','input','select','textarea','a']:
            els = page.eles(f'tag:{tag}')
            for el in els:
                txt = el.text.strip()[:60] if el.text else ''
                name = el.attr('name') or ''
                pid = el.attr('id') or ''
                cls = el.attr('class') or ''
                href = el.attr('href') or ''
                if txt or name or pid or href:
                    print(f"  <{tag}> text='{txt}' name='{name}' id='{pid}' class='{cls[:40]}' href='{href[:60]}'")
    except Exception as e:
        print(f"  Error: {e}")

# Step 1: Load ERP
try:
    page.get(ERP_URL, timeout=15)
    time.sleep(2)
except Exception as e:
    print(f"Load error: {e}")

explore_page("ERP首页")

# Step 2: Login if needed
if 'Login' in page.url or 'login' in page.url.lower() or '登' in page.title:
    print("\n=== 检测到登录页，尝试登录 ===")
    # Try to find form fields
    username = page.ele('@name=UserName') or page.ele('@name=username') or page.ele('@name=txtUserName') or page.ele('@id=UserName')
    password = page.ele('@name=Password') or page.ele('@name=password') or page.ele('@name=txtPassword') or page.ele('@id=Password')
    login_btn = page.ele('t:button') or page.ele('@value=登 陆') or page.ele('@value=登录')
    
    # If specific selectors didn't work, find first text+password inputs
    if not username:
        inputs = page.eles('tag:input')
        text_inputs = [i for i in inputs if i.attr('type') in (None, 'text', '')]
        pwd_inputs = [i for i in inputs if i.attr('type') == 'password']
        if text_inputs and pwd_inputs:
            username = text_inputs[0]
            password = pwd_inputs[0]
    
    print(f"  username: {username}")
    print(f"  password: {password}")
    print(f"  login_btn: {login_btn}")
    
    if username and password:
        username.input(USERNAME)
        time.sleep(0.3)
        password.input(PASSWORD)
        time.sleep(0.3)
        
        if login_btn:
            page.run_js("arguments[0].click()", login_btn)
        else:
            page.run_js("document.querySelector('form')?.requestSubmit()")
        
        time.sleep(3)
        explore_page("登录后")
    else:
        print("  Cannot find login fields, dumping form...")
        forms = page.eles('tag:form')
        print(f"  Forms: {len(forms)}")
        for f in forms:
            print(f"    Form HTML (first 300): {f.html[:300]}")

# Step 3: Navigate to ProcessPlan if logged in
if 'dashboard' in page.url or '首页' in page.title or page.title != '登录':
    print("\n=== 尝试导航到计划工艺 ===")
    # Try direct URL
    try:
        page.get(f'{ERP_URL.rstrip("/")}/#/plan/process', timeout=10)
        time.sleep(2)
        explore_page("计划工艺 (hash)")
    except:
        pass
    
    try:
        page.get(f'{ERP_URL.rstrip("/")}/Plan/ProcessPlan', timeout=10)
        time.sleep(2)
        explore_page("计划工艺 (direct)")
    except:
        pass

page.quit()
print("\nDONE")
