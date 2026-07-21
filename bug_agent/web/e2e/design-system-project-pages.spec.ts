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

async function mockProjectDesignRoutes(page: Page) {
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
        items: [
          { id: 1, name: 'Bug Agent 平台', code: 'BAG' },
          { id: 2, name: '质量中台', code: 'QMS' },
        ],
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
    if (method === 'POST' && /^\/api\/v1\/notifications\/\d+\/read$/.test(path)) {
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
          { id: 2, userId: 2, username: 'qa', nickname: '测试同学', role: 'tester' },
        ],
        iterations: [
          { id: 11, name: 'Sprint 5', status: 'active', startDate: '2026-04-10', endDate: '2026-04-20', goal: '统一 UI 骨架' },
          { id: 12, name: 'Sprint 6', status: 'planning', startDate: '2026-04-21', endDate: '2026-05-05', goal: '收敛长尾页面' },
        ],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/iterations') {
      await json(route, ok([
        { id: 11, name: 'Sprint 5', status: 'active', startDate: '2026-04-10', endDate: '2026-04-20', goal: '统一 UI 骨架' },
        { id: 12, name: 'Sprint 6', status: 'planning', startDate: '2026-04-21', endDate: '2026-05-05', goal: '收敛长尾页面' },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/stats') {
      await json(route, ok({ total: 9, pending: 4, fixing: 2, completed: 3, urgent: 1 }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/users') {
      await json(route, ok({
        list: [
          MOCK_USER,
          {
            id: 2,
            username: 'qa',
            nickname: '测试同学',
            email: 'qa@example.com',
            platformRole: 'member',
            agentTypes: 'test',
          },
        ],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/credentials') {
      await json(route, ok([
        {
          id: 1,
          name: '云效项目凭证',
          provider: 'yunxiao',
          type: 'access_token',
          maskedValue: 'yx_****',
          extraConfig: JSON.stringify({
            organizationId: 'org-1',
            endpoint: 'https://openapi-rdc.aliyuncs.com',
          }),
        },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/repos') {
      await json(route, ok([
        {
          id: 1,
          name: 'bug-agent-web',
          sourceType: 'github',
          repoUrl: 'https://github.com/example/bug-agent-web',
          defaultBranch: 'main',
          credentialId: 1,
          agentTypes: 'frontend,test',
          description: 'Web 端主仓库',
        },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/integrations') {
      await json(route, ok([
        {
          id: 1,
          name: 'Bugly Android',
          type: 'bugly',
          status: 'active',
          inboundPath: '/hook/bugly/android',
          config: { endpoint: 'https://bugly.qq.com', appId: 'app-1' },
          healthStatus: 'healthy',
          healthSummary: '最近一次同步成功',
          lastSyncStatus: 'success',
          lastSyncAt: '2026-04-13T13:00:00+08:00',
        },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/issue-clusters') {
      await json(route, ok({
        items: [
          {
            id: 101,
            title: '登录页在低端机白屏',
            status: 'new',
            severity: 'major',
            platform: 'android',
            appVersion: '5.2.0',
            sourceType: 'bugly',
            affectedUserCount: 12,
            signalCount: 36,
            owner: { id: 1, nickname: '管理员', username: 'admin' },
            routingConfidence: 0.82,
            createdAt: '2026-04-13T10:00:00+08:00',
            updatedAt: '2026-04-13T12:00:00+08:00',
          },
        ],
        total: 1,
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/issue-clusters/release-summary') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && /^\/api\/v1\/projects\/1\/issue-clusters\/\d+\/signals$/.test(path)) {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && /^\/api\/v1\/projects\/1\/issue-clusters\/\d+\/releases$/.test(path)) {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/modules') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/routing-rules') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/releases') {
      await json(route, ok([
        {
          id: 1,
          platform: 'android',
          appVersion: '5.2.0',
          buildNumber: '52001',
          channel: 'prod',
          releaseTime: '2026-04-13T09:00:00+08:00',
          repoId: 1,
        },
      ]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/releases/trends') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/regression-items') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/quality-insights/overview') {
      await json(route, ok({
        issuePool: { totalClusters: 14, openClusters: 6, convertedClusters: 4, ignoredClusters: 4 },
        releaseHealth: { highAnomalyCount: 1, watchAnomalyCount: 2, normalCount: 5 },
        regression: { openItems: 3, verifiedItems: 8, archivedItems: 2 },
        ai: {
          analysisCount: 18,
          fixTaskCount: 7,
          successfulCount: 20,
          fallbackCount: 2,
          failedCount: 3,
          averageDurationMs: 1820,
          totalEstimatedCostUsd: 2.18,
        },
        topReleaseAnomalies: [],
        sourceBreakdowns: [],
        moduleHotspots: [],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/ai/providers') {
      await json(route, {
        data: [
          {
            value: 'openai',
            name: 'OpenAI',
            models: [
              { name: 'gpt-5.4', endpoint: 'https://api.openai.com/v1' },
            ],
          },
        ],
      });
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/ai-configs') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/notification-webhooks') {
      await json(route, ok([]));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/notification-policies') {
      await json(route, ok([
        {
          category: 'defect_assigned',
          inAppEnabled: true,
          emailEnabled: false,
          webhookId: null,
        },
        {
          category: 'defect_status_change',
          inAppEnabled: true,
          emailEnabled: true,
          webhookId: null,
        },
      ]));
      return;
    }
    if (method === 'GET' && /^\/api\/v1\/projects\/1\/iterations\/\d+$/.test(path)) {
      await json(route, ok({
        id: 11,
        name: 'Sprint 5',
        startDate: '2026-04-10',
        endDate: '2026-04-20',
        status: 'active',
        goal: '统一 UI 骨架',
        repos: [],
      }));
      return;
    }

    await json(route, ok({}));
  });
}

test.describe('design system project pages', () => {
  test('问题收集与质量页移除 hero', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '1' });
    await mockProjectDesignRoutes(page);

    const cases = [
      ['/projects/1/defects/create', 'defect-create-hero', true],
      ['/projects/1/issue-pool', 'issue-pool-hero', true],
      ['/projects/1/integrations', 'project-integrations-hero', true],
      ['/projects/1/routing', 'project-routing-hero', true],
      ['/projects/1/regression', 'project-regression-hero', false],
      ['/projects/1/quality-insights', 'project-quality-insights-hero', true],
    ] as const;

    for (const [url, testId, hasActionBar] of cases) {
      await page.goto(url);
      await expect(page.getByTestId(testId)).toHaveCount(0);
      await expect(page.locator('.page-hero')).toHaveCount(0);
      if (hasActionBar) {
        await expect(page.locator('.page-action-bar')).toBeVisible();
      }
    }
  });

  test('项目治理页移除 hero', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '1' });
    await mockProjectDesignRoutes(page);

    const cases = [
      ['/projects/1/iterations', 'project-iterations-hero', true],
      ['/projects/1/members', 'project-members-hero', true],
      ['/projects/1/repos', 'project-repos-hero', true],
      ['/projects/1/ai-configs', 'project-ai-configs-hero', true],
      ['/projects/1/notifications', 'project-notifications-hero', true],
      ['/projects/1/settings', 'project-settings-hero', false],
    ] as const;

    for (const [url, testId, hasActionBar] of cases) {
      await page.goto(url);
      await expect(page.getByTestId(testId)).toHaveCount(0);
      await expect(page.locator('.page-hero')).toHaveCount(0);
      if (hasActionBar) {
        await expect(page.locator('.page-action-bar')).toBeVisible();
      }

      if (url === '/projects/1/repos') {
        const metricsWithinViewport = await page.locator('.metric-action-row').evaluate((node) => {
          const rect = node.getBoundingClientRect();
          return rect.right <= window.innerWidth + 1;
        });
        expect(metricsWithinViewport).toBeTruthy();
      }
    }
  });
});
