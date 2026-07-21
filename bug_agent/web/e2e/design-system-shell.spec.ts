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

function ok<T>(data: T) {
  return { code: 0, data };
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

async function mockPlatformRoutes(page: Page) {
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
        list: [
          {
            id: 1,
            name: 'Bug Agent 平台',
            code: 'BAG',
            status: 'active',
            description: '统一缺陷协作工作台',
            memberCount: 5,
            pendingDefects: 4,
            activeDefects: 2,
            members: [{ id: 1, nickname: '管理员' }],
          },
        ],
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
    if (method === 'POST' && path === '/api/v1/notifications/read-all') {
      await json(route, ok({ success: true }));
      return;
    }
    if (method === 'POST' && path.match(/^\/api\/v1\/notifications\/\d+\/read$/)) {
      await json(route, ok({ success: true }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/defects') {
      await json(route, ok({ list: [], total: 0 }));
      return;
    }

    await json(route, ok({}));
  });
}

async function mockProjectRoutes(page: Page) {
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
        list: [{ id: 1, name: 'Bug Agent 平台', code: 'BAG' }],
      }));
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
    if (method === 'GET' && path === '/api/v1/projects/1/iterations') {
      await json(route, ok([{ id: 11, name: 'Sprint 5', status: 'active', startDate: '2026-04-10', endDate: '2026-04-20' }]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/stats') {
      await json(route, ok({ total: 9, pending: 4, fixing: 2, completed: 3, urgent: 1 }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/defects') {
      await json(route, ok({
        list: [
          {
            id: 2,
            code: 'BUG-BAG-002',
            title: '缺陷详情页需要新的工作台布局',
            severity: 'major',
            priority: 'P1',
            status: 'pending_fix',
            type: 'functional',
            createdAt: '2026-04-13T12:00:00+08:00',
            assignee: { id: 1, username: 'admin', nickname: '管理员' },
          },
        ],
        total: 1,
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/defects/2') {
      await json(route, ok({
        defect: {
          id: 2,
          code: 'BUG-BAG-002',
          title: '缺陷详情页需要新的工作台布局',
          description: '## 背景\n当前详情结构过于松散。',
          severity: 'major',
          priority: 'P1',
          type: 'functional',
          status: 'pending_fix',
          tags: 'ui,detail',
          createdAt: '2026-04-13T12:00:00+08:00',
          updatedAt: '2026-04-13T12:30:00+08:00',
          assignee: { id: 1, username: 'admin', nickname: '管理员' },
          reporter: { id: 1, username: 'admin', nickname: '管理员' },
          iteration: { id: 11, name: 'Sprint 5' },
        },
        comments: [],
        fixTasks: [],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/defects/2/reports') {
      await json(route, ok([
        {
          id: 8,
          agentType: 'ui',
          provider: 'dashscope',
          modelName: 'qwen3.6-plus',
          promptVersion: 'v5.2',
          status: 'completed',
          durationMs: 1000,
          totalTokens: 1000,
          estimatedCostUsd: 0.01,
          fallbackUsed: false,
          createdAt: '2026-04-13T12:40:00+08:00',
          riskSummary: '需要把摘要、动作和原始信息分层。',
          summaryMarkdown: '## 根因\n页面层级不清。',
          validationSuggestions: '["检查摘要层是否始终在首屏"]',
          analysis: JSON.stringify({
            rootCause: '页面层级不清',
            riskLevel: 'medium',
            riskSummary: '影响阅读效率',
            affectedFiles: ['web/src/pages/defects/DefectDetail.tsx'],
            validationSuggestions: ['检查摘要层是否始终在首屏'],
          }),
        },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/users') {
      await json(route, ok({ list: [MOCK_USER] }));
      return;
    }
    if (method === 'GET' && path.startsWith('/api/v1/collaborations/')) {
      await json(route, ok(null));
      return;
    }
    if (method === 'POST' && path === '/api/v1/collaborations') {
      await json(route, ok({ id: 1, status: 'pending' }));
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
    if (method === 'POST' && path === '/api/v1/notifications/read-all') {
      await json(route, ok({ success: true }));
      return;
    }
    if (method === 'POST' && path.match(/^\/api\/v1\/notifications\/\d+\/read$/)) {
      await json(route, ok({ success: true }));
      return;
    }

    await json(route, ok({}));
  });
}

test.describe('design system shell', () => {
  test('平台级页面渲染新的平台控制台骨架', async ({ page }) => {
    await seedAuth(page);
    await mockPlatformRoutes(page);

    await page.goto('/projects');

    await expect(page.getByTestId('platform-shell')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-sidebar-header')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-sidebar-brand')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-navigation')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-topbar-heading')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-workspace-selector')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-search-field')).toBeVisible();
    await expect(page.locator('[data-testid="platform-shell"] .shell-user-trigger')).toBeVisible();
    await expect(page.locator('[data-testid="platform-hero"]')).toHaveCount(0);
    await expect(page.locator('.page-action-bar')).toBeVisible();
    await expect(page.locator('.metric-rail')).toHaveClass(/metric-rail--compact/);
    await expect(page.locator('.action-rail')).toHaveClass(/action-rail--compact/);
    await expect(page.locator('.shell-context-card')).toHaveCount(1);
    await expect(page.locator('.shell-context-card__meta')).toHaveCount(0);
    await expect(page.locator('.page-hero')).toHaveCount(0);
    await expect(page.locator('.topbar__subtitle')).toHaveCount(0);
    await expect(page.locator('[data-testid="platform-shell"] .topbar__title')).toHaveText('项目列表');
    await expect(page.getByText('AI Roles')).toHaveCount(0);
    await expect(page.locator('.project-card__badge').first()).toHaveClass(/project-card__badge--muted/);
    await expect(page.locator('.project-card__meta').first()).toBeVisible();
    await expect(page.locator('.project-card__footer .ant-tag')).toHaveCount(0);
    await expect(page.locator('.project-card__status').first()).toBeVisible();
    await expect(page.locator('.project-card__header .ant-tag')).toHaveCount(0);
    await expect(page.locator('.project-card__members').first()).toBeVisible();
    await expect(page.locator('.project-card__stat').first()).toBeVisible();

    const activeTitleBox = await page.locator('.shell-rail__item.is-active .shell-rail__title').boundingBox();
    const activeSubtitleBox = await page.locator('.shell-rail__item.is-active .shell-rail__subtitle').boundingBox();
    expect(activeTitleBox).not.toBeNull();
    expect(activeSubtitleBox).not.toBeNull();
    expect((activeSubtitleBox?.y ?? 0)).toBeGreaterThan((activeTitleBox?.y ?? 0) + (activeTitleBox?.height ?? 0) - 1);
  });

  test('项目级页面渲染新的项目工作区骨架', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '1' });
    await mockProjectRoutes(page);

    await page.goto('/projects/1');

    await expect(page.getByTestId('project-shell')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-sidebar-header')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-sidebar-brand')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-sidebar-backlink')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-navigation')).toBeVisible();
    await expect(page.getByTestId('project-context-panel')).toHaveCount(0);
    await expect(page.locator('[data-testid="project-shell"] .shell-topbar-heading')).toHaveCount(0);
    await expect(page.locator('[data-testid="project-shell"] .shell-workspace-selector')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-search-field')).toBeVisible();
    await expect(page.locator('[data-testid="project-shell"] .shell-user-trigger')).toBeVisible();
    await expect(page.locator('[data-testid="project-dashboard-hero"]')).toHaveCount(0);
    await expect(page.locator('.page-action-bar')).toBeVisible();
    await expect(page.locator('.page-hero')).toHaveCount(0);
    await expect(page.locator('[data-testid="active-iteration-list"]')).toBeVisible();
    await expect(page.locator('[data-testid="iteration-summary-card"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="active-iteration-list"] .ant-tag')).toHaveCount(0);
    await expect(page.locator('[data-testid="recent-defect-list"]')).toBeVisible();
    await expect(page.locator('[data-testid="recent-defect-row"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="recent-defect-row"] .ant-tag')).toHaveCount(0);
    await expect(page.locator('.recent-defect-row__meta').first()).toBeVisible();
  });

  test('缺陷详情页渲染摘要带和决策侧轨', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '1' });
    await mockProjectRoutes(page);

    await page.goto('/projects/1/defects/2');

    await expect(page.getByTestId('defect-summary-band')).toBeVisible();
    await expect(page.getByTestId('defect-decision-rail')).toBeVisible();
    await expect(page.getByText('最新 AI 结论')).toBeVisible();
  });
});
