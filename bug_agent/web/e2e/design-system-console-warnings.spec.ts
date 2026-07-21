import { expect, test, type Page, type Route } from '@playwright/test';

const MOCK_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjQxMDI0NDQ4MDAsInN1YiI6MX0.mock-signature';
const MOCK_USER = {
  id: 1,
  username: 'admin',
  nickname: '管理员',
  email: 'admin@example.com',
  platformRole: 'admin',
  agentTypes: 'backend,test',
};

function ok<T>(data: T, extras?: Record<string, unknown>) {
  return { code: 0, data, ...(extras || {}) };
}

async function json(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(payload),
  });
}

async function seedAuth(page: Page, options?: { lastProjectId?: string }) {
  await page.addInitScript((input) => {
    localStorage.setItem('token', input.token);
    localStorage.setItem('user', JSON.stringify(input.user));
    if (input.lastProjectId) {
      localStorage.setItem('lastProjectId', input.lastProjectId);
    }
  }, {
    token: MOCK_TOKEN,
    user: MOCK_USER,
    lastProjectId: options?.lastProjectId,
  });
}

async function mockWarningRoutes(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const method = req.method();
    const path = new URL(req.url()).pathname;

    if (method === 'GET' && path === '/api/v1/users/me') {
      await json(route, ok(MOCK_USER));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects') {
      await json(route, ok({
        items: [{ id: 1, name: 'Bug Agent 平台', code: 'BAG' }],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/user/projects') {
      await json(route, ok({
        list: [{
          id: 1,
          name: 'Bug Agent 平台',
          code: 'BAG',
          status: 'active',
          description: '统一缺陷协作工作台',
          memberCount: 5,
          pendingDefects: 4,
          activeDefects: 2,
          members: [{ id: 1, nickname: '管理员' }],
        }],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/notifications/unread-count') {
      await json(route, ok({ count: 0 }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/notifications') {
      await json(route, ok({ items: [] }));
      return;
    }
    if ((method === 'POST' || method === 'PUT') && path.includes('/notifications')) {
      await json(route, ok({ success: true }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1') {
      await json(route, ok({
        project: {
          id: 1,
          name: 'Bug Agent 平台',
          code: 'BAG',
          description: '统一缺陷协作工作台',
        },
        members: [
          { id: 1, userId: 1, username: 'admin', nickname: '管理员', role: 'project_admin' },
        ],
        iterations: [
          { id: 11, name: 'Sprint 5', status: 'active', startDate: '2026-04-10', endDate: '2026-04-20' },
        ],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/stats') {
      await json(route, ok({ total: 9, pending: 4, fixing: 2, completed: 3, urgent: 1 }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/defects') {
      await json(route, ok({
        list: [{
          id: 2,
          code: 'BUG-BAG-002',
          title: '缺陷列表需要新的数据舞台',
          severity: 'major',
          priority: 'P1',
          status: 'pending_fix',
          type: 'functional',
          createdAt: '2026-04-13T12:00:00+08:00',
          assignee: { id: 1, username: 'admin', nickname: '管理员' },
        }],
        total: 1,
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/repos') {
      await json(route, ok([{ id: 1, name: 'bug-agent-web', repoUrl: 'https://github.com/example/repo', defaultBranch: 'main', description: 'web repo' }]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/ai-configs') {
      await json(route, ok([{ id: 1, provider: 'openai', modelName: 'gpt-5.4', apiKey: 'sk-test-key', apiEndpoint: 'https://api.openai.com/v1', isDefault: true }]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/users') {
      await json(route, ok({
        list: [{
          id: 1,
          username: 'admin',
          nickname: '管理员',
          email: 'admin@example.com',
          platformRole: 'admin',
          agentTypes: 'backend,test',
          createdAt: '2026-04-13T12:00:00+08:00',
          lastLoginAt: '2026-04-13T13:00:00+08:00',
        }],
        total: 1,
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/invites') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/audit-logs') {
      await json(route, { code: 0, data: [{
        id: 1,
        createdAt: '2026-04-13T12:00:00+08:00',
        username: 'admin',
        action: 'POST create_defect',
        targetType: 'defect',
        targetId: 2,
        statusCode: 201,
        durationMs: 320,
        ipAddress: '127.0.0.1',
      }], total: 1 });
      return;
    }
    if (method === 'GET' && path === '/api/v1/audit-logs/stats') {
      await json(route, ok({
        totalLogs: 48,
        topActions: [{ action: 'create_defect', count: 12 }],
        activeUsers: [{ userId: 1, username: 'admin', count: 15 }],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/admin/platform-credentials') {
      await json(route, {
        data: [{
          id: 1,
          name: '平台 GitHub PAT',
          scope: 'platform',
          provider: 'github',
          type: 'pat',
          status: 'active',
          allowedProjectIds: [1],
          maskedValue: 'ghp_****',
        }],
      });
      return;
    }
    if (method === 'GET' && path === '/api/v1/admin/ai/providers') {
      await json(route, { data: [{
        id: 1,
        providerKey: 'openai',
        displayName: 'OpenAI',
        defaultEndpoint: 'https://api.openai.com/v1',
        status: 'active',
        sortOrder: 10,
        createdAt: '2026-04-13T12:00:00+08:00',
        updatedAt: '2026-04-13T12:00:00+08:00',
      }] });
      return;
    }
    if (method === 'GET' && path === '/api/v1/admin/ai/models') {
      await json(route, { data: [{
        id: 1,
        providerKey: 'openai',
        modelName: 'gpt-5.4',
        endpoint: '',
        capabilityTags: 'chat,reasoning,code',
        status: 'active',
        isDefault: true,
        sortOrder: 10,
        createdAt: '2026-04-13T12:00:00+08:00',
        updatedAt: '2026-04-13T12:00:00+08:00',
      }] });
      return;
    }

    await json(route, ok({}));
  });
}

test('关键页面不应产生设计系统相关控制台告警', async ({ page }) => {
  await seedAuth(page, { lastProjectId: '1' });
  await mockWarningRoutes(page);

  const warnings: string[] = [];
  const warningPatterns = [
    'The `List` component is deprecated',
    '`valueStyle` is deprecated',
    '`Tabs.TabPane` is deprecated',
    'useForm is not connected to any Form element',
    'Failed to fetch projects:',
    'Failed to fetch iterations:',
  ];

  page.on('console', (msg) => {
    const text = msg.text();
    if (warningPatterns.some((pattern) => text.includes(pattern))) {
      warnings.push(text);
    }
  });

  const urls = [
    '/projects',
    '/projects/1',
    '/audit-logs',
    '/platform-credentials',
    '/projects/1/settings',
    '/users',
    '/ai-catalog',
  ];

  for (const url of urls) {
    await page.goto(url);
    await page.waitForLoadState('networkidle');
  }

  expect(warnings).toEqual([]);
});
