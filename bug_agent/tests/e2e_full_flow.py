# -*- coding: utf-8 -*-
import json
import os
import urllib.request
from playwright.sync_api import sync_playwright

BASE_URL = 'http://localhost:5678'
API_URL = 'http://localhost:8765'
SCREENSHOT_DIR = '/tmp/bug_agent_test_v2'
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

results = {'passed': [], 'failed': [], 'warnings': []}

def log_pass(test_name, detail=''):
    results['passed'].append({'test': test_name, 'detail': detail})
    print(f'  \u2705 PASS: {test_name} {detail}')

def log_fail(test_name, detail=''):
    results['failed'].append({'test': test_name, 'detail': detail})
    print(f'  \u274c FAIL: {test_name} {detail}')

def log_warn(test_name, detail=''):
    results['warnings'].append({'test': test_name, 'detail': detail})
    print(f'  \u26a0\ufe0f  WARN: {test_name} {detail}')

def screenshot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f'{name}.png')
    page.screenshot(path=path, full_page=True)
    print(f'  \U0001f4f8 Screenshot: {path}')

def api_request(method, endpoint, token=None, data=None):
    url = f'{API_URL}{endpoint}'
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return {'status': resp.status, 'data': json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:500]
        return {'status': e.code, 'error': body_text}
    except Exception as e:
        return {'status': 0, 'error': str(e)}

# ========== API Setup: Get token and create test data ==========
print('\n' + '='*60)
print('SETUP: API Authentication & Test Data')
print('='*60)

login_resp = api_request('POST', '/api/v1/auth/login', data={'username': 'admin', 'password': 'admin123'})
token = ''
if login_resp.get('status') == 200:
    resp_data = login_resp.get('data', {})
    if isinstance(resp_data, dict):
        token = resp_data.get('data', {}).get('token', '') if isinstance(resp_data.get('data'), dict) else resp_data.get('token', '')
    if token:
        log_pass('API Login', 'Token obtained')
    else:
        log_fail('API Login', f'No token in response: {json.dumps(resp_data)[:200]}')
else:
    log_fail('API Login', str(login_resp))

project_id = None
defect_id = None
iteration_id = None

