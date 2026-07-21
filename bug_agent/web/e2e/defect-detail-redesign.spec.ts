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

async function seedAuth(page: Page) {
  await page.addInitScript((input) => {
    localStorage.setItem('token', input.token);
    localStorage.setItem('user', JSON.stringify(input.user));
    localStorage.setItem('lastProjectId', '1');
  }, {
    token: MOCK_TOKEN,
    user: MOCK_USER,
  });
}

async function mockProjectShell(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const method = req.method();
    const path = new URL(req.url()).pathname;

    if (method === 'GET' && path === '/api/v1/users/me') {
      await json(route, ok(MOCK_USER));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects') {
      await json(route, ok({ items: [{ id: 1, name: '默认项目', code: 'BUGAGENT' }] }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/user/projects') {
      await json(route, ok({ list: [{ id: 1, name: '默认项目', code: 'BUGAGENT' }] }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1') {
      await json(route, ok({
        project: {
          id: 1,
          name: '默认项目',
          code: 'BUGAGENT',
        },
        members: [
          { id: 1, userId: 1, username: 'admin', nickname: '管理员', role: 'project_admin' },
        ],
        iterations: [
          { id: 1, name: 'Sprint 1', status: 'active' },
        ],
      }));
      return;
    }
    if (method === 'GET' && path === '/api/v1/projects/1/iterations') {
      await json(route, ok([{ id: 1, name: 'Sprint 1', status: 'active' }]));
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
    if (method === 'GET' && path === '/api/v1/projects/1/quality-insights/overview') {
      await json(route, ok({
        issuePool: { totalClusters: 0, convertedClusters: 0, ignoredClusters: 0, pendingClusters: 0 },
        anomalyReleases: [],
        regression: { draft: 0, active: 0, verified: 0 },
        sourceDistribution: [],
        moduleHotspots: [],
        aiSummary: { totalReports: 0, totalFixTasks: 0, fallbackReports: 0, failedFixTasks: 0, averageAnalysisDurationMs: 0, averageFixDurationMs: 0, totalEstimatedCostUsd: 0 },
      }));
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

    await json(route, ok({}));
  });
}

test.describe('v5.2 defect detail redesign', () => {
  test('对话创建缺陷默认生成草稿并确认创建', async ({ page }) => {
    await seedAuth(page);
    await mockProjectShell(page);

    let draftRequested = false;
    let confirmRequested = false;

    await page.route('**/api/v1/projects/1/defects/draft-from-chat', async (route) => {
      draftRequested = true;
      const body = route.request().postDataJSON() as { message?: string; iterationId?: number; tags?: string[] };
      expect(body.message).toContain('云效仓库导入弹窗');
      await json(route, ok({
        title: 'ProjectRepos 云效仓库导入搜索应改为本地过滤',
        descriptionMarkdown: '## 现象\n- 当前搜索会反复请求远端接口\n- 应在已拉取仓库列表上做本地过滤\n\n## 建议\n- 默认不勾选仓库\n- 仅导入当前页勾选数据',
        severity: 'normal',
        priority: 'P2',
        type: 'functional',
        tags: ['projectrepos', '云效导入'],
        suggestedIterationId: body.iterationId ?? 1,
        missingInformation: ['建议补充是否影响历史已导入仓库'],
        confidence: 0.84,
        sourceMode: 'manual_chat',
        provider: 'dashscope',
        modelName: 'qwen3.6-plus',
        promptVersion: 'v5.2-draft-1',
        fallbackUsed: false,
      }));
    });

    await page.route('**/api/v1/projects/1/defects/confirm-create', async (route) => {
      confirmRequested = true;
      const body = route.request().postDataJSON() as { title?: string; sourceMode?: string; tags?: string[] };
      expect(body.title).toContain('ProjectRepos');
      expect(body.sourceMode).toBe('manual_chat');
      expect(body.tags).toContain('projectrepos');
      await json(route, ok({ id: 9 }));
    });

    await page.route('**/api/v1/defects/9', async (route) => {
      await json(route, ok({
        defect: {
          id: 9,
          code: 'BUG-BUGAGENT-009',
          title: 'ProjectRepos 云效仓库导入搜索应改为本地过滤',
          description: '## 现象\n- 当前搜索会反复请求远端接口\n\n## 建议\n- 改为本地过滤',
          severity: 'normal',
          priority: 'P2',
          type: 'functional',
          tags: 'projectrepos,云效导入',
          status: 'pending_assign',
          createdAt: '2026-04-13T15:00:00+08:00',
          updatedAt: '2026-04-13T15:00:00+08:00',
          assignee: null,
          reporter: { id: 1, username: 'admin', nickname: '管理员' },
          iteration: { id: 1, name: 'Sprint 1' },
        },
        comments: [],
        fixTasks: [],
      }));
    });
    await page.route('**/api/v1/defects/9/reports', async (route) => {
      await json(route, ok([]));
    });
    await page.route('**/api/v1/users*', async (route) => {
      await json(route, ok({ list: [MOCK_USER] }));
    });

    await page.goto('/projects/1/defects/create');

    await expect(page.getByText('Chat-First')).toBeVisible();
    await expect(page.getByRole('button', { name: 'AI 生成草稿' })).toBeVisible();

    await page.getByLabel('用自然语言描述问题').fill('云效仓库导入弹窗里搜索应该改为本地过滤，并默认不勾选仓库，只导入当前页勾选的仓库。');
    await page.getByRole('button', { name: 'AI 生成草稿' }).click();

    await expect(page.getByText('确认缺陷草稿')).toBeVisible();
    await expect(page.locator('input[value="ProjectRepos 云效仓库导入搜索应改为本地过滤"]')).toBeVisible();
    await expect(page.getByText('建议补充是否影响历史已导入仓库')).toBeVisible();

    await page.getByRole('button', { name: '确认创建缺陷' }).click();

    await expect(page).toHaveURL(/\/projects\/1\/defects\/9$/);
    await expect(page.locator('span').filter({ hasText: 'BUG-BUGAGENT-009' }).first()).toBeVisible();
    expect(draftRequested).toBeTruthy();
    expect(confirmRequested).toBeTruthy();
  });

  test('问题池详情对手动来源显示友好标签', async ({ page }) => {
    await seedAuth(page);
    await mockProjectShell(page);

    await page.route('**/api/v1/projects/1/releases', async (route) => {
      await json(route, ok([]));
    });
    await page.route('**/api/v1/projects/1/issue-clusters/release-summary**', async (route) => {
      await json(route, ok([]));
    });
    await page.route('**/api/v1/projects/1/issue-clusters', async (route) => {
      await json(route, ok({
        items: [
          {
            id: 11,
            projectId: 1,
            clusterKey: 'manual-11',
            title: '手动创建问题',
            summary: '来源于对话创建的手动问题',
            status: 'converted',
            signalCount: 1,
            affectedUserCount: 1,
            severity: 'normal',
            priority: 'P2',
            ownerUserId: 1,
            moduleId: null,
            firstSeenAt: '2026-04-13T12:00:00+08:00',
            lastSeenAt: '2026-04-13T12:30:00+08:00',
            linkedDefectId: 2,
            createdAt: '2026-04-13T12:00:00+08:00',
            updatedAt: '2026-04-13T12:30:00+08:00',
            owner: { id: 1, username: 'admin', nickname: '管理员' },
            defect: { id: 2, code: 'BUG-BUGAGENT-001', title: '手动缺陷', status: 'pending_fix', createdAt: '2026-04-13T12:00:00+08:00', updatedAt: '2026-04-13T12:30:00+08:00' },
          },
        ],
        total: 1,
      }));
    });
    await page.route('**/api/v1/projects/1/issue-clusters/11/signals', async (route) => {
      await json(route, ok([
        {
          id: 101,
          projectId: 1,
          connectorId: null,
          clusterId: 11,
          sourceType: 'manual_chat',
          sourceEventId: 'manual-2',
          sourceInstance: 'defect:2',
          title: '手动缺陷',
          description: '来自对话创建',
          occurrenceCount: 1,
          affectedUserCount: 1,
          firstSeenAt: '2026-04-13T12:00:00+08:00',
          lastSeenAt: '2026-04-13T12:30:00+08:00',
          rawPayloadJson: '{}',
          triageStatus: 'converted',
          linkedDefectId: 2,
          createdAt: '2026-04-13T12:00:00+08:00',
          updatedAt: '2026-04-13T12:30:00+08:00',
          platform: 'manual',
          appVersion: '',
          buildNumber: '',
          logExcerpt: '用户通过对话创建缺陷',
          stackTrace: '',
        },
      ]));
    });
    await page.route('**/api/v1/projects/1/issue-clusters/11/releases', async (route) => {
      await json(route, ok([]));
    });

    await page.goto('/projects/1/issue-pool');
    await page.getByRole('button', { name: '详情' }).click();

    await expect(page.getByRole('dialog', { name: /问题簇详情/ })).toBeVisible();
    await expect(page.getByRole('cell', { name: '对话创建' }).first()).toBeVisible();
  });

  test('缺陷详情按 Markdown 渲染摘要并折叠原始数据', async ({ page }) => {
    await seedAuth(page);
    await mockProjectShell(page);

    await page.route('**/api/v1/users*', async (route) => {
      await json(route, ok({ list: [MOCK_USER] }));
    });
    await page.route('**/api/v1/defects/2', async (route) => {
      await json(route, ok({
        defect: {
          id: 2,
          code: 'BUG-BUGAGENT-002',
          title: 'Markdown 渲染失败',
          description: '## 复现范围\n- 打开缺陷详情\n- 分析报告应按 Markdown 展示\n\n```ts\nconsole.log("bug")\n```',
          severity: 'major',
          priority: 'P1',
          type: 'functional',
          tags: 'markdown,detail',
          status: 'pending_verify',
          createdAt: '2026-04-13T12:00:00+08:00',
          updatedAt: '2026-04-13T12:40:00+08:00',
          assignee: { id: 1, username: 'admin', nickname: '管理员' },
          reporter: { id: 1, username: 'admin', nickname: '管理员' },
          iteration: { id: 1, name: 'Sprint 1' },
        },
        comments: [
          {
            id: 4,
            defectId: 2,
            userId: 1,
            content: '### 最新系统结论\n- 已生成分析摘要\n- 原始 JSON 不应直接平铺',
            isAgentMessage: true,
            createdAt: '2026-04-13T12:23:00+08:00',
            user: { id: 1, username: 'admin', nickname: '系统' },
          },
          {
            id: 3,
            defectId: 2,
            userId: 1,
            content: '### 排查记录\n- 最近分析记录已更新为最新结论卡',
            isAgentMessage: true,
            createdAt: '2026-04-13T12:22:00+08:00',
            user: { id: 1, username: 'admin', nickname: '系统' },
          },
          {
            id: 2,
            defectId: 2,
            userId: 1,
            content: '我补充了一个人工评论，说明当前问题主要集中在详情页阅读密度。',
            isAgentMessage: false,
            createdAt: '2026-04-13T12:21:00+08:00',
            user: { id: 1, username: 'admin', nickname: '管理员' },
          },
          {
            id: 1,
            defectId: 2,
            userId: 1,
            content: '### 旧系统动态\n- 这是更早的一条系统记录，应默认折叠到更早动态中。',
            isAgentMessage: true,
            createdAt: '2026-04-13T12:20:00+08:00',
            user: { id: 1, username: 'admin', nickname: '系统' },
          },
        ],
        fixTasks: [
          {
            id: 7,
            taskCode: 'FT-BUG-BUGAGENT-002',
            defectId: 2,
            agentType: 'backend',
            status: 'completed',
            fixBranch: 'fix/markdown-detail',
            aiProvider: 'dashscope',
            aiModelName: 'qwen3.6-plus',
            aiPromptVersion: 'v5.1-fix-1',
            aiDurationMs: 240000,
            aiTotalTokens: 12888,
            aiEstimatedCostUsd: 0.0234,
            aiRiskSummary: '风险主要在 Markdown 渲染与原始内容分层。',
            aiValidationSuggestions: '["确认分析摘要展示为标题和列表","确认原始 JSON 默认折叠"]',
            result: '{"raw":"debug-json"}',
            createdAt: '2026-04-13T12:30:00+08:00',
            completedAt: '2026-04-13T12:36:00+08:00',
          },
          {
            id: 6,
            taskCode: 'FT-BUG-BUGAGENT-001',
            defectId: 2,
            agentType: 'backend',
            status: 'failed',
            fixBranch: 'fix/old-attempt',
            aiProvider: 'dashscope',
            aiModelName: 'qwen3.6-plus',
            aiPromptVersion: 'v5.1-fix-1',
            aiDurationMs: 180000,
            aiTotalTokens: 9800,
            aiEstimatedCostUsd: 0.018,
            aiRiskSummary: '旧修复尝试未能解决正文与原始数据混排问题。',
            aiValidationSuggestions: '[]',
            result: '{"raw":"old-debug-json"}',
            createdAt: '2026-04-13T12:10:00+08:00',
            completedAt: '2026-04-13T12:18:00+08:00',
          },
        ],
      }));
    });
    await page.route('**/api/v1/defects/2/reports', async (route) => {
      await json(route, ok([
        {
          id: 2,
          reportCode: 'AR-2',
          defectId: 2,
          agentType: 'backend',
          status: 'completed',
          provider: 'dashscope',
          modelName: 'qwen3.6-plus',
          promptVersion: 'v5.2-analysis-1',
          durationMs: 8200,
          totalTokens: 3200,
          estimatedCostUsd: 0.0112,
          riskSummary: '正文层级已优化，但历史记录仍需折叠降噪。',
          validationSuggestions: '["确认最新结论卡优先展示","确认旧报告默认折叠"]',
          analysis: JSON.stringify({
            rootCause: '缺陷详情页没有把最新结论与历史分析分层展示。',
            affectedFiles: ['web/src/pages/defects/DefectDetail.tsx', 'web/src/components/MarkdownContent.tsx'],
            riskLevel: 'high',
            riskSummary: '如果继续把历史报告全部展开，页面仍然会像日志墙。',
            solution: {
              description: '把最新结论提取成独立摘要卡，历史记录收进折叠区。',
              steps: [
                { step: 1, action: '单独展示最新根因、风险和验证建议' },
                { step: 2, action: '历史分析记录默认收起' },
              ],
              estimatedEffort: '0.5d',
            },
          }),
          solution: '',
          createdAt: '2026-04-13T12:18:00+08:00',
        },
        {
          id: 1,
          reportCode: 'AR-1',
          defectId: 2,
          agentType: 'backend',
          status: 'completed',
          provider: 'dashscope',
          modelName: 'qwen3.6-plus',
          promptVersion: 'v5.1-analysis-1',
          durationMs: 10000,
          totalTokens: 4000,
          estimatedCostUsd: 0.0138,
          riskSummary: '原始 JSON 直接平铺导致页面难以阅读。',
          validationSuggestions: '["检查 Markdown 标题是否渲染","确认代码块渲染正常"]',
          analysis: JSON.stringify({
            rootCause: '缺陷详情页将 Markdown 和原始 JSON 混在正文区渲染。',
            affectedFiles: ['web/src/pages/defects/DefectDetail.tsx'],
            riskLevel: 'medium',
            riskSummary: '如果不分层，系统评论会持续污染主阅读区。',
            solution: {
              description: '把正文、摘要、原始数据拆层。',
              steps: [
                { step: 1, action: '描述和报告统一 Markdown 渲染' },
                { step: 2, action: '原始 JSON 收进折叠区' },
              ],
              estimatedEffort: '0.5d',
            },
          }),
          solution: '',
          createdAt: '2026-04-13T12:10:00+08:00',
        },
      ]));
    });

    await page.goto('/projects/1/defects/2');

    await expect(page.getByText('最新 AI 结论')).toBeVisible();
    await expect(page.getByText('阅读摘要')).toBeVisible();
    await expect(page.getByText('缺陷概览')).toBeVisible();
    await expect(page.getByText('展开完整分析')).toBeVisible();
    await expect(page.getByText('展开任务详情')).toBeVisible();
    await expect(page.getByRole('heading', { name: '复现范围' })).toBeVisible();
    await expect(page.locator('pre code')).toContainText('console.log("bug")');
    await expect(page.getByText('历史分析记录（1）')).toBeVisible();
    await expect(page.getByText('历史修复任务（1）')).toBeVisible();
    await expect(page.getByText('最近动态（3）')).toBeVisible();
    await page.getByText('展开完整分析').click();
    await page.getByText('最近动态（3）').click();
    await expect(page.getByText('更早动态（1）')).toBeVisible();
    await expect(page.getByRole('button', { name: /查看原始数据/ }).first()).toBeVisible();
    await expect(page.getByText('raw":"debug-json')).not.toBeVisible();
  });
});
