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

test.describe('PRD v2.0 browser e2e', () => {
  test('登录后进入项目列表', async ({ page }) => {
    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'POST' && path === '/api/v1/auth/login') {
        await json(route, ok({ token: MOCK_TOKEN, user: MOCK_USER }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/user/projects') {
        await json(route, ok({
          list: [
            {
              id: 101,
              name: 'BugAgent 平台',
              code: 'BUG',
              status: 'active',
              memberCount: 1,
              pendingDefects: 2,
              activeDefects: 1,
              members: [{ id: 1, nickname: '管理员' }],
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 201, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/login');
    await page.getByRole('button', { name: /登\s*录/ }).click();

    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByRole('heading', { name: '我的项目' })).toBeVisible();
  });

  test('个人信息页可更新 AGENT 身份', async ({ page }) => {
    await seedAuth(page);

    let updatedAgentTypes: string[] | null = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/users/me') {
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: 'backend,test',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences') {
        await json(route, ok([
          { id: 1, category: 'defect_assigned', channels: 'in_app,email' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/users/me/agent-types') {
        const body = req.postDataJSON() as { agentTypes?: string[] };
        updatedAgentTypes = body.agentTypes || [];
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: updatedAgentTypes.join(','),
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/profile');
    await expect(page.getByRole('heading', { name: '管理员' })).toBeVisible();

    await page.getByRole('tab', { name: 'AGENT 身份' }).click();
    await page.getByRole('checkbox', { name: /产品经理/ }).check();
    await page.getByRole('button', { name: '保存 AGENT 身份' }).click();

    await expect(page.getByText('AGENT 身份已更新')).toBeVisible();
    await expect.poll(() => updatedAgentTypes).not.toBeNull();
    expect(updatedAgentTypes).toContain('product');
  });

  test('个人信息从用户菜单打开全局弹窗并支持修改密码', async ({ page }) => {
    await seedAuth(page);

    let changedPasswordPayload: { currentPassword?: string; newPassword?: string } | null = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/users/me') {
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: 'backend,test',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences') {
        await json(route, ok([
          { id: 1, category: 'defect_assigned', channels: 'in_app,email' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/users/me/password') {
        changedPasswordPayload = req.postDataJSON() as { currentPassword?: string; newPassword?: string };
        await json(route, ok({ success: true }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects');
    await expect(page.getByRole('heading', { name: '项目列表' })).toBeVisible();

    await page.getByRole('button', { name: '用户菜单' }).click();
    await page.getByRole('menuitem', { name: '个人信息' }).click();
    await expect(page).toHaveURL(/\/projects$/);

    const modal = page.getByRole('dialog', { name: '个人中心' });
    await expect(modal).toBeVisible();
    await expect(modal.getByText('管理员')).toBeVisible();

    await modal.getByRole('tab', { name: '修改密码' }).click();
    await modal.getByLabel('当前密码').fill('admin123');
    await modal.locator('input#newPassword').fill('Admin@123456789');
    await modal.locator('input#confirmPassword').fill('Admin@123456789');
    await modal.getByRole('button', { name: '保存新密码' }).click();

    await expect.poll(() => changedPasswordPayload).not.toBeNull();
    expect(changedPasswordPayload).toEqual({
      currentPassword: 'admin123',
      newPassword: 'Admin@123456789',
    });
  });

  test('个人中心通知设置支持保存并测试个人 webhook', async ({ page }) => {
    await seedAuth(page);

    let savedWebhookPayload: any = null;
    let testedWebhookPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/users/me') {
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: 'backend,test',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences') {
        await json(route, ok([
          { id: 1, category: 'defect_assigned', channels: 'in_app,email' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences/webhook') {
        await json(route, ok({
          url: 'https://hooks.example.com/current',
          enabled: true,
          secretConfigured: true,
        }));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/notification-preferences/webhook') {
        savedWebhookPayload = req.postDataJSON();
        await json(route, ok({
          url: savedWebhookPayload.url,
          enabled: savedWebhookPayload.enabled,
          secretConfigured: true,
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/notification-preferences/webhook/test') {
        testedWebhookPayload = req.postDataJSON();
        await json(route, ok({
          success: true,
          message: '个人Webhook测试成功',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects');
    await page.getByRole('button', { name: '用户菜单' }).click();
    await page.getByRole('menuitem', { name: '个人信息' }).click();

    const modal = page.getByRole('dialog', { name: '个人中心' });
    await expect(modal).toBeVisible();
    await modal.getByRole('tab', { name: '通知偏好' }).click();

    await modal.getByLabel('个人 Webhook 地址').fill('https://hooks.example.com/new');
    await modal.getByLabel('Webhook Secret（可选）').fill('my-user-secret');
    await modal.getByRole('button', { name: '测试发送' }).click();
    await expect.poll(() => testedWebhookPayload).not.toBeNull();
    expect(testedWebhookPayload.url).toBe('https://hooks.example.com/new');
    expect(testedWebhookPayload.secret).toBe('my-user-secret');

    await modal.getByRole('button', { name: '保存个人Webhook' }).click();
    await expect.poll(() => savedWebhookPayload).not.toBeNull();
    expect(savedWebhookPayload.url).toBe('https://hooks.example.com/new');
    expect(savedWebhookPayload.enabled).toBe(true);
    expect(savedWebhookPayload.secret).toBe('my-user-secret');
  });

  test('普通个人中心支持按 Escape 关闭弹窗', async ({ page }) => {
    await seedAuth(page);

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/users/me') {
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: 'backend,test',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences') {
        await json(route, ok([
          { id: 1, category: 'defect_assigned', channels: 'in_app,email' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences/webhook') {
        await json(route, ok({
          url: '',
          enabled: false,
          secretConfigured: false,
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects');
    await page.getByRole('button', { name: '用户菜单' }).click();
    await page.getByRole('menuitem', { name: '个人信息' }).click();

    const modal = page.getByRole('dialog', { name: '个人中心' });
    await expect(modal).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(modal).toHaveCount(0);
    await expect(page).toHaveURL(/\/projects$/);
  });

  test('临时密码用户登录后会被强制修改密码', async ({ page }) => {
    let changedPasswordPayload: { currentPassword?: string; newPassword?: string } | null = null;
    const consoleErrors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'POST' && path === '/api/v1/auth/login') {
        await json(route, ok({
          token: MOCK_TOKEN,
          user: {
            ...MOCK_USER,
            mustChangePassword: true,
          },
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/users/me/password') {
        changedPasswordPayload = req.postDataJSON() as { currentPassword?: string; newPassword?: string };
        await json(route, ok({ success: true }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/login');
    await page.getByRole('button', { name: /登\s*录/ }).click();

    await expect(page).toHaveURL(/\/projects$/);
    const modal = page.getByRole('dialog', { name: '个人中心' });
    await expect(modal).toBeVisible();
    expect(consoleErrors.join('\n')).not.toContain('useForm` is not connected to any Form element');
    await expect(modal.getByRole('tab', { name: '修改密码' })).toBeVisible();
    await expect(modal.getByRole('tab', { name: '基本信息' })).toHaveCount(0);

    await modal.getByLabel('当前密码').fill('admin123');
    await modal.locator('input#newPassword').fill('Admin@123456789');
    await modal.locator('input#confirmPassword').fill('Admin@123456789');
    await modal.getByRole('button', { name: '保存新密码' }).click();

    await expect.poll(() => changedPasswordPayload).not.toBeNull();
    await expect(modal).toHaveCount(0);
  });

  test('仓库管理页可触发仓库连接测试', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    let connectionChecked = false;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v2.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/repos') {
        await json(route, ok([
          {
            id: 501,
            projectId: 101,
            name: 'bug-agent-server',
            repoUrl: 'https://github.com/example/bug-agent-server.git',
            sourceType: 'github',
            credentialId: 11,
            agentTypes: 'backend,test',
            defaultBranch: 'main',
            description: 'mock repo',
          },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok([
          {
            id: 11,
            name: 'GitHub-PAT',
            maskedValue: 'ghp_****',
          },
        ]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/repos/501/test-connection') {
        connectionChecked = true;
        await json(route, ok({
          success: true,
          message: '连接成功(mock)',
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/repos');
    await expect(page.getByRole('heading', { name: '仓库管理' })).toBeVisible();

    await page.getByRole('button', { name: '测试连接' }).first().click();
    await expect(page.getByText('连接成功(mock)')).toBeVisible();
    await expect.poll(() => connectionChecked).toBeTruthy();
  });

  test('顶部通知按钮可打开消息中心并支持标记已读', async ({ page }) => {
    await seedAuth(page);

    let markReadPayload: { ids?: number[] } | null = null;
    const notifications = [
      {
        id: 901,
        title: '缺陷状态已更新',
        content: 'BUG-101 已进入待验证',
        type: 'in_app',
        category: 'defect_status_change',
        read: false,
        related_id: 88,
        metadata: JSON.stringify({ defect_id: 88 }),
        created_at: 1775808000,
      },
      {
        id: 902,
        title: '系统公告',
        content: '今晚 22:00 进行发布演练',
        type: 'in_app',
        category: 'system_announce',
        read: true,
        related_id: 0,
        metadata: 'null',
        created_at: 1775807000,
      },
    ];

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notifications/unread-count') {
        await json(route, {
          code: 0,
          count: notifications.filter((item) => !item.read).length,
        });
        return;
      }
      if (method === 'GET' && path === '/api/v1/notifications') {
        await json(route, {
          code: 0,
          data: notifications,
          total: notifications.length,
          page: 1,
          pageSize: 20,
        });
        return;
      }
      if (method === 'PUT' && path === '/api/v1/notifications/read') {
        markReadPayload = req.postDataJSON() as { ids?: number[] };
        const ids = new Set(markReadPayload.ids || []);
        for (const item of notifications) {
          if (ids.has(item.id)) {
            item.read = true;
          }
        }
        await json(route, {
          code: 0,
          message: 'marked as read',
          affected_rows: markReadPayload.ids?.length || 0,
        });
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects');
    await expect(page.getByRole('heading', { name: '项目列表' })).toBeVisible();

    await page.getByRole('button', { name: '通知中心' }).click();

    const notificationDrawer = page.getByRole('dialog', { name: '消息中心' });
    await expect(notificationDrawer.getByRole('heading', { name: '消息中心' })).toBeVisible();
    await expect(notificationDrawer.getByText('缺陷状态已更新')).toBeVisible();
    await expect(notificationDrawer.getByText('BUG-101 已进入待验证')).toBeVisible();

    await notificationDrawer.getByRole('button', { name: /^标记已读$/ }).click();

    await expect.poll(() => markReadPayload).not.toBeNull();
    expect(markReadPayload?.ids).toEqual([901]);
  });
});

test.describe('PRD v3.0 yunxiao browser e2e', () => {
  test('个人信息页支持云效凭证连通性测试并读取扩展配置', async ({ page }) => {
    await seedAuth(page);

    let yunxiaoTestPayload: any = null;
    const credentials: any[] = [
      {
        id: 801,
        userId: 1,
        name: '云效主账号',
        type: 'pat',
        provider: 'yunxiao',
        extraConfig: JSON.stringify({
          organizationId: 'org-e2e',
          workspaceId: 'space-e2e',
          endpoint: 'https://openapi-rdc.aliyuncs.com',
        }),
        maskedValue: 'toke****-xyz',
        lastUsedAt: null,
        createdAt: new Date().toISOString(),
      },
    ];

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/users/me') {
        await json(route, ok({
          ...MOCK_USER,
          agentTypes: 'backend,test',
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/notification-preferences') {
        await json(route, ok([
          { id: 1, category: 'defect_assigned', channels: 'in_app,email' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok(credentials));
        return;
      }
      if (method === 'POST' && path === '/api/v1/integrations/yunxiao/test-connection') {
        yunxiaoTestPayload = req.postDataJSON();
        await json(route, ok({
          success: true,
          message: '云效连接成功(mock)',
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/profile');
    await expect(page.getByRole('heading', { name: '管理员' })).toBeVisible();

    await page.getByRole('tab', { name: '访问凭证' }).click();
    await expect(page.getByText('云效主账号')).toBeVisible();

    await page.getByRole('button', { name: '测试云效' }).first().click();
    await expect(page.getByText('云效连接成功(mock)')).toBeVisible();
    await expect.poll(() => yunxiaoTestPayload).not.toBeNull();
    expect(yunxiaoTestPayload.credentialId).toBe(801);
    expect(yunxiaoTestPayload.organizationId).toBe('org-e2e');
    expect(yunxiaoTestPayload.endpoint).toBe('https://openapi-rdc.aliyuncs.com');
  });

  test('仓库管理页支持云效仓库导入并自动回填凭证扩展配置', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const credentials = [
      {
        id: 11,
        name: 'Yunxiao PAT',
        provider: 'yunxiao',
        extraConfig: JSON.stringify({
          organizationId: 'org-xyz',
          endpoint: 'https://openapi-rdc.aliyuncs.com',
        }),
        maskedValue: 'toke****',
      },
    ];

    const repos: any[] = [];
    const yunxiaoRepos = [
      {
        externalId: 'repo-1',
        name: 'cloud-repo-a',
        repoUrl: 'https://codeup.aliyun.com/acme/cloud-repo-a.git',
        defaultBranch: 'main',
      },
    ];
    let importPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v3.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/repos') {
        await json(route, ok(repos));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok(credentials));
        return;
      }
      if (method === 'GET' && path === '/api/v1/integrations/yunxiao/repos') {
        await json(route, ok({
          list: yunxiaoRepos,
          page: 1,
          size: 100,
          total: 1,
          organizationId: 'org-xyz',
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/repos/import/yunxiao') {
        importPayload = req.postDataJSON();
        repos.push({
          id: 701,
          projectId: 101,
          name: yunxiaoRepos[0].name,
          repoUrl: yunxiaoRepos[0].repoUrl,
          sourceType: 'yunxiao',
          credentialId: 11,
          agentTypes: 'backend,test',
          defaultBranch: 'main',
          description: '',
        });
        await json(route, ok({
          summary: {
            total: 1,
            imported: 1,
            skipped: 0,
            failed: 0,
          },
          imported: [{ name: yunxiaoRepos[0].name, repoUrl: yunxiaoRepos[0].repoUrl }],
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/repos');
    await expect(page.getByRole('heading', { name: '仓库管理' })).toBeVisible();

    await page.getByRole('button', { name: '从云效导入' }).click();

    const modal = page.locator('.ant-modal').last();
    await expect(modal.getByLabel('组织ID（可选）')).toHaveValue('org-xyz');
    await expect(modal.getByLabel('API Endpoint（可选）')).toHaveValue('https://openapi-rdc.aliyuncs.com');

    await modal.getByRole('button', { name: '拉取仓库' }).click();
    await expect(modal.getByRole('cell', { name: 'cloud-repo-a', exact: true })).toBeVisible();
    await modal.locator('.ant-table-row .ant-checkbox-input').first().check();

    await modal.getByRole('button', { name: '导入选中仓库' }).click();
    await expect(page.getByText(/导入完成：新增 1，跳过 0，失败 0/)).toBeVisible();
    await expect.poll(() => importPayload).not.toBeNull();
    expect(importPayload.credentialId).toBe(11);
    expect(importPayload.items).toHaveLength(1);
    expect(importPayload.items[0].repoUrl).toBe('https://codeup.aliyun.com/acme/cloud-repo-a.git');
  });


  test('仓库导入仅显示云效凭证并支持本地搜索与当前页勾选导入', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const credentials = [
      {
        id: 11,
        name: 'Yunxiao Import',
        provider: 'yunxiao',
        extraConfig: JSON.stringify({
          organizationId: 'org-xyz',
          endpoint: 'https://openapi-rdc.aliyuncs.com',
        }),
        maskedValue: 'yx****',
      },
      {
        id: 12,
        name: 'GitHub Token',
        provider: 'github',
        maskedValue: 'ghp_****',
      },
      {
        id: 13,
        name: 'Generic Token',
        provider: 'generic',
        maskedValue: 'sk-****',
      },
    ];

    const repos = [];
    const yunxiaoRepos = [
      { externalId: 'r-1', name: 'alpha-api', repoUrl: 'https://codeup.aliyun.com/acme/alpha-api.git', defaultBranch: 'main' },
      { externalId: 'r-2', name: 'beta-api', repoUrl: 'https://codeup.aliyun.com/acme/beta-api.git', defaultBranch: 'main' },
      { externalId: 'r-3', name: 'gamma-web', repoUrl: 'https://codeup.aliyun.com/acme/gamma-web.git', defaultBranch: 'main' },
      { externalId: 'r-4', name: 'delta-web', repoUrl: 'https://codeup.aliyun.com/acme/delta-web.git', defaultBranch: 'main' },
      { externalId: 'r-5', name: 'omega-worker', repoUrl: 'https://codeup.aliyun.com/acme/omega-worker.git', defaultBranch: 'main' },
      { externalId: 'r-6', name: 'zeta-worker', repoUrl: 'https://codeup.aliyun.com/acme/zeta-worker.git', defaultBranch: 'main' },
      { externalId: 'r-7', name: 'theta-job', repoUrl: 'https://codeup.aliyun.com/acme/theta-job.git', defaultBranch: 'main' },
      { externalId: 'r-8', name: 'iota-job', repoUrl: 'https://codeup.aliyun.com/acme/iota-job.git', defaultBranch: 'main' },
      { externalId: 'r-9', name: 'kappa-service', repoUrl: 'https://codeup.aliyun.com/acme/kappa-service.git', defaultBranch: 'main' },
    ];
    let listReposRequestCount = 0;
    let importPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({ items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }] }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([{ id: 301, name: 'Sprint 5', status: 'active' }]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG', description: 'v5.1' },
          members: [{ id: 1, userId: 1, role: 'project_admin', username: 'admin', nickname: '管理员' }],
          iterations: [{ id: 301, name: 'Sprint 5', status: 'active', startDate: '2026-04-01T00:00:00Z', endDate: '2026-04-30T00:00:00Z' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/repos') {
        await json(route, ok(repos));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok(credentials));
        return;
      }
      if (method === 'GET' && path === '/api/v1/integrations/yunxiao/repos') {
        listReposRequestCount += 1;
        await json(route, ok({
          list: yunxiaoRepos,
          page: 1,
          size: 100,
          total: yunxiaoRepos.length,
          organizationId: 'org-xyz',
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/repos/import/yunxiao') {
        importPayload = req.postDataJSON();
        await json(route, ok({
          summary: {
            total: importPayload.items.length,
            imported: importPayload.items.length,
            skipped: 0,
            failed: 0,
          },
          imported: importPayload.items,
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/repos');
    await page.getByRole('button', { name: '从云效导入' }).click();

    const modal = page.locator('.ant-modal').last();
    await modal.getByLabel('云效凭证').click();
    const dropdown = page.locator('.ant-select-dropdown').last();
    await expect(dropdown).toContainText('Yunxiao Import');
    await expect(dropdown).not.toContainText('GitHub Token');
    await expect(dropdown).not.toContainText('Generic Token');
    await page.keyboard.press('Escape');

    await modal.getByRole('button', { name: '拉取仓库' }).click();
    await expect.poll(() => listReposRequestCount).toBe(1);
    await expect(modal.getByRole('checkbox', { name: /选择当前页/ })).not.toBeVisible();
    await expect(modal.getByRole('cell', { name: 'alpha-api', exact: true })).toBeVisible();
    await expect(modal.locator('tbody input[type="checkbox"]:checked')).toHaveCount(0);

    const localSearchInput = modal.getByPlaceholder('对已拉取仓库做本地过滤');
    await localSearchInput.fill('worker');
    await expect(modal.getByRole('cell', { name: 'omega-worker', exact: true })).toBeVisible();
    await expect(modal.getByRole('cell', { name: 'zeta-worker', exact: true })).toBeVisible();
    await expect(modal.getByRole('cell', { name: 'alpha-api', exact: true })).toHaveCount(0);
    await expect.poll(() => listReposRequestCount).toBe(1);

    await localSearchInput.fill('');
    await expect(modal.getByRole('cell', { name: 'alpha-api', exact: true })).toBeVisible();
    await modal.locator('tbody').getByRole('checkbox').nth(0).check();
    await modal.locator('.ant-pagination-item').filter({ hasText: '2' }).click();
    await expect(modal.getByRole('cell', { name: 'kappa-service', exact: true })).toBeVisible();
    await expect(modal.locator('tbody input[type="checkbox"]:checked')).toHaveCount(0);
    await modal.locator('tbody').getByRole('checkbox').nth(0).check();

    await modal.getByRole('button', { name: '导入选中仓库' }).click();
    await expect.poll(() => importPayload).not.toBeNull();
    expect(importPayload.credentialId).toBe(11);
    expect(importPayload.items).toHaveLength(1);
    expect(importPayload.items[0].name).toBe('kappa-service');
  });

  test('成员管理页支持云效成员导入并自动回填凭证扩展配置', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const credentials = [
      {
        id: 12,
        name: 'Yunxiao Members',
        provider: 'yunxiao',
        extraConfig: JSON.stringify({
          organizationId: 'org-members',
          endpoint: 'https://openapi-rdc.aliyuncs.com',
        }),
        maskedValue: 'memb****',
      },
    ];

    const currentMembers: any[] = [
      {
        id: 1,
        userId: 1,
        role: 'project_admin',
        username: 'admin',
        nickname: '管理员',
      },
      {
        id: 2,
        userId: 2,
        role: 'viewer',
        username: 'member2',
        nickname: '已存在成员',
      },
    ];
    const yunxiaoMembers = [
      { externalId: 'u-1', name: 'Member One', email: 'member1@example.com', role: 'admin' },
      { externalId: 'u-2', name: 'Member Two', username: 'member2', role: 'developer' },
      { externalId: 'u-3', name: 'Member Three', email: 'notfound@example.com', role: 'tester' },
    ];
    let importPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v3.0',
          },
          members: currentMembers,
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok(credentials));
        return;
      }
      if (method === 'GET' && path === '/api/v1/users') {
        await json(route, ok({
          list: [
            { id: 2, username: 'member2', email: 'member2@example.com', nickname: 'member2' },
            { id: 3, username: 'member1', email: 'member1@example.com', nickname: 'member1' },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/integrations/yunxiao/members') {
        await json(route, ok({
          list: yunxiaoMembers,
          page: 1,
          size: 100,
          total: 2,
          organizationId: 'org-members',
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/members/import/yunxiao') {
        importPayload = req.postDataJSON();
        await json(route, ok({
          summary: {
            total: 3,
            added: 1,
            updated: 1,
            skipped: 0,
            unmatched: 1,
            failed: 0,
          },
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/members');
    await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible();

    await page.getByRole('button', { name: '从云效导入' }).click();

    const modal = page.locator('.ant-modal').last();
    await expect(modal.getByLabel('组织ID（可选）')).toHaveValue('org-members');
    await expect(modal.getByLabel('API Endpoint（可选）')).toHaveValue('https://openapi-rdc.aliyuncs.com');

    await modal.getByRole('button', { name: '拉取成员' }).click();
    await expect(modal.getByText('Member One')).toBeVisible();
    await expect(modal.getByText('将新增', { exact: true })).toBeVisible();
    await expect(modal.getByText('将更新', { exact: true })).toBeVisible();
    await expect(modal.getByText('本地未匹配', { exact: true })).toBeVisible();
    await expect(modal.getByText(/预估：新增 1，更新 1，已存在 0，未匹配 1/)).toBeVisible();

    const updateSwitch = modal.getByRole('switch');
    if ((await updateSwitch.getAttribute('aria-checked')) !== 'true') {
      await updateSwitch.click();
    }

    await modal.getByRole('button', { name: '导入选中成员' }).click();
    await expect(page.getByText(/导入完成：新增 1，更新 1，未匹配 1/)).toBeVisible();
    await expect.poll(() => importPayload).not.toBeNull();
    expect(importPayload.credentialId).toBe(12);
    expect(importPayload.updateExisting).toBe(true);
    expect(importPayload.items).toHaveLength(3);
  });

  test('成员导入未匹配结果支持导出', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const credentials = [
      {
        id: 12,
        name: 'Yunxiao Members',
        provider: 'yunxiao',
        extraConfig: JSON.stringify({
          organizationId: 'org-members',
          endpoint: 'https://openapi-rdc.aliyuncs.com',
        }),
        maskedValue: 'memb****',
      },
    ];

    const currentMembers: any[] = [
      {
        id: 1,
        userId: 1,
        role: 'project_admin',
        username: 'admin',
        nickname: '管理员',
      },
    ];
    const yunxiaoMembers = [
      { externalId: 'u-1', name: 'Member One', email: 'notfound@example.com', role: 'tester' },
    ];

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v3.0',
          },
          members: currentMembers,
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        await json(route, ok(credentials));
        return;
      }
      if (method === 'GET' && path === '/api/v1/users') {
        await json(route, ok({ list: [] }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/integrations/yunxiao/members') {
        await json(route, ok({
          list: yunxiaoMembers,
          page: 1,
          size: 100,
          total: 1,
          organizationId: 'org-members',
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/members/import/yunxiao') {
        await json(route, ok({
          summary: {
            total: 1,
            added: 0,
            updated: 0,
            skipped: 0,
            unmatched: 1,
            failed: 0,
          },
          unmatched: [
            {
              externalId: 'u-1',
              name: 'Member One',
              email: 'notfound@example.com',
              role: 'tester',
              reason: '未匹配到本地用户',
            },
          ],
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/members');
    await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible();
    await page.getByRole('button', { name: '从云效导入' }).click();

    const modal = page.locator('.ant-modal').last();
    await modal.getByRole('button', { name: '拉取成员' }).click();
    await expect(modal.getByText('Member One')).toBeVisible();

    await modal.getByRole('button', { name: '导入选中成员' }).click();
    await expect(page.getByText(/导入完成：新增 0，更新 0，未匹配 1/)).toBeVisible();
    await expect(modal.getByRole('button', { name: '导出未匹配成员' })).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      modal.getByRole('button', { name: '导出未匹配成员' }).click(),
    ]);
    expect(download.suggestedFilename()).toContain('yunxiao-unmatched-members');
  });

  test('项目AI配置支持手动模型并提示非目录模型', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const aiConfigs: any[] = [];
    let createPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v3.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/ai-configs') {
        await json(route, ok(aiConfigs));
        return;
      }
      if (method === 'GET' && path === '/api/v1/ai/providers') {
        await json(route, ok([
          {
            name: 'OpenAI',
            value: 'openai',
            models: [
              { name: 'gpt-5.4', endpoint: 'https://api.openai.com/v1' },
            ],
          },
          {
            name: '自定义',
            value: 'custom',
            models: [],
          },
        ]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/ai-configs') {
        createPayload = req.postDataJSON();
        aiConfigs.push({
          id: 901,
          projectId: 101,
          ...createPayload,
          isDefault: true,
        });
        await json(route, ok({
          id: 901,
          projectId: 101,
          ...createPayload,
          isDefault: true,
        }), 201);
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/ai-configs');
    await expect(page.getByRole('heading', { name: 'AI 配置' })).toBeVisible();

    await page.getByRole('button', { name: '添加配置' }).click();
    const modal = page.locator('.ant-modal').last();
    await modal.getByLabel('AI厂商').click();
    await page.getByText('OpenAI', { exact: true }).last().click();
    await modal.getByRole('button', { name: '手动填写模型' }).click();
    await modal.getByLabel('模型名称').fill('gpt-5.5-exp-manual');
    await modal.getByLabel('API密钥').fill('sk-test-123456');
    await modal.getByRole('button', { name: /保\s*存/ }).click();

    await expect(page.getByText('当前厂商/模型不在目录中，将按非目录模型保存')).toBeVisible();
    await expect(page.getByText('AI配置已添加')).toBeVisible();
    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload.provider).toBe('openai');
    expect(createPayload.modelName).toBe('gpt-5.5-exp-manual');
  });

  test('项目AI配置页在目录为空时给出初始化提示并允许手动填写', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v3.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/ai-configs') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/ai/providers') {
        await json(route, ok([
          {
            name: '自定义',
            value: 'custom',
            models: [],
          },
        ]));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/ai-configs');
    await expect(page.getByText('AI 目录未初始化')).toBeVisible();

    await page.getByRole('button', { name: '添加配置' }).click();
    const modal = page.locator('.ant-modal').last();
    await expect(modal.getByRole('textbox', { name: 'AI厂商' })).toBeVisible();
    await expect(modal.getByRole('textbox', { name: '模型名称' })).toBeVisible();
  });

  test('AI目录管理页支持新增厂商、展开模型并测试可用性', async ({ page }) => {
    await seedAuth(page);

    const providers: any[] = [
      {
        id: 1,
        providerKey: 'openai',
        displayName: 'OpenAI',
        defaultEndpoint: 'https://api.openai.com/v1',
        status: 'active',
        sortOrder: 10,
      },
    ];
    const models: any[] = [
      {
        id: 101,
        providerKey: 'openai',
        modelName: 'gpt-5.4',
        endpoint: 'https://api.openai.com/v1',
        capabilityTags: 'chat,reasoning,code',
        status: 'active',
        isDefault: true,
        sortOrder: 10,
      },
    ];
    let providerCreatePayload: any = null;
    let modelUpdatePayload: any = null;
    let modelTestPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/admin/ai/providers') {
        await json(route, ok(providers));
        return;
      }
      if (method === 'GET' && path === '/api/v1/admin/ai/models') {
        await json(route, ok(models));
        return;
      }
      if (method === 'POST' && path === '/api/v1/admin/ai/providers') {
        providerCreatePayload = req.postDataJSON();
        providers.push({
          id: 2,
          ...providerCreatePayload,
        });
        await json(route, ok({ id: 2, ...providerCreatePayload }), 201);
        return;
      }
      if (method === 'PUT' && path === '/api/v1/admin/ai/models/101') {
        modelUpdatePayload = req.postDataJSON();
        models[0] = {
          ...models[0],
          ...modelUpdatePayload,
        };
        await json(route, ok(models[0]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/admin/ai/models/101/test') {
        modelTestPayload = req.postDataJSON();
        await json(route, ok({
          success: true,
          latencyMs: 123,
          message: '模型可用性测试成功',
          endpoint: 'https://api.openai.com/v1',
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/ai-catalog');
    await expect(page.getByRole('heading', { name: 'AI目录管理' })).toBeVisible();
    await expect(page.getByText('AI 厂商目录')).toBeVisible();
    await expect(page.getByText('AI 目录以数据库为唯一来源')).toBeVisible();

    await page.getByRole('button', { name: '新增厂商' }).click();
    {
      const modal = page.locator('.ant-modal').last();
      await modal.getByLabel('厂商标识').fill('dashscope');
      await modal.getByLabel('显示名称').fill('阿里云 DashScope');
      await modal.getByLabel('默认端点').fill('https://dashscope.aliyuncs.com/compatible-mode/v1');
      await modal.getByRole('button', { name: /保\s*存/ }).click();
    }
    await expect(page.getByText('AI厂商目录已创建')).toBeVisible();
    await expect.poll(() => providerCreatePayload).not.toBeNull();
    expect(providerCreatePayload.providerKey).toBe('dashscope');

    await page.getByRole('button', { name: '展开模型' }).first().click();
    await page.locator('tr', { hasText: 'gpt-5.4' }).getByRole('button', { name: '编辑' }).click();
    {
      const modal = page.locator('.ant-modal').last();
      await modal.getByLabel('模型名称').fill('gpt-5.4-tuned');
      await modal.getByLabel('能力标签（可选）').fill('chat,reasoning');
      await modal.getByRole('button', { name: /保\s*存/ }).click();
    }
    await expect(page.getByText('AI模型目录已更新')).toBeVisible();
    await expect.poll(() => modelUpdatePayload).not.toBeNull();
    expect(modelUpdatePayload.providerKey).toBe('openai');
    expect(modelUpdatePayload.modelName).toBe('gpt-5.4-tuned');

    await page.locator('tr', { hasText: 'gpt-5.4-tuned' }).getByRole('button', { name: '测试可用性' }).click();
    const testModal = page.getByRole('dialog', { name: '测试模型可用性 - gpt-5.4-tuned' });
    {
      await testModal.getByLabel('临时 API Key').fill('sk-test-123');
      await testModal.getByRole('button', { name: '开始测试' }).click();
    }
    await expect.poll(() => modelTestPayload).not.toBeNull();
    expect(modelTestPayload.apiKey).toBe('sk-test-123');
    await expect(testModal.getByText('测试成功', { exact: true })).toBeVisible();
    await expect(testModal.getByText('耗时：123 ms')).toBeVisible();
  });

  test('用户管理页支持按项目归属筛选并可管理员重置密码', async ({ page }) => {
    await seedAuth(page);

    let lastProjectFilter: string | null = null;
    let resetUserId: string | null = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const url = new URL(req.url());
      const path = url.pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/users') {
        lastProjectFilter = url.searchParams.get('projectId');
        const list = lastProjectFilter === '101'
          ? [{
              id: 2,
              username: 'project_member',
              nickname: '项目成员',
              email: 'member@example.com',
              platformRole: 'member',
              mustChangePassword: false,
              createdAt: '2026-04-10T12:00:00Z',
            }]
          : [{
              id: 2,
              username: 'project_member',
              nickname: '项目成员',
              email: 'member@example.com',
              platformRole: 'member',
              mustChangePassword: false,
              createdAt: '2026-04-10T12:00:00Z',
            }, {
              id: 3,
              username: 'other_member',
              nickname: '其他成员',
              email: 'other@example.com',
              platformRole: 'member',
              mustChangePassword: false,
              createdAt: '2026-04-10T12:00:00Z',
            }];
        await json(route, ok({ list, total: list.length, page: 1, size: 20 }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/users/2/reset-password') {
        resetUserId = '2';
        await json(route, ok({
          id: 2,
          temporaryPassword: 'TempPassword@123456',
          mustChangePassword: true,
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/users');
    await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible();

    await page.getByLabel('按项目归属筛选').click();
    await page.getByText('BugAgent 平台 (BUG)', { exact: true }).click();
    await expect.poll(() => lastProjectFilter).toBe('101');
    await expect(page.getByText('project_member')).toBeVisible();
    await expect(page.getByText('other_member')).toHaveCount(0);

    const row = page.locator('tr', { hasText: 'project_member' });
    await row.getByRole('button', { name: '重置密码' }).click();

    await expect.poll(() => resetUserId).toBe('2');
    const resetModal = page.locator('.ant-modal-confirm');
    await expect(resetModal.locator('.ant-modal-confirm-title')).toHaveText('已为 project_member 重置密码');
    await expect(resetModal.getByText('TempPassword@123456')).toBeVisible();
  });

  test('平台凭证管理页支持创建带项目授权的平台凭证', async ({ page }) => {
    await seedAuth(page);

    let createPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const url = new URL(req.url());
      const path = url.pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/admin/platform-credentials') {
        await json(route, ok([]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/admin/platform-credentials') {
        createPayload = req.postDataJSON();
        await json(route, ok({
          id: 1,
          ...createPayload,
          scope: 'platform',
          status: createPayload.status || 'active',
          maskedValue: 'ghp_****form',
        }), 201);
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/platform-credentials');
    await expect(page.getByRole('heading', { name: '平台凭证管理' })).toBeVisible();

    await page.getByRole('button', { name: '新增平台凭证' }).click();
    const modal = page.locator('.ant-modal').last();
    await modal.getByLabel('凭证名称').fill('平台 GitHub 凭证');
    await modal.getByLabel('允许使用的项目').click();
    await page.getByText('BugAgent 平台 (BUG)', { exact: true }).click();
    await modal.getByLabel('凭证内容').fill('ghp_platform_secret');
    await modal.getByRole('button', { name: /保\s*存/ }).click();

    await expect(page.getByText('平台凭证已创建')).toBeVisible();
    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload.name).toBe('平台 GitHub 凭证');
    expect(createPayload.allowedProjectIds).toEqual([101]);
    expect(createPayload.provider).toBe('github');
    expect(createPayload.type).toBe('pat');
  });

  test('平台配置页支持保存 SMTP 配置并发送测试邮件', async ({ page }) => {
    await seedAuth(page);

    let savePayload: any = null;
    let testPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/admin/platform-settings/email') {
        await json(route, ok({
          smtpHost: 'smtp.example.com',
          smtpPort: 587,
          smtpUser: 'robot@example.com',
          smtpFrom: 'BugAgent <noreply@example.com>',
          passwordConfigured: true,
        }));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/admin/platform-settings/email') {
        savePayload = req.postDataJSON();
        await json(route, ok({
          ...savePayload,
          passwordConfigured: true,
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/admin/platform-settings/email/test') {
        testPayload = req.postDataJSON();
        await json(route, ok({ sent: true }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/platform-settings');
    await expect(page.getByRole('heading', { name: '平台配置' })).toBeVisible();
    await expect(page.getByText('密码已配置')).toBeVisible();

    await page.getByLabel('SMTP Host').fill('smtp.db.example.com');
    await page.getByLabel('SMTP Port').fill('2525');
    await page.getByLabel('SMTP 用户名').fill('mailer@example.com');
    await page.getByLabel('发件人').fill('BugAgent <mailer@example.com>');
    await page.getByLabel('SMTP 密码').fill('new-smtp-secret');
    await page.getByRole('button', { name: '保存配置' }).click();

    await expect(page.getByText('平台邮件配置已保存')).toBeVisible();
    await expect.poll(() => savePayload).not.toBeNull();
    expect(savePayload.smtpHost).toBe('smtp.db.example.com');
    expect(savePayload.smtpPort).toBe(2525);
    expect(savePayload.smtpPassword).toBe('new-smtp-secret');

    await page.getByLabel('测试接收邮箱').fill('receiver@example.com');
    await page.getByRole('button', { name: '发送测试邮件' }).click();

    await expect(page.getByText('测试邮件发送成功')).toBeVisible();
    await expect.poll(() => testPayload).not.toBeNull();
    expect(testPayload.to).toBe('receiver@example.com');
    expect(testPayload.smtpHost).toBe('smtp.db.example.com');
  });

  test('项目仓库页按项目拉取凭证并展示平台与个人来源标识', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    let credentialsProjectID: string | null = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const url = new URL(req.url());
      const path = url.pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v4.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/repos') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/credentials') {
        credentialsProjectID = url.searchParams.get('projectId');
        await json(route, ok([
          {
            id: 11,
            userId: 1,
            name: '平台 GitHub',
            type: 'pat',
            provider: 'github',
            scope: 'platform',
            status: 'active',
            maskedValue: 'ghp_****plat',
            allowedProjectIds: [101],
          },
          {
            id: 12,
            userId: 1,
            name: '我的 GitHub',
            type: 'pat',
            provider: 'github',
            scope: 'personal',
            status: 'active',
            maskedValue: 'ghp_****self',
          },
        ]));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/repos');
    await expect(page.getByRole('heading', { name: '仓库管理' })).toBeVisible();

    await page.getByRole('button', { name: '添加仓库' }).click();
    const modal = page.locator('.ant-modal').last();
    await modal.getByLabel('访问凭证').click();
    await expect(page.getByText('平台 GitHub')).toBeVisible();
    await expect(page.getByText('我的 GitHub')).toBeVisible();
    const optionTexts = await page.locator('.ant-select-item-option').allTextContents();
    expect(optionTexts.join(' ')).toContain('平台');
    expect(optionTexts.join(' ')).toContain('个人');
    await expect.poll(() => credentialsProjectID).toBe('101');
  });

  test('项目通知管理页支持创建 Webhook 并保存单选策略', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const webhooks: any[] = [];
    const policies: any[] = [
      { id: 1, projectId: 101, category: 'defect_assigned', inAppEnabled: true, emailEnabled: true, webhookId: null },
      { id: 2, projectId: 101, category: 'defect_status_change', inAppEnabled: true, emailEnabled: true, webhookId: null },
      { id: 3, projectId: 101, category: 'defect_mention', inAppEnabled: true, emailEnabled: true, webhookId: null },
      { id: 4, projectId: 101, category: 'defect_due_soon', inAppEnabled: true, emailEnabled: true, webhookId: null },
      { id: 5, projectId: 101, category: 'iteration_start', inAppEnabled: true, emailEnabled: false, webhookId: null },
      { id: 6, projectId: 101, category: 'iteration_end', inAppEnabled: true, emailEnabled: true, webhookId: null },
      { id: 7, projectId: 101, category: 'collaboration_complete', inAppEnabled: true, emailEnabled: false, webhookId: null },
    ];
    let createPayload: any = null;
    let policySavePayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([
          { id: 301, name: 'Sprint 5', status: 'active' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: {
            id: 101,
            name: 'BugAgent 平台',
            code: 'BUG',
            description: 'v4.0',
          },
          members: [{ id: 1, nickname: '管理员' }],
          iterations: [
            {
              id: 301,
              name: 'Sprint 5',
              status: 'active',
              startDate: '2026-04-01T00:00:00Z',
              endDate: '2026-04-30T00:00:00Z',
            },
          ],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/notification-webhooks') {
        await json(route, ok(webhooks));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/notification-policies') {
        await json(route, ok(policies));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/notification-webhooks') {
        createPayload = req.postDataJSON();
        webhooks.push({
          id: 901,
          projectId: 101,
          ...createPayload,
        });
        await json(route, ok({
          id: 901,
          projectId: 101,
          ...createPayload,
        }), 201);
        return;
      }
      if (method === 'PUT' && path === '/api/v1/projects/101/notification-policies') {
        policySavePayload = req.postDataJSON();
        for (const update of policySavePayload.policies || []) {
          const target = policies.find((item) => item.category === update.category);
          if (target) {
            Object.assign(target, update);
          }
        }
        await json(route, ok(policies));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/notifications');
    await expect(page.getByRole('heading', { name: '通知管理' })).toBeVisible();

    await page.getByRole('button', { name: '新增 Webhook' }).click();
    const modal = page.locator('.ant-modal').last();
    await modal.getByLabel('Webhook 名称').fill('飞书机器人');
    await modal.getByLabel('Webhook 地址').fill('https://hooks.example.com/feishu');
    await modal.getByLabel('签名密钥（可选）').fill('hook-secret');
    await modal.getByRole('button', { name: /保\s*存/ }).click();

    await expect(page.getByText('项目 Webhook 已创建')).toBeVisible();
    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload.name).toBe('飞书机器人');

    const mentionRow = page.locator('tr', { hasText: '评论中被提及' });
    await mentionRow.locator('.ant-select').click();
    await page.getByText('飞书机器人', { exact: true }).last().click();

    await page.getByRole('button', { name: '保存通知策略' }).click();
    await expect(page.getByText('项目通知策略已保存')).toBeVisible();
    await expect.poll(() => policySavePayload).not.toBeNull();
    expect(policySavePayload.policies).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          category: 'defect_mention',
          webhookId: 901,
          inAppEnabled: true,
          emailEnabled: true,
        }),
      ]),
    );
  });

  test('信号接入页支持创建阿里云日志连接器并查看同步记录', async ({ page }) => {
    await seedAuth(page);

    const connectors: any[] = [];
    const syncRecords: any[] = [];
    let createPayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG', description: '质量平台', status: 'active' },
          members: [{ id: 1, userId: 1, username: 'admin', nickname: '管理员' }],
          iterations: [{ id: 201, name: 'Sprint 5', status: 'active' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/integrations') {
        await json(route, ok(connectors));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/integrations') {
        createPayload = req.postDataJSON();
        connectors.push({
          id: 1,
          projectId: 101,
          inboundToken: 'sig_demo',
          inboundPath: '/api/v1/inbound/connectors/sig_demo',
          hasConfig: true,
          createdBy: 1,
          createdAt: '2026-04-12T00:00:00Z',
          updatedAt: '2026-04-12T00:00:00Z',
          lastSyncStatus: '',
          ...createPayload,
        });
        await json(route, ok(connectors[0]), 201);
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/integrations/1/test') {
        await json(route, ok({ ok: true }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/integrations/1/sync') {
        syncRecords.unshift({
          id: 901,
          connectorId: 1,
          triggerType: 'aliyun_log_pull',
          status: 'success',
          importedCount: 2,
          clusteredCount: 2,
          startedAt: '2026-04-12T12:00:00Z',
          createdAt: '2026-04-12T12:00:00Z',
        });
        connectors[0].lastSyncStatus = 'success';
        connectors[0].lastSyncAt = '2026-04-12T12:00:00Z';
        await json(route, ok({ importedCount: 2, clusteredCount: 2, syncRecordId: 901 }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/integrations/1/sync-records') {
        await json(route, ok(syncRecords));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/integrations');
    await expect(page.locator('.ant-card-head-title', { hasText: '信号接入' }).first()).toBeVisible();

    await page.getByRole('button', { name: '新增连接器' }).click();
    const modal = page.locator('.ant-modal').last();
    await modal.getByTestId('connector-name-input').fill('阿里云日志 Android');
    await modal.getByTestId('connector-type-select').click();
    await page.getByText('阿里云日志', { exact: true }).click();
    await modal.getByTestId('connector-aliyun-endpoint').fill('https://cn-hangzhou.log.aliyuncs.com');
    await modal.getByTestId('connector-aliyun-project').fill('mobile-app');
    await modal.getByTestId('connector-aliyun-logstore').fill('mobile-error');
    await modal.getByTestId('connector-aliyun-query').fill('level:error');
    await modal.getByTestId('connector-aliyun-ak').fill('demo-ak');
    await modal.getByTestId('connector-aliyun-sk').fill('demo-sk');
    await modal.getByTestId('connector-aliyun-from-minutes').fill('30');
    await modal.getByTestId('connector-aliyun-lines').fill('20');
    await page.locator('.ant-modal-footer .ant-btn-primary').last().click();

    await expect(page.getByText('接入连接器已创建')).toBeVisible();
    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload.type).toBe('aliyun_log');
    expect(createPayload.config).toMatchObject({
      endpoint: 'https://cn-hangzhou.log.aliyuncs.com',
      project: 'mobile-app',
      logstore: 'mobile-error',
      query: 'level:error',
      accessKeyId: 'demo-ak',
      accessKeySecret: 'demo-sk',
      fromMinutes: 30,
      lines: 20,
    });

    const row = page.locator('tr', { hasText: '阿里云日志 Android' });
    await row.getByRole('button', { name: '同步' }).click();
    await expect(page.getByText('阿里云日志同步完成')).toBeVisible();
    await row.getByRole('button', { name: '记录' }).click();
    await expect(page.getByText('aliyun_log_pull')).toBeVisible();
  });

  test('项目问题池页支持筛选、查看信号、指派、合并并转缺陷', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const cluster = {
      id: 501,
      projectId: 101,
      clusterKey: 'fp-1',
      title: '启动崩溃',
      summary: '用户打开 App 后立即闪退',
      status: 'new',
      signalCount: 1,
      affectedUserCount: 3,
      severity: 'major',
      priority: 'P1',
      anomalyLevel: 'watch',
      platform: 'android',
      appVersion: '1.2.3',
      buildNumber: '1203001',
      releaseMatchCount: 1,
      ownerUserId: null,
      linkedDefectId: null,
      lastSeenAt: '2026-04-12T12:00:00Z',
      firstSeenAt: '2026-04-12T11:55:00Z',
      createdAt: '2026-04-12T11:55:00Z',
      updatedAt: '2026-04-12T12:00:00Z',
      owner: null,
    };
    const targetCluster = {
      id: 502,
      projectId: 101,
      clusterKey: 'fp-2',
      title: '旧版启动崩溃',
      summary: '更早批次已经确认的启动崩溃',
      status: 'triaging',
      signalCount: 3,
      affectedUserCount: 8,
      severity: 'major',
      priority: 'P1',
      anomalyLevel: 'baseline',
      platform: 'android',
      appVersion: '1.2.0',
      buildNumber: '1200002',
      releaseMatchCount: 0,
      ownerUserId: 2,
      linkedDefectId: null,
      lastSeenAt: '2026-04-11T12:00:00Z',
      firstSeenAt: '2026-04-11T11:00:00Z',
      createdAt: '2026-04-11T11:00:00Z',
      updatedAt: '2026-04-11T12:00:00Z',
      owner: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
    };
    const convertedCluster = {
      id: 503,
      projectId: 101,
      clusterKey: 'fp-3',
      title: '支付页崩溃',
      summary: '用户进入支付页后白屏并崩溃',
      status: 'converted',
      signalCount: 2,
      affectedUserCount: 9,
      severity: 'fatal',
      priority: 'P0',
      anomalyLevel: 'high',
      platform: 'android',
      appVersion: '1.2.4',
      buildNumber: '1204001',
      releaseMatchCount: 0,
      ownerUserId: 2,
      linkedDefectId: 703,
      lastSeenAt: '2026-04-12T13:00:00Z',
      firstSeenAt: '2026-04-12T12:20:00Z',
      createdAt: '2026-04-12T12:20:00Z',
      updatedAt: '2026-04-12T13:00:00Z',
      owner: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
      defect: {
        id: 703,
        code: 'BUG-BUG-202604-003',
        title: '支付页崩溃',
        description: '来源于问题池',
        severity: 'fatal',
        priority: 'P0',
        type: 'functional',
        status: 'pending_fix',
        assigneeId: 2,
        reporterId: 1,
        createdAt: '2026-04-12T12:25:00Z',
        updatedAt: '2026-04-12T12:40:00Z',
        assignee: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
        reporter: MOCK_USER,
      },
    };
    const signals = [
      {
        id: 801,
        projectId: 101,
        connectorId: 1,
        clusterId: 501,
        sourceType: 'aliyun_log',
        sourceEventId: 'evt-1',
        sourceInstance: 'aliyun_log:1',
        title: '启动崩溃',
        description: '用户打开 App 后立即闪退',
        platform: 'android',
        appVersion: '1.2.3',
        buildNumber: '1203001',
        stackTrace: 'java.lang.IllegalStateException: startup boom\n\tat app.StartupActivity.onCreate(StartupActivity.kt:42)',
        logExcerpt: '启动页闪退\njava.lang.IllegalStateException: startup boom',
        occurrenceCount: 4,
        affectedUserCount: 3,
        firstSeenAt: '2026-04-12T11:55:00Z',
        lastSeenAt: '2026-04-12T12:00:00Z',
        rawPayloadJson: '{"message":"启动页闪退"}',
        triageStatus: 'new',
        createdAt: '2026-04-12T11:55:00Z',
        updatedAt: '2026-04-12T12:00:00Z',
      },
    ];
    const releaseMatches = [
      {
        release: {
          id: 901,
          projectId: 101,
          platform: 'android',
          appVersion: '1.2.3',
          buildNumber: '1203001',
          channel: 'prod',
          releaseTime: '2026-04-12T10:00:00Z',
          commitSha: 'abc123',
          createdAt: '2026-04-12T10:00:00Z',
          updatedAt: '2026-04-12T10:00:00Z',
        },
        matchMode: 'exact_build',
        signalCount: 1,
        affectedUserCount: 3,
        lastSeenAt: '2026-04-12T12:00:00Z',
      },
    ];
    const releases = [
      releaseMatches[0].release,
      {
        id: 902,
        projectId: 101,
        platform: 'android',
        appVersion: '1.2.0',
        buildNumber: '1200002',
        channel: 'gray',
        releaseTime: '2026-04-11T10:00:00Z',
        commitSha: 'def456',
        createdAt: '2026-04-11T10:00:00Z',
        updatedAt: '2026-04-11T10:00:00Z',
      },
    ];
    const releaseSummary = [
      {
        release: releaseMatches[0].release,
        clusterCount: 1,
        signalCount: 1,
        affectedUserCount: 3,
        lastSeenAt: '2026-04-12T12:00:00Z',
      },
    ];
    let assignPayload: any = null;
    let mergePayload: any = null;
    let listStatusFilter = '';
    let listPlatformFilter = '';
    let listAppVersionFilter = '';
    let listReleaseFilter = '';
    let listKeyword = '';
    let summaryReleaseFilter = '';
    let listAnomalyFilter = '';

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const url = new URL(req.url());
      const path = url.pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({
          items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([{ id: 301, name: 'Sprint 5', status: 'active' }]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG' },
          members: [
            { id: 1, userId: 1, nickname: '管理员', username: 'admin', role: 'project_admin' },
            { id: 2, userId: 2, nickname: '客户端负责人', username: 'client_owner', role: 'developer' },
          ],
          iterations: [{ id: 301, name: 'Sprint 5', status: 'active' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/releases') {
        await json(route, ok(releases));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/release-summary') {
        summaryReleaseFilter = url.searchParams.get('releaseId') || '';
        const filteredSummary = !summaryReleaseFilter
          ? releaseSummary
          : releaseSummary.filter((item) => String(item.release.id) === summaryReleaseFilter);
        await json(route, ok(filteredSummary));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters') {
        listStatusFilter = url.searchParams.get('status') || '';
        listPlatformFilter = url.searchParams.get('platform') || '';
        listAppVersionFilter = url.searchParams.get('appVersion') || '';
        listReleaseFilter = url.searchParams.get('releaseId') || '';
        listKeyword = url.searchParams.get('q') || '';
        listAnomalyFilter = url.searchParams.get('anomalyLevel') || '';
        const items = [cluster, targetCluster, convertedCluster].filter((item) => {
          const matchStatus = !listStatusFilter || item.status === listStatusFilter;
          const matchPlatform = !listPlatformFilter || item.platform === listPlatformFilter;
          const matchVersion = !listAppVersionFilter || `${item.appVersion || ''}`.includes(listAppVersionFilter);
          const matchRelease = !listReleaseFilter || (listReleaseFilter === '901' && item.id === 501) || (listReleaseFilter === '902' && item.id === 502);
          const matchKeyword = !listKeyword || `${item.title} ${item.summary}`.includes(listKeyword);
          const anomalyLevel = item.id === 501 ? 'watch' : item.id === 503 ? 'high' : 'baseline';
          const matchAnomaly = !listAnomalyFilter || anomalyLevel === listAnomalyFilter;
          return matchStatus && matchPlatform && matchVersion && matchRelease && matchKeyword && matchAnomaly;
        });
        await json(route, ok({ items, total: items.length }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/501/signals') {
        await json(route, ok(signals));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/503/signals') {
        await json(route, ok([
          {
            ...signals[0],
            id: 803,
            clusterId: 503,
            sourceEventId: 'evt-3',
            title: '支付页崩溃',
            description: '用户进入支付页后白屏并崩溃',
            appVersion: '1.2.4',
            buildNumber: '1204001',
            occurrenceCount: 9,
            affectedUserCount: 9,
            triageStatus: 'converted',
          },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/501/releases') {
        await json(route, ok(releaseMatches));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/503/releases') {
        await json(route, ok([]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/issue-clusters/501/assign') {
        assignPayload = req.postDataJSON();
        cluster.ownerUserId = assignPayload.ownerUserId;
        cluster.status = 'triaging';
        cluster.owner = { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' };
        await json(route, ok(cluster));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/issue-clusters/501/merge') {
        mergePayload = req.postDataJSON();
        targetCluster.signalCount += cluster.signalCount;
        targetCluster.affectedUserCount += cluster.affectedUserCount;
        targetCluster.lastSeenAt = cluster.lastSeenAt;
        cluster.status = 'clustered';
        cluster.signalCount = 0;
        cluster.affectedUserCount = 0;
        await json(route, ok({ sourceCluster: cluster, targetCluster }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/issue-clusters/501/convert') {
        cluster.status = 'converted';
        cluster.linkedDefectId = 701;
        await json(route, ok({
          cluster,
          defect: {
            id: 701,
            code: 'BUG-BUG-202604-001',
          },
        }));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/issue-clusters/502/convert') {
        targetCluster.status = 'converted';
        targetCluster.linkedDefectId = 702;
        await json(route, ok({
          cluster: targetCluster,
          defect: {
            id: 702,
            code: 'BUG-BUG-202604-002',
          },
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/701') {
        await json(route, ok({
          defect: {
            id: 701,
            code: 'BUG-BUG-202604-001',
            title: '启动崩溃',
            description: '来源于问题池',
            severity: 'major',
            priority: 'P1',
            type: 'functional',
            status: 'pending_assign',
            reporterId: 1,
            iterationId: 301,
            createdAt: '2026-04-12T12:05:00Z',
            updatedAt: '2026-04-12T12:05:00Z',
            reporter: MOCK_USER,
          },
          comments: [],
          fixTasks: [],
          reports: [],
          attachments: [],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/701/reports') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/702') {
        await json(route, ok({
          defect: {
            id: 702,
            code: 'BUG-BUG-202604-002',
            title: '旧版启动崩溃',
            description: '来源于问题池',
            severity: 'major',
            priority: 'P1',
            type: 'functional',
            status: 'pending_assign',
            reporterId: 1,
            iterationId: 301,
            createdAt: '2026-04-12T12:05:00Z',
            updatedAt: '2026-04-12T12:05:00Z',
            reporter: MOCK_USER,
          },
          comments: [],
          fixTasks: [],
          reports: [],
          attachments: [],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/702/reports') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/703') {
        await json(route, ok({
          defect: convertedCluster.defect,
          comments: [],
          fixTasks: [],
          reports: [],
          attachments: [],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/defects/703/reports') {
        await json(route, ok([]));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/issue-pool');
    await expect(page.locator('.ant-card-head-title', { hasText: '问题池' }).first()).toBeVisible();
    await expect(page.getByText('启动崩溃', { exact: true })).toBeVisible();
    const convertedRow = page.locator('tr', { hasText: '支付页崩溃' });
    await expect(convertedRow.getByText('BUG-BUG-202604-003')).toBeVisible();
    await expect(convertedRow.getByText('pending_fix')).toBeVisible();
    await expect(convertedRow.getByText('异常抬升')).toBeVisible();
    const releaseSummaryCard = page.getByTestId('issue-pool-release-summary-card');
    await expect(releaseSummaryCard.getByText('版本影响汇总')).toBeVisible();
    await expect(releaseSummaryCard.getByText('1.2.3 / 1203001')).toBeVisible();
    await expect(releaseSummaryCard.getByText('prod')).toBeVisible();

    await convertedRow.getByRole('button', { name: '详情' }).click();
    await expect(page.getByTestId('issue-pool-defect-progress-card')).toBeVisible();
    await expect(page.getByTestId('issue-pool-defect-progress-card').getByText('BUG-BUG-202604-003')).toBeVisible();
    await expect(page.getByTestId('issue-pool-defect-progress-card').getByText('pending_fix')).toBeVisible();
    await expect(page.getByTestId('issue-pool-defect-progress-card').getByText('客户端负责人')).toBeVisible();
    await page.getByTestId('issue-pool-open-defect').click();
    await expect(page).toHaveURL(/\/projects\/101\/defects\/703$/);
    await page.goto('/projects/101/issue-pool');
    await expect(page).toHaveURL(/\/projects\/101\/issue-pool$/);

    await page.getByTestId('issue-pool-release-filter').click();
    await page.getByText('android / 1.2.3 / 1203001 / prod', { exact: true }).click();
    await expect.poll(() => listReleaseFilter).toBe('901');
    await expect.poll(() => summaryReleaseFilter).toBe('901');
    await expect(page.getByText('旧版启动崩溃', { exact: true })).not.toBeVisible();

    await page.getByTestId('issue-pool-status-filter').click();
    await page.getByText('待分诊', { exact: true }).click();
    await expect.poll(() => listStatusFilter).toBe('new');

    await page.getByTestId('issue-pool-platform-filter').click();
    await page.getByText('Android', { exact: true }).click();
    await expect.poll(() => listPlatformFilter).toBe('android');

    await page.getByTestId('issue-pool-release-filter').hover();
    await page.locator('[data-testid="issue-pool-release-filter"] .ant-select-clear').click();
    await expect.poll(() => listReleaseFilter).toBe('');

    await page.getByTestId('issue-pool-anomaly-filter').click();
    await page.locator('.ant-select-item-option-content', { hasText: '关注抬升' }).click();
    await expect.poll(() => listAnomalyFilter).toBe('watch');
    await expect(page.getByText('启动崩溃', { exact: true })).toBeVisible();
    await expect(page.getByText('支付页崩溃', { exact: true })).not.toBeVisible();

    await page.getByTestId('issue-pool-version-filter').fill('1.2');
    await page.getByTestId('issue-pool-search').locator('input').press('Enter');
    await expect.poll(() => listAppVersionFilter).toBe('1.2');

    const searchInput = page.getByTestId('issue-pool-search').locator('input');
    await searchInput.fill('启动');
    await searchInput.press('Enter');
    await expect.poll(() => listKeyword).toBe('启动');

    const row = page.locator('tr', { hasText: '启动崩溃' });
    await expect(row.getByText('android')).toBeVisible();
    await expect(row.getByText('1.2.3 / 1203001')).toBeVisible();
    await expect(row.getByText('命中 1 个版本')).toBeVisible();
    await row.getByRole('button', { name: '详情' }).click();
    await expect(page.getByText('evt-1')).toBeVisible();
    const releaseCard = page.locator('.ant-drawer .ant-card').filter({ has: page.getByText('版本影响', { exact: true }) });
    await expect(releaseCard.getByText('版本影响', { exact: true })).toBeVisible();
    await expect(releaseCard.getByText('精确构建')).toBeVisible();
    await expect(releaseCard.getByText('1.2.3 / 1203001')).toBeVisible();
    await expect(page.getByText('日志上下文')).toBeVisible();
    await expect(page.getByText('启动页闪退')).toBeVisible();

    await page.getByTestId('issue-pool-drawer-assign').click();
    await page.getByTestId('issue-pool-assign-owner').click();
    await page.getByText('客户端负责人', { exact: true }).click();
    await page.locator('.ant-modal-footer .ant-btn-primary').last().click();
    await expect.poll(() => assignPayload).not.toBeNull();
    expect(assignPayload.ownerUserId).toBe(2);

    await page.getByTestId('issue-pool-drawer-merge').click();
    const mergeModal = page.locator('.ant-modal').last();
    await mergeModal.getByTestId('issue-pool-merge-target').click();
    await page.locator('.ant-select-item-option-content', { hasText: '旧版启动崩溃 (#502)' }).click();
    await mergeModal.getByLabel('原因').fill('确认是同一启动崩溃指纹');
    await mergeModal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect.poll(() => mergePayload).not.toBeNull();
    expect(mergePayload.targetClusterId).toBe(502);
    await expect(page.getByText('问题簇已合并')).toBeVisible();

    await page.getByTestId('issue-pool-anomaly-filter').hover();
    await page.locator('[data-testid="issue-pool-anomaly-filter"] .ant-select-clear').click();
    await expect.poll(() => listAnomalyFilter).toBe('');

    await page.getByTestId('issue-pool-status-filter').click();
    await page.getByText('处理中', { exact: true }).click();
    await expect.poll(() => listStatusFilter).toBe('triaging');

    const targetRow = page.locator('tr', { hasText: '旧版启动崩溃' });
    await targetRow.getByRole('button', { name: '转缺陷' }).click();
    await expect(page.getByText('问题簇已转为缺陷')).toBeVisible();
    await expect(page).toHaveURL(/\/projects\/101\/defects\/702$/);
  });

  test('项目问题池可生成回归项，并在回归中心标记已验证', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    let createdRegression = false;
    let updatedRegressionPayload: any = null;
    const cluster = {
      id: 511,
      projectId: 101,
      clusterKey: 'fp-regression-ui',
      title: '登录页闪退',
      summary: '用户进入登录页后立刻闪退',
      status: 'converted',
      signalCount: 2,
      affectedUserCount: 6,
      severity: 'major',
      priority: 'P1',
      anomalyLevel: 'watch',
      platform: 'android',
      appVersion: '5.1.0',
      buildNumber: '51001',
      releaseMatchCount: 0,
      ownerUserId: 2,
      linkedDefectId: 711,
      lastSeenAt: '2026-04-12T12:00:00Z',
      firstSeenAt: '2026-04-12T11:40:00Z',
      createdAt: '2026-04-12T11:40:00Z',
      updatedAt: '2026-04-12T12:00:00Z',
      owner: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
      defect: {
        id: 711,
        code: 'BUG-BUG-202604-011',
        title: '登录页闪退',
        description: '来源于问题池',
        severity: 'major',
        priority: 'P1',
        type: 'functional',
        status: 'pending_fix',
        assigneeId: 2,
        reporterId: 1,
        createdAt: '2026-04-12T11:45:00Z',
        updatedAt: '2026-04-12T11:50:00Z',
        assignee: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
        reporter: MOCK_USER,
      },
    };
    const regressionItem = {
      id: 611,
      projectId: 101,
      clusterId: 511,
      defectId: 711,
      title: '登录页闪退',
      summary: '用户进入登录页后立刻闪退',
      sourceFingerprint: 'fp-regression-ui',
      status: 'draft',
      ownerUserId: 2,
      createdBy: 1,
      createdAt: '2026-04-12T12:05:00Z',
      updatedAt: '2026-04-12T12:05:00Z',
      owner: { id: 2, username: 'client_owner', nickname: '客户端负责人', email: 'client@example.com', createdAt: '2026-04-12T00:00:00Z' },
      defect: cluster.defect,
    };

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({ items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }] }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG' },
          members: [
            { id: 1, userId: 1, nickname: '管理员', username: 'admin', role: 'project_admin' },
            { id: 2, userId: 2, nickname: '客户端负责人', username: 'client_owner', role: 'developer' },
          ],
          iterations: [{ id: 301, name: 'Sprint 5', status: 'active' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([{ id: 301, name: 'Sprint 5', status: 'active' }]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/releases') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/release-summary') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters') {
        await json(route, ok({ items: [cluster], total: 1 }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/511/signals') {
        await json(route, ok([]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/issue-clusters/511/releases') {
        await json(route, ok([]));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/issue-clusters/511/regression-items') {
        createdRegression = true;
        await json(route, ok(regressionItem), 201);
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/regression-items') {
        await json(route, ok(createdRegression ? [regressionItem] : []));
        return;
      }
      if (method === 'PUT' && path === '/api/v1/projects/101/regression-items/611') {
        updatedRegressionPayload = req.postDataJSON();
        regressionItem.status = 'verified';
        regressionItem.lastVerifiedAt = '2026-04-12T12:10:00Z';
        await json(route, ok(regressionItem));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/issue-pool');
    await page.getByRole('button', { name: '详情' }).click();
    await page.getByTestId('issue-pool-create-regression').click();
    await expect(page.getByText('回归预防项已创建')).toBeVisible();

    await page.goto('/projects/101/regression');
    await expect(page.getByRole('heading', { name: '回归预防' })).toBeVisible();
    await expect(page.getByText('登录页闪退', { exact: true })).toBeVisible();
    await page.getByTestId('regression-verify-611').click();
    await expect.poll(() => updatedRegressionPayload).not.toBeNull();
    expect(updatedRegressionPayload).toEqual({ status: 'verified' });
    await expect(page.getByText('verified')).toBeVisible();
  });

  test('项目路由治理页支持管理模块、规则和版本发布', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    const modules: any[] = [];
    const rules: any[] = [];
    const releases: any[] = [
      {
        id: 800,
        projectId: 101,
        platform: 'android',
        appVersion: '4.9.0',
        buildNumber: '49999',
        channel: 'prod',
        releaseTime: '2026-04-11T10:00:00Z',
        commitSha: 'old999',
        repoId: 21,
        metadataJson: '{}',
        createdAt: '2026-04-11T10:00:00Z',
        updatedAt: '2026-04-11T10:00:00Z',
      },
    ];
    const releaseTrends: any[] = [
      {
        release: releases[0],
        clusterCount: 1,
        signalCount: 1,
        affectedUserCount: 3,
        lastSeenAt: '2026-04-11T11:00:00Z',
        anomalyLevel: 'baseline',
        previousRelease: null,
        previousClusterCount: 0,
        previousAffectedUserCount: 0,
        clusterDelta: 1,
        affectedUserDelta: 3,
      },
    ];
    let modulePayload: any = null;
    let rulePayload: any = null;
    let releasePayload: any = null;

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({ items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }] }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([{ id: 301, name: 'Sprint 5', status: 'active' }]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG' },
          members: [
            { id: 1, userId: 1, nickname: '管理员', username: 'admin', role: 'project_admin' },
            { id: 2, userId: 2, nickname: '客户端负责人', username: 'client_owner', role: 'developer' },
          ],
          iterations: [{ id: 301, name: 'Sprint 5', status: 'active' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/repos') {
        await json(route, ok([
          { id: 21, projectId: 101, name: 'mobile-app', repoUrl: 'https://example.com/mobile.git', sourceType: 'git', defaultBranch: 'main', createdAt: '2026-04-12T00:00:00Z', updatedAt: '2026-04-12T00:00:00Z' },
        ]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/modules') {
        await json(route, ok(modules));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/modules') {
        modulePayload = req.postDataJSON();
        modules.unshift({
          id: 601,
          projectId: 101,
          createdAt: '2026-04-12T12:00:00Z',
          updatedAt: '2026-04-12T12:00:00Z',
          ...modulePayload,
        });
        await json(route, ok(modules[0]), 201);
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/routing-rules') {
        await json(route, ok(rules));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/routing-rules') {
        rulePayload = req.postDataJSON();
        rules.unshift({
          id: 701,
          projectId: 101,
          createdAt: '2026-04-12T12:05:00Z',
          updatedAt: '2026-04-12T12:05:00Z',
          ...rulePayload,
        });
        await json(route, ok(rules[0]), 201);
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/releases') {
        await json(route, ok(releases));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/releases/trends') {
        await json(route, ok(releaseTrends));
        return;
      }
      if (method === 'POST' && path === '/api/v1/projects/101/releases') {
        releasePayload = req.postDataJSON();
        const createdRelease = {
          id: 801,
          projectId: 101,
          createdAt: '2026-04-12T12:10:00Z',
          updatedAt: '2026-04-12T12:10:00Z',
          releaseTime: releasePayload.releaseTime,
          metadataJson: JSON.stringify(releasePayload.metadata || {}),
          ...releasePayload,
        };
        releases.unshift(createdRelease);
        releaseTrends.unshift({
          release: createdRelease,
          clusterCount: 2,
          signalCount: 3,
          affectedUserCount: 9,
          lastSeenAt: '2026-04-12T12:20:00Z',
          anomalyLevel: 'watch',
          previousRelease: releases[1],
          previousClusterCount: 1,
          previousAffectedUserCount: 3,
          clusterDelta: 1,
          affectedUserDelta: 6,
        });
        await json(route, ok(createdRelease), 201);
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/routing');
    await expect(page.locator('.ant-card-head-title', { hasText: '路由治理' }).first()).toBeVisible();

    await page.getByRole('button', { name: '新增模块' }).click();
    let modal = page.locator('.ant-modal').last();
    await modal.getByLabel('模块名称').fill('启动链路');
    await modal.getByLabel('模块编码').fill('startup');
    await modal.getByLabel('负责人').click();
    await page.getByText('客户端负责人', { exact: true }).click();
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect.poll(() => modulePayload).not.toBeNull();
    expect(modulePayload.name).toBe('启动链路');
    await expect(page.getByText('项目模块已创建')).toBeVisible();

    await page.getByRole('tab', { name: '路由规则' }).click();
    await page.getByRole('button', { name: '新增规则' }).click();
    modal = page.locator('.ant-modal').last();
    await modal.getByLabel('匹配类型').click();
    await page.locator('.ant-select-item-option-content', { hasText: '平台' }).click();
    await modal.getByLabel('匹配值').fill('android');
    await modal.getByLabel('归属模块').click();
    await page.locator('.ant-select-item-option-content', { hasText: '启动链路' }).click();
    await modal.getByLabel('优先级覆盖').click();
    await page.locator('.ant-select-item-option-content', { hasText: 'P0' }).click();
    await modal.getByLabel('严重级别覆盖').click();
    await page.locator('.ant-select-item-option-content', { hasText: 'fatal' }).click();
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect.poll(() => rulePayload).not.toBeNull();
    expect(rulePayload.matchType).toBe('platform');
    expect(rulePayload.moduleId).toBe(601);
    await expect(page.getByText('路由规则已创建')).toBeVisible();

    await page.getByRole('tab', { name: '版本发布' }).click();
    const releaseTrendCard = page.getByTestId('release-trend-card');
    await expect(releaseTrendCard.getByText('发布趋势')).toBeVisible();
    await expect(releaseTrendCard.getByText('基线版本', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '新增版本' }).click();
    modal = page.locator('.ant-modal').last();
    await modal.getByLabel('版本号').fill('5.0.0');
    await modal.getByLabel('构建号').fill('50001');
    await modal.getByLabel('渠道').fill('prod');
    await modal.getByLabel('仓库').click();
    await page.locator('.ant-select-item-option-content', { hasText: 'mobile-app (main)' }).click();
    await modal.getByLabel('Commit SHA').fill('abc123');
    await modal.locator('.ant-modal-footer .ant-btn-primary').click();
    await expect.poll(() => releasePayload).not.toBeNull();
    expect(releasePayload.appVersion).toBe('5.0.0');
    expect(releasePayload.repoId).toBe(21);
    await expect(page.getByText('版本发布已创建')).toBeVisible();
    await expect(releaseTrendCard.getByText('关注抬升')).toBeVisible();
    const createdTrendRow = releaseTrendCard.locator('tr', { hasText: '5.0.0 (50001)' });
    await expect(createdTrendRow.getByText('9', { exact: true })).toBeVisible();
  });

  test('项目质量情报页展示问题概览、发布异常和模块热点', async ({ page }) => {
    await seedAuth(page, { lastProjectId: '101' });

    await page.route('**/api/v1/**', async (route) => {
      const req = route.request();
      const method = req.method();
      const path = new URL(req.url()).pathname;

      if (method === 'GET' && path === '/api/v1/projects') {
        await json(route, ok({ items: [{ id: 101, name: 'BugAgent 平台', code: 'BUG' }] }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101') {
        await json(route, ok({
          project: { id: 101, name: 'BugAgent 平台', code: 'BUG' },
          members: [{ id: 1, userId: 1, nickname: '管理员', username: 'admin', role: 'project_admin' }],
          iterations: [{ id: 301, name: 'Sprint 5', status: 'active' }],
        }));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/iterations') {
        await json(route, ok([{ id: 301, name: 'Sprint 5', status: 'active' }]));
        return;
      }
      if (method === 'GET' && path === '/api/v1/projects/101/quality-insights/overview') {
        await json(route, ok({
          issuePool: {
            totalClusters: 12,
            openClusters: 4,
            convertedClusters: 6,
            ignoredClusters: 2,
            totalSignals: 48,
            affectedUserCount: 103,
          },
          regression: {
            totalItems: 7,
            openItems: 3,
            verifiedItems: 3,
            archivedItems: 1,
          },
          releaseHealth: {
            baselineCount: 1,
            normalCount: 2,
            watchAnomalyCount: 1,
            highAnomalyCount: 1,
          },
          sourceBreakdowns: [
            { sourceType: 'bugly', signalCount: 28, clusterCount: 7, affectedUserCount: 68 },
            { sourceType: 'aliyun_log', signalCount: 20, clusterCount: 5, affectedUserCount: 35 },
          ],
          moduleHotspots: [
            { moduleName: '支付模块', clusterCount: 5, openClusterCount: 2, convertedClusterCount: 2, affectedUserCount: 49, highAnomalyClusterCount: 1 },
            { moduleName: '登录模块', clusterCount: 3, openClusterCount: 1, convertedClusterCount: 1, affectedUserCount: 22, highAnomalyClusterCount: 0 },
          ],
          topReleaseAnomalies: [
            {
              release: {
                id: 901,
                projectId: 101,
                platform: 'android',
                appVersion: '5.2.0',
                buildNumber: '52001',
                channel: 'prod',
                releaseTime: '2026-04-12T10:00:00Z',
                createdAt: '2026-04-12T10:00:00Z',
                updatedAt: '2026-04-12T10:00:00Z',
              },
              clusterCount: 4,
              signalCount: 18,
              affectedUserCount: 42,
              anomalyLevel: 'high',
            },
            {
              release: {
                id: 902,
                projectId: 101,
                platform: 'android',
                appVersion: '5.1.0',
                buildNumber: '51001',
                channel: 'prod',
                releaseTime: '2026-04-11T10:00:00Z',
                createdAt: '2026-04-11T10:00:00Z',
                updatedAt: '2026-04-11T10:00:00Z',
              },
              clusterCount: 2,
              signalCount: 9,
              affectedUserCount: 16,
              anomalyLevel: 'watch',
            },
          ],
        }));
        return;
      }

      await json(route, ok({}));
    });

    await page.goto('/projects/101/quality-insights');
    await expect(page.getByRole('heading', { name: '质量情报' })).toBeVisible();
    await expect(page.getByTestId('quality-issue-total').getByText('12')).toBeVisible();
    await expect(page.getByTestId('quality-release-high').getByText('1')).toBeVisible();
    await expect(page.getByTestId('quality-regression-open').getByText('3')).toBeVisible();
    await expect(page.getByText('android / 5.2.0 / 52001')).toBeVisible();
    await expect(page.getByText('异常抬升', { exact: true })).toBeVisible();
    await expect(page.getByText('支付模块')).toBeVisible();
    await expect(page.getByText('bugly')).toBeVisible();
  });
});