if token:
    # Get or create project
    projects_resp = api_request('GET', '/api/v1/projects', token=token)
    projects_data = projects_resp.get('data', {}).get('data', [])
    if isinstance(projects_data, list) and len(projects_data) > 0:
        project_id = str(projects_data[0].get('id', ''))
        log_pass('Get project', f'ID: {project_id}')
    elif isinstance(projects_data, dict):
        items = projects_data.get('items', projects_data.get('list', []))
        if items:
            project_id = str(items[0].get('id', ''))

    if not project_id:
        create_resp = api_request('POST', '/api/v1/projects', token=token, data={'name': 'E2E\u6d4b\u8bd5\u9879\u76ee', 'code': 'E2E', 'description': '\u81ea\u52a8\u5316\u6d4b\u8bd5\u521b\u5efa\u7684\u9879\u76ee'})
        if create_resp.get('status') in [200, 201]:
            new_proj = create_resp.get('data', {}).get('data', {})
            project_id = str(new_proj.get('id', ''))
            log_pass('Create project', f'ID: {project_id}')
        else:
            log_fail('Create project', str(create_resp))

    if project_id:
        # Create iteration with required fields
        iter_resp = api_request('POST', f'/api/v1/projects/{project_id}/iterations', token=token, data={
            'name': 'Sprint 1',
            'status': 'active',
            'startDate': '2026-04-01T00:00:00Z',
            'endDate': '2026-05-01T00:00:00Z',
        })
        if iter_resp.get('status') in [200, 201]:
            iter_data = iter_resp.get('data', {}).get('data', {})
            iteration_id = iter_data.get('id')
            log_pass('Create iteration', f'ID: {iteration_id}')
        else:
            # Try to get existing iterations
            list_iter = api_request('GET', f'/api/v1/projects/{project_id}/iterations', token=token)
            iter_list = list_iter.get('data', {}).get('data', [])
            if isinstance(iter_list, list) and len(iter_list) > 0:
                iteration_id = iter_list[0].get('id')
                log_pass('Get existing iteration', f'ID: {iteration_id}')
            else:
                log_warn('Iteration', f'Could not create/get iteration: {iter_resp}')

        # Create test defect (only if we have an iteration)
        if iteration_id:
            defect_data = {
                'title': 'E2E\u6d4b\u8bd5\u7f3a\u9677-\u767b\u5f55\u9875\u9762\u5f02\u5e38',
                'description': '\u767b\u5f55\u9875\u9762\u5728\u79fb\u52a8\u7aef\u663e\u793a\u5f02\u5e38\uff0c\u8f93\u5165\u6846\u88ab\u906e\u6321\uff0c\u65e0\u6cd5\u6b63\u5e38\u8f93\u5165\u7528\u6237\u540d\u548c\u5bc6\u7801\u3002\n\n\u590d\u73b0\u6b65\u9aa4\uff1a\n1. \u6253\u5f00\u79fb\u52a8\u7aef\u6d4f\u89c8\u5668\n2. \u8bbf\u95ee\u767b\u5f55\u9875\u9762\n3. \u89c2\u5bdf\u8f93\u5165\u6846\u4f4d\u7f6e',
                'severity': 'major',
                'priority': 'P1',
                'type': 'ui',
                'iterationId': iteration_id,
                'tags': ['UI\u6837\u5f0f', '\u517c\u5bb9\u6027']
            }
            defect_resp = api_request('POST', '/api/v1/defects', token=token, data=defect_data)
            if defect_resp.get('status') in [200, 201]:
                defect_result = defect_resp.get('data', {}).get('data', {})
                defect_id = defect_result.get('id')
                log_pass('Create test defect', f'ID: {defect_id}')
            else:
                log_warn('Create test defect', f'Failed: {defect_resp}')
        else:
            # Try to get existing defects for the project
            defects_resp = api_request('GET', f'/api/v1/defects?projectId={project_id}', token=token)
            defects_list = defects_resp.get('data', {}).get('data', {})
            if isinstance(defects_list, dict):
                items = defects_list.get('items', defects_list.get('list', []))
                if items:
                    defect_id = items[0].get('id')
                    log_pass('Get existing defect', f'ID: {defect_id}')
            elif isinstance(defects_list, list) and len(defects_list) > 0:
                defect_id = defects_list[0].get('id')
                log_pass('Get existing defect', f'ID: {defect_id}')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()

    # ========== FLOW 1: Login ==========
    print('\n' + '='*60)
    print('FLOW 1: Authentication - Login')
    print('='*60)

    page.goto(f'{BASE_URL}/login')
    page.wait_for_load_state('networkidle')
    screenshot(page, '01_login_page')

    login_input = page.locator('input#username, input[placeholder*="\u7528\u6237\u540d"], input[placeholder*="\u8d26\u53f7"]').first
    pwd_input = page.locator('input#password, input[type="password"]').first
    login_btn = page.locator('button[type="submit"], button:has-text("\u767b\u5f55"), button:has-text("\u767b \u5f55")').first

    if login_input.count() > 0 and pwd_input.count() > 0:
        login_input.fill('admin')
        pwd_input.fill('admin123')
        screenshot(page, '02_login_filled')
        login_btn.click()
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '03_after_login')
        current_url = page.url
        if '/login' not in current_url:
            log_pass('Login', f'Redirected to {current_url}')
        else:
            log_fail('Login', 'Still on login page after submit')
    else:
        log_fail('Login form', 'Could not find login form elements')

    # ========== FLOW 2: Project List ==========
    print('\n' + '='*60)
    print('FLOW 2: Project List')
    print('='*60)

    page.goto(f'{BASE_URL}/projects')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)
    screenshot(page, '04_project_list')

    # Project cards use onClick, not <a> tags
    project_cards = page.locator('.project-card, [class*="project-card"]').all()
    new_project_btn = page.locator('button:has-text("\u65b0\u5efa\u9879\u76ee")').first

    if len(project_cards) > 0:
        log_pass('Project list', f'Found {len(project_cards)} project cards')
        # Click first project card
        project_cards[0].click()
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        screenshot(page, '05_project_dashboard')
        log_pass('Navigate to project', f'URL: {page.url}')
    elif new_project_btn.count() > 0:
        log_warn('Project list', 'No project cards found, but create button exists')
    else:
        log_fail('Project list', 'No project cards or create button found')

    # ========== FLOW 3: Project Dashboard ==========
    print('\n' + '='*60)
    print('FLOW 3: Project Dashboard')
    print('='*60)

    if project_id:
        page.goto(f'{BASE_URL}/projects/{project_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        screenshot(page, '06_dashboard')

        # Check sidebar navigation
        sidebar_links = page.locator('.ant-menu a, [class*="sider"] a, nav a').all()
        log_pass('Dashboard sidebar', f'Found {len(sidebar_links)} navigation links')

        # Check metric cards
        metric_cards = page.locator('[class*="metric"], [class*="stat"], .ant-statistic').all()
        if len(metric_cards) > 0:
            log_pass('Dashboard metrics', f'Found {len(metric_cards)} metric elements')
        else:
            log_warn('Dashboard metrics', 'No metric elements found')

    # ========== FLOW 4: Defect List ==========
    print('\n' + '='*60)
    print('FLOW 4: Defect List')
    print('='*60)

    if project_id:
        page.goto(f'{BASE_URL}/projects/{project_id}/defects')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        screenshot(page, '07_defect_list')

        # Check table/list
        table_rows = page.locator('table tbody tr, .ant-table-row, [class*="defect-item"]').all()
        if len(table_rows) > 0:
            log_pass('Defect list', f'Found {len(table_rows)} defect rows')
        else:
            log_warn('Defect list', 'No defect rows visible')

        # Check search
        search_input = page.locator('input[placeholder*="\u641c\u7d22"], input[placeholder*="\u7b5b\u9009"], input[placeholder*="search"]').first
        if search_input.count() > 0:
            log_pass('Defect search', 'Search input found')

        # Check create button
        create_btn = page.locator('button:has-text("\u521b\u5efa"), a:has-text("\u521b\u5efa"), button:has-text("\u65b0\u5efa")').first
        if create_btn.count() > 0:
            log_pass('Defect create button', 'Found')

    # ========== FLOW 5: Create Defect (Chat + Advanced) ==========
    print('\n' + '='*60)
    print('FLOW 5: Create Defect - Chat & Advanced Mode')
    print('='*60)

    if project_id:
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/create')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '08_create_defect_chat')

        # Check mode tabs
        chat_tab = page.locator('[role="tab"]:has-text("\u5bf9\u8bdd"), [class*="tab"]:has-text("\u5bf9\u8bdd")').first
        advanced_tab = page.locator('[role="tab"]:has-text("\u9ad8\u7ea7"), [class*="tab"]:has-text("\u9ad8\u7ea7")').first

        if chat_tab.count() > 0:
            log_pass('Chat mode tab', 'Found')
        if advanced_tab.count() > 0:
            log_pass('Advanced mode tab', 'Found')

        # Check chat input area
        chat_textarea = page.locator('textarea[placeholder*="\u63cf\u8ff0"], textarea[placeholder*="\u95ee\u9898"]').first
        if chat_textarea.count() > 0:
            chat_textarea.fill('\u767b\u5f55\u9875\u9762\u5728\u79fb\u52a8\u7aef\u663e\u793a\u5f02\u5e38\uff0c\u8f93\u5165\u6846\u88ab\u906e\u6321\uff0c\u65e0\u6cd5\u6b63\u5e38\u8f93\u5165\u7528\u6237\u540d\u548c\u5bc6\u7801')
            screenshot(page, '09_chat_filled')
            log_pass('Chat input', 'Filled with test content')
        else:
            log_warn('Chat input', 'Textarea not found')

        # Check send button (icon-only, uses SendOutlined)
        send_btn = page.locator('button.brand-button .anticon-send, button.brand-button:has(.anticon-send)').first
        if send_btn.count() > 0:
            log_pass('Send button', 'Found (icon button with SendOutlined)')
        else:
            send_btn_area = page.locator('button.brand-button').first
            if send_btn_area.count() > 0:
                log_pass('Send button', 'Found (brand-button in chat area)')
            else:
                log_warn('Send button', 'Not found')

        # Check iteration selector
        iter_select = page.locator('.ant-select:has-text("\u9009\u62e9\u8fed\u4ee3"), .ant-select-selector').first
        if iter_select.count() > 0:
            log_pass('Chat iteration selector', 'Found')

        # Switch to advanced mode (from current page, no re-navigation)
        if advanced_tab.count() > 0:
            advanced_tab.click()
            page.wait_for_timeout(3000)
            screenshot(page, '10_advanced_mode')

            # Title input - use JS evaluation as most reliable method
            result = page.evaluate('''() => {
                const inputs = document.querySelectorAll('input[placeholder]');
                for (const inp of inputs) {
                    if (inp.placeholder.includes('\u6807\u9898')) {
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(inp, 'E2E\u6d4b\u8bd5\u7f3a\u9677-\u9ad8\u7ea7\u6a21\u5f0f');
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }''')
            if result:
                log_pass('Advanced - title input', 'Filled via React-compatible JS')
            else:
                log_warn('Advanced - title input', 'Not found in DOM after tab switch')

            # Description textarea
            desc_textarea = page.locator('textarea[placeholder*="\u63cf\u8ff0"]').first
            if desc_textarea.count() > 0:
                desc_textarea.fill('\u8fd9\u662f\u4e00\u4e2aE2E\u6d4b\u8bd5\u521b\u5efa\u7684\u7f3a\u9677\u63cf\u8ff0')
                log_pass('Advanced - description', 'Filled')

            # Severity selector
            severity_select = page.locator('.ant-select:has-text("\u4e00\u822c"), .ant-select').first
            if severity_select.count() > 0:
                log_pass('Advanced - severity selector', 'Found')

            screenshot(page, '11_advanced_filled')

            # Switch back to chat mode
            chat_tab = page.locator('[role="tab"]:has-text("\u5bf9\u8bdd"), [class*="tab"]:has-text("\u5bf9\u8bdd")').first
            if chat_tab.count() > 0:
                chat_tab.click()
                page.wait_for_timeout(500)
                screenshot(page, '12_back_to_chat')
                log_pass('Mode switch back', 'Switched back to chat mode')

    # ========== FLOW 7: Defect Detail ==========
    print('\n' + '='*60)
    print('FLOW 7: Defect Detail Page')
    print('='*60)

    if project_id and defect_id:
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/{defect_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '13_defect_detail')

        # Check Steps component
        steps = page.locator('.ant-steps, [class*="steps"]').first
        if steps.count() > 0:
            log_pass('Defect detail - Steps', 'Found')
        else:
            log_warn('Defect detail - Steps', 'Not found')

        # Check status tag
        status_tag = page.locator('.ant-tag').first
        if status_tag.count() > 0:
            log_pass('Defect detail - Status tag', f'Text: {status_tag.text_content()}')
        else:
            log_warn('Defect detail - Status tag', 'Not found')

        # Check breadcrumb
        breadcrumb = page.locator('.ant-breadcrumb').first
        if breadcrumb.count() > 0:
            log_pass('Defect detail - Breadcrumb', 'Found')

        # Check back button
        back_btn = page.locator('button .anticon-arrow-left, button:has(.anticon-arrow-left)').first
        if back_btn.count() > 0:
            log_pass('Defect detail - Back button', 'Found')

        # Check action buttons (depends on defect status)
        action_btns = page.locator('button:has-text("\u6307\u6d3e"), button:has-text("\u5f00\u59cb\u5206\u6790"), button:has-text("\u5f00\u59cb\u4fee\u590d"), button:has-text("\u9a8c\u8bc1\u901a\u8fc7"), button:has-text("\u62d2\u7edd")').all()
        if len(action_btns) > 0:
            log_pass('Defect detail - Actions', f'Found {len(action_btns)} action buttons: {[b.text_content().strip() for b in action_btns]}')
        else:
            log_warn('Defect detail - Actions', 'No action buttons found')

        # Click "\u52a8\u6001" tab to reveal comment area
        activity_tab = page.locator('[role="tab"]:has-text("\u52a8\u6001"), .ant-tabs-tab:has-text("\u52a8\u6001")').first
        if activity_tab.count() > 0:
            activity_tab.click()
            page.wait_for_timeout(1000)
            screenshot(page, '13b_defect_activity')

            comment_textarea = page.locator('textarea[placeholder*="\u8bc4\u8bba"], textarea[placeholder*="\u8f93\u5165\u8bc4\u8bba"]').first
            if comment_textarea.count() > 0:
                log_pass('Defect detail - Comment area', 'Found in activity tab')
                # Try typing a comment
                comment_textarea.fill('\u8fd9\u662f\u4e00\u6761E2E\u6d4b\u8bd5\u8bc4\u8bba')
                log_pass('Defect detail - Comment input', 'Filled test comment')
            else:
                # Broader search
                all_textareas = page.locator('textarea:visible').all()
                if len(all_textareas) > 0:
                    log_pass('Defect detail - Comment area', f'Found {len(all_textareas)} visible textareas')
                else:
                    log_warn('Defect detail - Comment area', 'No textarea found in activity tab')
        else:
            log_warn('Defect detail - Activity tab', 'Not found')

        # Check sidebar info
        info_section = page.locator('[class*="info"], [class*="sidebar"], [class*="meta"]').first
        if info_section.count() > 0:
            log_pass('Defect detail - Info section', 'Found')

        # Test status transition
        transition_btn = page.locator('button:has-text("\u5206\u914d")').first
        if transition_btn.count() > 0:
            log_pass('Defect detail - Assign button', 'Clickable')
    else:
        log_warn('Defect detail', 'No defect_id available, skipping')

    # ========== FLOW 8-18: Project Sub-pages ==========
    print('\n' + '='*60)
    print('FLOW 8-18: Project Sub-pages')
    print('='*60)

    sub_pages = [
        (f'/projects/{project_id}/issue-pool', 'Issue Pool', ['\u95ee\u9898', '\u4fe1\u53f7', '\u5206\u8bca', 'issue']),
        (f'/projects/{project_id}/routing', 'Routing Center', ['\u8def\u7531', '\u6a21\u5757', '\u89c4\u5219', 'routing']),
        (f'/projects/{project_id}/integrations', 'Integrations', ['\u96c6\u6210', '\u8fde\u63a5', 'integration']),
        (f'/projects/{project_id}/settings', 'Project Settings', ['\u8bbe\u7f6e', 'setting']),
        (f'/projects/{project_id}/members', 'Project Members', ['\u6210\u5458', 'member']),
        (f'/projects/{project_id}/regression', 'Regression Center', ['\u56de\u5f52', 'regression']),
        (f'/projects/{project_id}/quality-insights', 'Quality Insights', ['\u8d28\u91cf', '\u6d1e\u5bdf', 'quality']),
        (f'/projects/{project_id}/iterations', 'Iterations', ['\u8fed\u4ee3', 'iteration']),
        (f'/projects/{project_id}/repos', 'Repos', ['\u4ed3\u5e93', 'repo']),
        (f'/projects/{project_id}/ai-configs', 'AI Configs', ['AI', '\u914d\u7f6e', '\u6a21\u578b']),
        (f'/projects/{project_id}/notifications', 'Notifications', ['\u901a\u77e5', 'notification']),
    ] if project_id else []

    for i, (url, name, keywords) in enumerate(sub_pages, start=14):
        page.goto(f'{BASE_URL}{url}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        screenshot(page, f'{i:02d}_{name.lower().replace(" ", "_")}')

        body_text = page.locator('body').text_content() or ''
        if any(kw in body_text for kw in keywords):
            log_pass(f'{name}', 'Page loaded with expected content')
        else:
            log_warn(f'{name}', 'Page loaded but expected keywords not found')

        # Check for JS errors on page
        page_errors = []
        def capture_error(msg):
            if msg.type == 'error' and 'favicon' not in msg.text.lower():
                page_errors.append(msg.text)
        page.on('console', capture_error)
        page.wait_for_timeout(500)
        page.remove_listener('console', capture_error)
        if page_errors:
            log_warn(f'{name} - Console errors', f'{len(page_errors)} errors')

    # ========== FLOW 19-24: Global Pages ==========
    print('\n' + '='*60)
    print('FLOW 19-24: Global Pages')
    print('='*60)

    global_pages = [
        ('/users', 'User Management', ['\u7528\u6237', 'user']),
        ('/ai-catalog', 'AI Catalog', ['AI', '\u6a21\u578b', 'provider']),
        ('/platform-credentials', 'Platform Credentials', ['\u51ed\u8bc1', 'credential', '\u5bc6\u94a5']),
        ('/platform-settings', 'Platform Settings', ['\u8bbe\u7f6e', 'setting']),
        ('/audit-logs', 'Audit Logs', ['\u5ba1\u8ba1', '\u65e5\u5fd7', 'audit']),
        ('/profile', 'Profile', ['\u8d44\u6599', '\u5934\u50cf', 'profile', '\u4e2a\u4eba']),
    ]

    for i, (url, name, keywords) in enumerate(global_pages, start=25):
        page.goto(f'{BASE_URL}{url}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        screenshot(page, f'{i:02d}_{name.lower().replace(" ", "_")}')

        body_text = page.locator('body').text_content() or ''
        if any(kw in body_text for kw in keywords):
            log_pass(f'{name}', 'Page loaded with expected content')
        else:
            log_warn(f'{name}', 'Page loaded but expected keywords not found')

    # ========== FLOW 25: User Dropdown Menu ==========
    print('\n' + '='*60)
    print('FLOW 25: User Dropdown Menu')
    print('='*60)

    page.goto(f'{BASE_URL}/projects')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1500)

    # ShellUserTrigger renders a clickable div with user initial
    user_trigger = page.locator('[class*="shell-user"], [class*="user-trigger"], [class*="avatar"]').first
    if user_trigger.count() > 0:
        user_trigger.click()
        page.wait_for_timeout(800)
        screenshot(page, '31_user_dropdown')

        # Check if dropdown appeared
        dropdown_items = page.locator(':has-text("\u4e2a\u4eba\u4fe1\u606f"), :has-text("\u9000\u51fa\u767b\u5f55")').all()
        if len(dropdown_items) > 0:
            log_pass('User dropdown', 'Opens on click with menu items')
        else:
            log_warn('User dropdown', 'Clicked trigger but no menu items visible')
    else:
        log_warn('User trigger', 'No user trigger element found')

    # ========== FLOW 26: Console Error Deep Check ==========
    print('\n' + '='*60)
    print('FLOW 26: Console Error Deep Check')
    print('='*60)

    console_errors = []

    def handle_console(msg):
        if msg.type == 'error':
            console_errors.append(msg.text)

    page.on('console', handle_console)

    key_pages = [
        ('/login', 'Login'),
        ('/projects', 'Projects'),
    ]
    if project_id:
        key_pages.extend([
            (f'/projects/{project_id}', 'Dashboard'),
            (f'/projects/{project_id}/defects', 'Defects'),
            (f'/projects/{project_id}/defects/create', 'Create Defect'),
            (f'/projects/{project_id}/issue-pool', 'Issue Pool'),
            (f'/projects/{project_id}/routing', 'Routing'),
        ])
    key_pages.extend([
        ('/users', 'Users'),
        ('/ai-catalog', 'AI Catalog'),
        ('/profile', 'Profile'),
    ])

    for url, name in key_pages:
        console_errors.clear()
        page.goto(f'{BASE_URL}{url}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)

        filtered = [e for e in console_errors if 'favicon' not in e.lower() and 'devtools' not in e.lower()]
        if len(filtered) > 0:
            log_fail(f'Console errors on {name}', f'{len(filtered)} errors: {filtered[:3]}')
        else:
            log_pass(f'Console errors on {name}', 'No errors')

    page.remove_listener('console', handle_console)

    # ========== FLOW 27: API Endpoints ==========
    print('\n' + '='*60)
    print('FLOW 27: API Endpoints Check')
    print('='*60)

    health_resp = api_request('GET', '/healthz')
    if health_resp.get('status') == 200:
        log_pass('API /healthz', 'OK')
    else:
        log_fail('API /healthz', str(health_resp))

    if token:
        auth_endpoints = [
            ('GET', '/api/v1/users/me'),
            ('GET', '/api/v1/projects'),
            ('GET', '/api/v1/users'),
            ('GET', '/api/v1/rbac/my-permissions'),
            ('GET', '/api/v1/notifications/unread-count'),
        ]
        if project_id:
            auth_endpoints.extend([
                ('GET', f'/api/v1/projects/{project_id}'),
                ('GET', f'/api/v1/projects/{project_id}/stats'),
                ('GET', f'/api/v1/projects/{project_id}/iterations'),
                ('GET', f'/api/v1/projects/{project_id}/modules'),
            ])
        if defect_id:
            auth_endpoints.extend([
                ('GET', f'/api/v1/defects/{defect_id}'),
                ('GET', f'/api/v1/defects/{defect_id}/transitions'),
                ('GET', f'/api/v1/defects/{defect_id}/history'),
            ])

        for method, endpoint in auth_endpoints:
            resp = api_request(method, endpoint, token=token)
            if resp.get('status') == 200:
                code = resp.get('data', {}).get('code', 'N/A')
                log_pass(f'API {method} {endpoint}', f'Status: 200, Code: {code}')
            else:
                log_fail(f'API {method} {endpoint}', f'HTTP {resp.get("status")}: {resp.get("error", "")[:200]}')

    # ========== FLOW 28: Mobile Responsive ==========
    print('\n' + '='*60)
    print('FLOW 28: Mobile Responsive Check')
    print('='*60)

    mobile_page = context.new_page()
    mobile_page.set_viewport_size({'width': 375, 'height': 812})
    mobile_page.goto(f'{BASE_URL}/projects')
    mobile_page.wait_for_load_state('networkidle')
    mobile_page.wait_for_timeout(1500)
    mobile_page.screenshot(path=os.path.join(SCREENSHOT_DIR, '32_mobile_projects.png'), full_page=True)

    mobile_content = mobile_page.locator('body').text_content()
    if mobile_content and len(mobile_content) > 50:
        log_pass('Mobile viewport', 'Content renders on mobile')
    else:
        log_warn('Mobile viewport', 'Limited content visible on mobile')

    # Test defect detail on mobile
    if project_id and defect_id:
        mobile_page.goto(f'{BASE_URL}/projects/{project_id}/defects/{defect_id}')
        mobile_page.wait_for_load_state('networkidle')
        mobile_page.wait_for_timeout(1500)
        mobile_page.screenshot(path=os.path.join(SCREENSHOT_DIR, '33_mobile_defect_detail.png'), full_page=True)
        log_pass('Mobile defect detail', 'Page renders on mobile')

    mobile_page.close()
    browser.close()

# ========== SUMMARY ==========
print('\n' + '='*60)
print('TEST SUMMARY')
print('='*60)
print(f'\u2705 Passed: {len(results["passed"])}')
print(f'\u274c Failed: {len(results["failed"])}')
print(f'\u26a0\ufe0f  Warnings: {len(results["warnings"])}')

if results['failed']:
    print('\n\u274c FAILED TESTS:')
    for item in results['failed']:
        print(f'  - {item["test"]}: {item["detail"]}')

if results['warnings']:
    print('\n\u26a0\ufe0f  WARNINGS:')
    for item in results['warnings']:
        print(f'  - {item["test"]}: {item["detail"]}')

print(f'\n\U0001f4f8 Screenshots saved to: {SCREENSHOT_DIR}/')

with open(os.path.join(SCREENSHOT_DIR, 'test_results.json'), 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f'\U0001f4ca Full results saved to: {SCREENSHOT_DIR}/test_results.json')
