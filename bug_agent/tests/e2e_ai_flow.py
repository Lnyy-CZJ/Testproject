# -*- coding: utf-8 -*-
import json
import os
import time
import urllib.request
from playwright.sync_api import sync_playwright

BASE_URL = 'http://localhost:5678'
API_URL = 'http://localhost:8765'
SCREENSHOT_DIR = '/tmp/bug_agent_ai_flow'
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

def api_request(method, endpoint, token=None, data=None, timeout=30):
    url = f'{API_URL}{endpoint}'
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {'status': resp.status, 'data': json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:500]
        try:
            parsed = json.loads(body_text)
        except:
            parsed = body_text
        return {'status': e.code, 'error': parsed}
    except Exception as e:
        return {'status': 0, 'error': str(e)}

# ========== SETUP ==========
print('\n' + '='*60)
print('SETUP: Authentication & Test Data')
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
        log_fail('API Login', f'No token: {json.dumps(resp_data)[:200]}')
else:
    log_fail('API Login', str(login_resp))

project_id = None
project_code = None

if token:
    projects_resp = api_request('GET', '/api/v1/projects', token=token)
    projects_data = projects_resp.get('data', {}).get('data', [])
    if isinstance(projects_data, list) and len(projects_data) > 0:
        project_id = str(projects_data[0].get('id', ''))
        project_code = projects_data[0].get('code', '')
        log_pass('Get project', f'ID: {project_id}, Code: {project_code}')
    elif isinstance(projects_data, dict):
        items = projects_data.get('items', projects_data.get('list', []))
        if items:
            project_id = str(items[0].get('id', ''))
            project_code = items[0].get('code', '')
            log_pass('Get project', f'ID: {project_id}, Code: {project_code}')

    if not project_id:
        create_resp = api_request('POST', '/api/v1/projects', token=token, data={
            'name': 'AI\u6d41\u7a0b\u6d4b\u8bd5\u9879\u76ee',
            'code': 'AIFLOW',
            'description': '\u6d4b\u8bd5AI\u5bf9\u8bdd\u521b\u5efa\u7f3a\u9677\u5230\u4fee\u590d\u7684\u5b8c\u6574\u6d41\u7a0b'
        })
        if create_resp.get('status') in [200, 201]:
            new_proj = create_resp.get('data', {}).get('data', {})
            project_id = str(new_proj.get('id', ''))
            project_code = new_proj.get('code', 'AIFLOW')
            log_pass('Create project', f'ID: {project_id}')
        else:
            log_fail('Create project', str(create_resp))

    # Ensure project has an iteration
    iteration_id = None
    if project_id:
        iter_resp = api_request('POST', f'/api/v1/projects/{project_id}/iterations', token=token, data={
            'name': 'AI Flow Sprint',
            'status': 'active',
            'startDate': '2026-04-01T00:00:00Z',
            'endDate': '2026-05-01T00:00:00Z',
        })
        if iter_resp.get('status') in [200, 201]:
            iteration_id = iter_resp.get('data', {}).get('data', {}).get('id')
            log_pass('Create iteration', f'ID: {iteration_id}')
        else:
            # Get existing iterations
            list_iter = api_request('GET', f'/api/v1/projects/{project_id}/iterations', token=token)
            iter_list = list_iter.get('data', {}).get('data', [])
            if isinstance(iter_list, list) and len(iter_list) > 0:
                iteration_id = iter_list[0].get('id')
                log_pass('Get existing iteration', f'ID: {iteration_id}')
            else:
                log_warn('Create iteration', f'Failed: {str(iter_resp.get("error", ""))[:100]}')

        # Check AI configs
        ai_configs_resp = api_request('GET', f'/api/v1/projects/{project_id}/ai-configs', token=token)
        ai_configs = ai_configs_resp.get('data', {}).get('data', [])
        if isinstance(ai_configs, list) and len(ai_configs) > 0:
            log_pass('AI configs', f'Found {len(ai_configs)} config(s)')
        elif isinstance(ai_configs, dict):
            items = ai_configs.get('items', ai_configs.get('list', []))
            if items:
                log_pass('AI configs', f'Found {len(items)} config(s)')
            else:
                log_warn('AI configs', 'No AI configs - AI features will use fallback')
        else:
            log_warn('AI configs', 'No AI configs found - AI features will use fallback')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()

    # ========== STEP 1: Login ==========
    print('\n' + '='*60)
    print('STEP 1: Login')
    print('='*60)

    page.goto(f'{BASE_URL}/login')
    page.wait_for_load_state('networkidle')
    page.locator('input#username, input[placeholder*="\u7528\u6237\u540d"]').first.fill('admin')
    page.locator('input#password, input[type="password"]').first.fill('admin123')
    page.locator('button[type="submit"]').first.click()
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)

    if '/login' not in page.url:
        log_pass('Login', f'Success, redirected to {page.url}')
    else:
        log_fail('Login', 'Failed')
        browser.close()
        exit(1)

    # ========== STEP 2: Navigate to Create Defect ==========
    print('\n' + '='*60)
    print('STEP 2: Navigate to Create Defect Page')
    print('='*60)

    page.goto(f'{BASE_URL}/projects/{project_id}/defects/create')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    screenshot(page, '01_create_defect_page')

    # Verify we're on chat mode by default
    chat_tab = page.locator('[role="tab"]:has-text("\u5bf9\u8bdd")').first
    if chat_tab.count() > 0:
        log_pass('Chat mode default', 'Chat tab visible')
    else:
        log_warn('Chat mode', 'Chat tab not found')

    # ========== STEP 3: Chat - Input Defect Description ==========
    print('\n' + '='*60)
    print('STEP 3: Chat - Input Defect Description')
    print('='*60)

    # Find the chat textarea
    chat_textarea = page.locator('textarea').first
    if chat_textarea.count() > 0:
        test_description = '\u767b\u5f55\u9875\u9762\u8f93\u5165\u9519\u8bef\u5bc6\u7801\u540e\u6ca1\u6709\u63d0\u793a\u4fe1\u606f\uff0c\u7528\u6237\u65e0\u6cd5\u77e5\u9053\u5bc6\u7801\u9519\u8bef\u8fd8\u662f\u7cfb\u7edf\u6545\u969c\uff0c\u5bfc\u81f4\u53cd\u590d\u91cd\u8bd5\u5e76\u6700\u7ec8\u8d26\u53f7\u88ab\u9501\u5b9a'
        chat_textarea.fill(test_description)
        screenshot(page, '02_chat_description_filled')
        log_pass('Chat input', f'Filled: {test_description[:30]}...')
    else:
        log_fail('Chat input', 'Textarea not found')

    # ========== STEP 4: Chat - Send & Wait for AI Draft ==========
    print('\n' + '='*60)
    print('STEP 4: Chat - Send & Wait for AI Draft Generation')
    print('='*60)

    # Click send button
    send_btn = page.locator('button.brand-button').first
    if send_btn.count() > 0:
        send_btn.click()
        log_pass('Send button clicked', 'Waiting for AI response...')

        # Wait for draft to appear (AI generation may take time, max 30s)
        try:
            draft_confirm = page.wait_for_selector('.defect-draft-confirm', timeout=30000)
            page.wait_for_timeout(1000)
            screenshot(page, '03_ai_draft_generated')
            log_pass('AI draft generated', 'Draft confirm component appeared')
        except:
            # Check if there's any response in chat
            page.wait_for_timeout(5000)
            screenshot(page, '03_ai_draft_timeout')
            log_warn('AI draft', 'Draft confirm not found within 30s - checking page state')

            # Check page content for any AI response
            body_text = page.locator('body').text_content() or ''
            if '\u8349\u7a3f' in body_text or 'draft' in body_text.lower() or '\u786e\u8ba4' in body_text:
                log_pass('AI draft', 'Draft content found in page')
            elif '\u9519\u8bef' in body_text or 'error' in body_text.lower() or '\u5931\u8d25' in body_text:
                log_warn('AI draft', 'AI generation may have failed (no AI config?)')
            else:
                log_warn('AI draft', 'No draft or error message visible')
    else:
        log_fail('Send button', 'Not found')

    # ========== STEP 5: API - Test Draft Generation Directly ==========
    print('\n' + '='*60)
    print('STEP 5: API - Test Draft Generation Directly')
    print('='*60)

    if token and project_id:
        draft_resp = api_request('POST', f'/api/v1/projects/{project_id}/defects/draft-from-chat', token=token, data={
            'message': '\u767b\u5f55\u9875\u9762\u8f93\u5165\u9519\u8bef\u5bc6\u7801\u540e\u6ca1\u6709\u63d0\u793a\u4fe1\u606f\uff0c\u7528\u6237\u65e0\u6cd5\u77e5\u9053\u662f\u5bc6\u7801\u9519\u8bef\u8fd8\u662f\u7cfb\u7edf\u6545\u969c',
            'tags': ['\u767b\u5f55\u6a21\u5757', '\u8868\u5355\u6821\u9a8c']
        }, timeout=120)

        if draft_resp.get('status') == 200:
            draft_data = draft_resp.get('data', {}).get('data', {})
            if isinstance(draft_data, dict):
                title = draft_data.get('title', '')
                severity = draft_data.get('severity', '')
                priority = draft_data.get('priority', '')
                fallback = draft_data.get('fallbackUsed', False)
                log_pass('API draft-from-chat', f'Title: {title[:40]}, Severity: {severity}, Priority: {priority}, Fallback: {fallback}')
            else:
                log_pass('API draft-from-chat', f'Response: {json.dumps(draft_data)[:200]}')
        else:
            log_fail('API draft-from-chat', f'Status: {draft_resp.get("status")}, Error: {str(draft_resp.get("error", ""))[:200]}')

    # ========== STEP 6: API - Confirm Create Defect ==========
    print('\n' + '='*60)
    print('STEP 6: API - Confirm Create Defect from Draft')
    print('='*60)

    created_defect_id = None

    if token and project_id and iteration_id:
        confirm_resp = api_request('POST', f'/api/v1/projects/{project_id}/defects/confirm-create', token=token, data={
            'iterationId': iteration_id,
            'title': '\u767b\u5f55\u9875\u9762\u8f93\u5165\u9519\u8bef\u5bc6\u7801\u540e\u65e0\u63d0\u793a\u4fe1\u606f',
            'descriptionMarkdown': '## \u95ee\u9898\u63cf\u8ff0\n\u767b\u5f55\u9875\u9762\u8f93\u5165\u9519\u8bef\u5bc6\u7801\u540e\u6ca1\u6709\u63d0\u793a\u4fe1\u606f\uff0c\u7528\u6237\u65e0\u6cd5\u77e5\u9053\u5bc6\u7801\u9519\u8bef\u8fd8\u662f\u7cfb\u7edf\u6545\u969c\u3002\n\n## \u590d\u73b0\u6b65\u9aa4\n1. \u6253\u5f00\u767b\u5f55\u9875\u9762\n2. \u8f93\u5165\u9519\u8bef\u5bc6\u7801\n3. \u89c2\u5bdf\u65e0\u9519\u8bef\u63d0\u793a',
            'severity': 'major',
            'priority': 'P1',
            'type': 'functional',
            'tags': ['\u767b\u5f55\u6a21\u5757', '\u8868\u5355\u6821\u9a8c'],
            'sourceMode': 'manual_chat'
        })

        if confirm_resp.get('status') in [200, 201]:
            defect_data = confirm_resp.get('data', {}).get('data', {})
            created_defect_id = defect_data.get('id')
            defect_code = defect_data.get('code', '')
            defect_status = defect_data.get('status', '')
            log_pass('API confirm-create', f'ID: {created_defect_id}, Code: {defect_code}, Status: {defect_status}')
        else:
            log_fail('API confirm-create', f'Status: {confirm_resp.get("status")}, Error: {str(confirm_resp.get("error", ""))[:200]}')

    # ========== STEP 7: Navigate to Defect Detail ==========
    print('\n' + '='*60)
    print('STEP 7: Navigate to Defect Detail Page')
    print('='*60)

    if created_defect_id:
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/{created_defect_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '04_defect_detail')

        # Verify detail page elements
        steps = page.locator('.ant-steps').first
        if steps.count() > 0:
            log_pass('Detail - Steps', 'Found')
        else:
            log_warn('Detail - Steps', 'Not found')

        status_tag = page.locator('.ant-tag').first
        if status_tag.count() > 0:
            log_pass('Detail - Status', f'Status: {status_tag.text_content()}')

        breadcrumb = page.locator('.ant-breadcrumb').first
        if breadcrumb.count() > 0:
            log_pass('Detail - Breadcrumb', 'Found')

        # Check action buttons based on current status
        all_btns = page.locator('button:visible').all()
        btn_texts = [b.text_content().strip() for b in all_btns if b.text_content().strip()]
        log_pass('Detail - All buttons', f'{btn_texts}')

        # Check for specific action buttons
        assign_btn = page.locator('button:has-text("\u6307\u6d3e")').first
        analyze_btn = page.locator('button:has-text("\u5206\u6790")').first
        fix_btn = page.locator('button:has-text("\u4fee\u590d")').first

        if assign_btn.count() > 0:
            log_pass('Detail - Assign button', 'Found')
        if analyze_btn.count() > 0:
            log_pass('Detail - Analyze button', 'Found')
        if fix_btn.count() > 0:
            log_pass('Detail - Fix button', 'Found')
    else:
        log_warn('Defect detail', 'No defect ID available')

    # ========== STEP 8: Assign Defect (Status Transition) ==========
    print('\n' + '='*60)
    print('STEP 8: Assign Defect')
    print('='*60)

    if created_defect_id and token:
        # Get recommend assignees
        assignees_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/recommend-assignees', token=token)
        if assignees_resp.get('status') == 200:
            log_pass('API recommend-assignees', 'OK')
        else:
            log_warn('API recommend-assignees', f'Status: {assignees_resp.get("status")}')

        # Assign defect to admin (user ID 1)
        assign_resp = api_request('PUT', f'/api/v1/defects/{created_defect_id}/assign', token=token, data={
            'assigneeId': 1
        })
        if assign_resp.get('status') == 200:
            log_pass('API assign defect', 'Assigned to admin')
        else:
            log_fail('API assign defect', f'Status: {assign_resp.get("status")}, Error: {str(assign_resp.get("error", ""))[:200]}')

        # Check status after assignment
        defect_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}', token=token)
        if defect_resp.get('status') == 200:
            current_status = defect_resp.get('data', {}).get('data', {}).get('status', '')
            log_pass('Defect status after assign', f'Status: {current_status}')
        else:
            log_warn('Get defect after assign', f'Failed: {defect_resp.get("status")}')

    # ========== STEP 9: Trigger AI Analysis ==========
    print('\n' + '='*60)
    print('STEP 9: Trigger AI Analysis')
    print('='*60)

    if created_defect_id and token:
        # Get available transitions
        transitions_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/transitions', token=token)
        if transitions_resp.get('status') == 200:
            transitions = transitions_resp.get('data', {}).get('data', [])
            if isinstance(transitions, list):
                log_pass('API transitions', f'Available: {[t.get("to", t.get("status", "")) if isinstance(t, dict) else t for t in transitions]}')
            else:
                log_pass('API transitions', f'Response: {json.dumps(transitions)[:200] if isinstance(transitions, (dict, list)) else transitions}')
        else:
            log_warn('API transitions', f'Status: {transitions_resp.get("status")}')

        # Try to transition to pending_analysis (use /status endpoint, not /transition)
        transition_resp = api_request('PUT', f'/api/v1/defects/{created_defect_id}/status', token=token, data={
            'status': 'pending_analysis'
        })
        if transition_resp.get('status') == 200:
            log_pass('Transition to pending_analysis', 'OK')
        else:
            log_warn('Transition to pending_analysis', f'Status: {transition_resp.get("status")}, Error: {str(transition_resp.get("error", ""))[:200]}')

        # Trigger analysis via API
        analyze_resp = api_request('POST', '/api/v1/agents/analyze', token=token, data={
            'defectId': created_defect_id,
            'agentTypes': ['frontend']
        })
        if analyze_resp.get('status') == 200:
            log_pass('API trigger analysis', 'Analysis started')
        else:
            log_warn('API trigger analysis', f'Status: {analyze_resp.get("status")}, Error: {str(analyze_resp.get("error", ""))[:200]}')

        # Wait and check for analysis reports
        print('  Waiting 10s for analysis to process...')
        time.sleep(10)

        reports_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/reports', token=token)
        if reports_resp.get('status') == 200:
            reports = reports_resp.get('data', {}).get('data', [])
            if isinstance(reports, list):
                if len(reports) > 0:
                    for r in reports:
                        log_pass('Analysis report', f'Status: {r.get("status")}, Agent: {r.get("agentType")}, Fallback: {r.get("fallbackUsed")}')
                else:
                    log_warn('Analysis reports', 'No reports yet (may still be processing)')
            else:
                log_pass('Analysis reports', f'Response: {json.dumps(reports)[:200]}')
        else:
            log_warn('Analysis reports', f'Status: {reports_resp.get("status")}')

        # Refresh detail page to see updated status
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/{created_defect_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '05_after_analysis')

        status_tag = page.locator('.ant-tag').first
        if status_tag.count() > 0:
            log_pass('Status after analysis', f'Status: {status_tag.text_content()}')

    # ========== STEP 10: Trigger AI Fix ==========
    print('\n' + '='*60)
    print('STEP 10: Trigger AI Fix')
    print('='*60)

    if created_defect_id and token:
        # Check current defect status
        defect_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}', token=token)
        current_status = ''
        if defect_resp.get('status') == 200:
            current_status = defect_resp.get('data', {}).get('data', {}).get('status', '')
            log_pass('Current defect status', f'Status: {current_status}')

        # Transition to pending_fix if needed
        if current_status != 'pending_fix' and current_status != 'fixing':
            transition_resp = api_request('PUT', f'/api/v1/defects/{created_defect_id}/status', token=token, data={
                'status': 'pending_fix'
            })
            if transition_resp.get('status') == 200:
                log_pass('Transition to pending_fix', 'OK')
            else:
                log_warn('Transition to pending_fix', f'Status: {transition_resp.get("status")}, Error: {str(transition_resp.get("error", ""))[:200]}')

        # Trigger fix task via API
        fix_resp = api_request('POST', f'/api/v1/defects/{created_defect_id}/fix-tasks', token=token, data={
            'agentType': 'frontend',
            'targetBranch': 'fix/login-error-prompt'
        })
        if fix_resp.get('status') in [200, 201]:
            fix_data = fix_resp.get('data', {}).get('data', {})
            task_code = fix_data.get('taskCode', '')
            task_status = fix_data.get('status', '')
            log_pass('API create fix task', f'TaskCode: {task_code}, Status: {task_status}')
        else:
            log_fail('API create fix task', f'Status: {fix_resp.get("status")}, Error: {str(fix_resp.get("error", ""))[:200]}')

        # Wait and check fix task status
        print('  Waiting 5s for fix task to start...')
        time.sleep(5)

        # Check fix tasks list
        fix_tasks_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/fix-tasks', token=token)
        if fix_tasks_resp.get('status') == 200:
            fix_tasks = fix_tasks_resp.get('data', {}).get('data', [])
            if isinstance(fix_tasks, list):
                for ft in fix_tasks:
                    log_pass('Fix task', f'Code: {ft.get("taskCode", ft.get("code", ""))}, Status: {ft.get("status")}')
            else:
                log_pass('Fix tasks', f'Response: {json.dumps(fix_tasks)[:200]}')
        else:
            log_warn('Fix tasks list', f'Status: {fix_tasks_resp.get("status")}')

        # Refresh detail page
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/{created_defect_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)
        screenshot(page, '06_after_fix_triggered')

        status_tag = page.locator('.ant-tag').first
        if status_tag.count() > 0:
            log_pass('Status after fix trigger', f'Status: {status_tag.text_content()}')

    # ========== STEP 11: Test Frontend Fix Modal ==========
    print('\n' + '='*60)
    print('STEP 11: Test Frontend Fix Modal Interaction')
    print('='*60)

    if created_defect_id:
        # Navigate to a defect in pending_fix status
        # First create another defect and set it to pending_fix
        if token and project_id:
            confirm_resp2 = api_request('POST', f'/api/v1/projects/{project_id}/defects/confirm-create', token=token, data={
                'iterationId': iteration_id,
                'title': '\u9996\u9875\u52a0\u8f7d\u901f\u5ea6\u8fc7\u6162\u8d85\u8fc73\u79d2',
                'descriptionMarkdown': '\u9996\u9875\u52a0\u8f7d\u901f\u5ea6\u8fc7\u6162\uff0c\u767d\u5c4f\u65f6\u95f4\u8d85\u8fc73\u79d2\uff0c\u5f71\u54cd\u7528\u6237\u4f53\u9a8c',
                'severity': 'minor',
                'priority': 'P2',
                'type': 'performance',
                'sourceMode': 'manual_chat'
            })
            defect2_id = None
            if confirm_resp2.get('status') in [200, 201]:
                defect2_id = confirm_resp2.get('data', {}).get('data', {}).get('id')
                log_pass('Create second defect', f'ID: {defect2_id}')

                # Assign and transition to pending_fix
                api_request('PUT', f'/api/v1/defects/{defect2_id}/assign', token=token, data={'assigneeId': 1})
                api_request('PUT', f'/api/v1/defects/{defect2_id}/status', token=token, data={'status': 'pending_analysis'})
                api_request('PUT', f'/api/v1/defects/{defect2_id}/status', token=token, data={'status': 'pending_fix'})

                # Navigate to this defect
                page.goto(f'{BASE_URL}/projects/{project_id}/defects/{defect2_id}')
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(2000)
                screenshot(page, '07_defect_pending_fix')

                # Look for fix button
                fix_btn = page.locator('button:has-text("\u5f00\u59cb\u4fee\u590d"), button:has-text("\u4fee\u590d")').first
                if fix_btn.count() > 0:
                    fix_btn.click()
                    page.wait_for_timeout(1000)
                    screenshot(page, '08_fix_modal')

                    # Check modal content
                    modal = page.locator('.ant-modal:visible, [class*="modal"]:visible').first
                    if modal.count() > 0:
                        log_pass('Fix modal', 'Opened successfully')

                        # Check for branch input
                        branch_input = page.locator('.ant-modal input[placeholder*="\u5206\u652f"], .ant-modal input[placeholder*="branch"]').first
                        if branch_input.count() > 0:
                            branch_input.fill('fix/homepage-loading')
                            log_pass('Fix modal - Branch input', 'Filled')

                        # Check for confirm button
                        confirm_btn = page.locator('.ant-modal button:has-text("\u521b\u5efa\u4fee\u590d\u4efb\u52a1"), .ant-modal button:has-text("\u786e\u5b9a"), .ant-modal button[type="submit"]').first
                        if confirm_btn.count() > 0:
                            log_pass('Fix modal - Confirm button', 'Found')
                        else:
                            log_warn('Fix modal - Confirm button', 'Not found')

                        screenshot(page, '09_fix_modal_filled')
                    else:
                        log_warn('Fix modal', 'Modal did not appear')
                else:
                    log_warn('Fix button', 'Not found on pending_fix defect')

    # ========== STEP 12: Test Collaboration Panel ==========
    print('\n' + '='*60)
    print('STEP 12: Test Collaboration Panel')
    print('='*60)

    if created_defect_id:
        page.goto(f'{BASE_URL}/projects/{project_id}/defects/{created_defect_id}')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2000)

        # Look for collaboration tab or panel
        collab_tab = page.locator('[role="tab"]:has-text("\u534f\u4f5c"), [role="tab"]:has-text("Collaboration")').first
        if collab_tab.count() > 0:
            collab_tab.click()
            page.wait_for_timeout(1000)
            screenshot(page, '10_collaboration_panel')
            log_pass('Collaboration panel', 'Tab found and clicked')
        else:
            log_warn('Collaboration panel', 'Tab not found')

        # Test collaboration API
        if token:
            collab_resp = api_request('POST', f'/api/v1/defects/{created_defect_id}/collaborations', token=token, data={
                'defectId': created_defect_id,
                'agentTypes': ['frontend'],
                'triggerUserId': 1
            })
            if collab_resp.get('status') in [200, 201]:
                log_pass('API collaboration', 'Started')
            else:
                log_warn('API collaboration', f'Status: {collab_resp.get("status")}, Error: {str(collab_resp.get("error", ""))[:200]}')

    # ========== STEP 13: Verify Defect History ==========
    print('\n' + '='*60)
    print('STEP 13: Verify Defect History & Comments')
    print('='*60)

    if created_defect_id and token:
        history_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/history', token=token)
        if history_resp.get('status') == 200:
            history = history_resp.get('data', {}).get('data', [])
            if isinstance(history, list):
                log_pass('Defect history', f'{len(history)} history entries')
                for h in history[:3]:
                    action = h.get('action', h.get('field', ''))
                    log_pass('  History entry', f'Action: {action}')
            else:
                log_pass('Defect history', f'Response: {json.dumps(history)[:200]}')
        else:
            log_warn('Defect history', f'Status: {history_resp.get("status")}')

        comments_resp = api_request('GET', f'/api/v1/defects/{created_defect_id}/comments', token=token)
        if comments_resp.get('status') == 200:
            comments = comments_resp.get('data', {}).get('data', [])
            if isinstance(comments, list):
                log_pass('Defect comments', f'{len(comments)} comments')
            else:
                log_pass('Defect comments', f'Response: {json.dumps(comments)[:200]}')
        else:
            log_warn('Defect comments', f'Status: {comments_resp.get("status")}')

    # ========== STEP 14: Full Frontend Chat-to-Create Flow ==========
    print('\n' + '='*60)
    print('STEP 14: Full Frontend Chat-to-Create Flow (End-to-End)')
    print('='*60)

    page.goto(f'{BASE_URL}/projects/{project_id}/defects/create')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)
    screenshot(page, '11_chat_create_start')

    # Fill chat input with a realistic defect description
    chat_textarea = page.locator('textarea').first
    if chat_textarea.count() > 0:
        chat_textarea.fill('\u7528\u6237\u5728\u4e2a\u4eba\u8bbe\u7f6e\u9875\u9762\u4fee\u6539\u5934\u50cf\u540e\u70b9\u51fb\u4fdd\u5b58\u6309\u94ae\u65e0\u53cd\u5e94\uff0c\u5934\u50cf\u672a\u66f4\u65b0\uff0c\u4e5f\u6ca1\u6709\u9519\u8bef\u63d0\u793a\uff0c\u5237\u65b0\u9875\u9762\u540e\u5934\u50cf\u6062\u590d\u4e3a\u65e7\u7684')
        screenshot(page, '12_chat_filled_v2')

        # Click send
        send_btn = page.locator('button.brand-button').first
        if send_btn.count() > 0:
            send_btn.click()
            log_pass('Chat send', 'Clicked')

            # Wait for AI response with longer timeout
            print('  Waiting up to 60s for AI draft generation...')
            try:
                page.wait_for_selector('.defect-draft-confirm', timeout=60000)
                page.wait_for_timeout(2000)
                screenshot(page, '13_draft_generated_v2')
                log_pass('Full chat flow - Draft generated', 'Success')

                # Try to find and click confirm button
                confirm_create_btn = page.locator('button:has-text("\u786e\u8ba4\u521b\u5efa"), button:has-text("\u63d0\u4ea4"), button:has-text("\u521b\u5efa")').first
                if confirm_create_btn.count() > 0:
                    log_pass('Full chat flow - Confirm button', 'Found')
                    screenshot(page, '14_before_confirm')
                else:
                    log_warn('Full chat flow - Confirm button', 'Not found')
            except:
                screenshot(page, '13_draft_timeout_v2')
                log_warn('Full chat flow - Draft generation', 'Timeout or no draft component found')

                # Check if there are any error messages
                error_msg = page.locator('.ant-message, .ant-alert-error, [class*="error"]').first
                if error_msg.count() > 0:
                    log_warn('Full chat flow - Error', error_msg.text_content()[:100])

    # ========== STEP 15: Console Error Check ==========
    print('\n' + '='*60)
    print('STEP 15: Console Error Check on Key Pages')
    print('='*60)

    console_errors = []
    def handle_console(msg):
        if msg.type == 'error':
            console_errors.append(msg.text)

    page.on('console', handle_console)

    key_pages = [
        (f'/projects/{project_id}/defects/create', 'Create Defect'),
        (f'/projects/{project_id}/defects/{created_defect_id}', 'Defect Detail'),
    ] if project_id and created_defect_id else []

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
