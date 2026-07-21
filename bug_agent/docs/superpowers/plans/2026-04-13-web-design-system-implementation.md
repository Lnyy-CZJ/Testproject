# Web Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Bug Agent web UI around the approved DESIGN.md system by introducing a shared visual foundation, new shell components, and updated high-frequency page families.

**Architecture:** Start with a failing Playwright smoke spec that locks the new shell and page-family structure. Then implement the design system in layers: global tokens and theme overrides, platform/project shells, auth surfaces, dashboard/list/detail pages, and final verification. The implementation favors shared shells and CSS primitives so the redesign propagates broadly without rewriting every leaf page independently.

**Tech Stack:** React 19, React Router 7, Ant Design 6, Tailwind 4 utilities, Playwright, TypeScript, Vite

---

## File Map

**Create**

- `web/e2e/design-system-shell.spec.ts` — regression checks for new shell structure and key page-family landmarks
- `web/src/components/layout/AppShell.tsx` — shared chrome frame for platform/project workspaces
- `web/src/components/layout/PageHero.tsx` — narrative layer wrapper for page title, status and actions
- `web/src/components/layout/MetricRail.tsx` — reusable stat/summary pill rail for dashboards and lists

**Modify**

- `web/src/App.tsx` — global Ant Design tokens and component theme alignment
- `web/src/index.css` — design tokens, shell surfaces, card classes, action rails, list/detail utilities
- `web/src/layouts/MainLayout.tsx` — platform console shell
- `web/src/layouts/ProjectLayout.tsx` — project workspace shell
- `web/src/pages/auth/Login.tsx` — brand-story auth page
- `web/src/pages/auth/Register.tsx` — auth family parity
- `web/src/pages/projects/ProjectList.tsx` — platform hero + project card family
- `web/src/pages/Dashboard.tsx` — platform workbench page
- `web/src/pages/projects/ProjectDashboard.tsx` — project workbench page
- `web/src/pages/defects/DefectList.tsx` — action rail + data stage list page
- `web/src/pages/defects/DefectDetail.tsx` — summary band + reading-first workbench detail page

**Verify**

- `web/e2e/browser-prd-flows.spec.ts`
- `web/e2e/defect-detail-redesign.spec.ts`

---

### Task 1: Lock The New UI Contract With Failing Browser Tests

**Files:**
- Create: `web/e2e/design-system-shell.spec.ts`
- Modify: none
- Verify: `web/e2e/design-system-shell.spec.ts`

- [ ] **Step 1: Write the failing Playwright spec**

Create `web/e2e/design-system-shell.spec.ts` with mocked shell data and assertions for:

```ts
await expect(page.getByTestId('platform-shell')).toBeVisible();
await expect(page.getByTestId('platform-hero')).toBeVisible();
await expect(page.getByTestId('project-shell')).toBeVisible();
await expect(page.getByTestId('project-context-panel')).toBeVisible();
await expect(page.getByTestId('defect-summary-band')).toBeVisible();
await expect(page.getByTestId('defect-decision-rail')).toBeVisible();
```

- [ ] **Step 2: Run the new spec to verify it fails**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npx playwright test e2e/design-system-shell.spec.ts --project=chromium
```

Expected: FAIL because the new `data-testid` landmarks do not exist yet.

- [ ] **Step 3: Do not write production code until the failure is confirmed**

Confirm the failure is specifically due to missing shell/detail landmarks, not broken mocks or route wiring.

---

### Task 2: Implement Global Tokens And Reusable Shell Primitives

**Files:**
- Create: `web/src/components/layout/AppShell.tsx`
- Create: `web/src/components/layout/PageHero.tsx`
- Create: `web/src/components/layout/MetricRail.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Implement the minimal shared layout components**

Add `AppShell.tsx` with props for shell variant, sidebar, topbar and content; add `PageHero.tsx` for title/subtitle/actions; add `MetricRail.tsx` for summary pills.

Key structure:

```tsx
export function AppShell({ testId, sidebar, topbar, children, shellClassName }: AppShellProps) {
  return (
    <div data-testid={testId} className={cn('app-shell', shellClassName)}>
      <aside className="app-shell__sidebar">{sidebar}</aside>
      <div className="app-shell__main">
        <header className="app-shell__topbar">{topbar}</header>
        <main className="app-shell__content">{children}</main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Align global Ant Design tokens to DESIGN.md**

Update `App.tsx` token values for:

```ts
colorPrimary: '#7c3aed',
colorInfo: '#0ea5e9',
borderRadius: 16,
fontFamily: "'Geist', 'PingFang SC', 'Microsoft YaHei', sans-serif",
boxShadowSecondary: '0 18px 40px rgba(15, 23, 42, 0.10)',
```

and tighten `Card`, `Button`, `Table`, `Input`, `Tag`, `Menu`, `Modal`.

- [ ] **Step 3: Introduce design tokens and semantic CSS surfaces**

Update `index.css` with root-level tokens and semantic classes:

```css
:root {
  --bg-page: #f5f7fb;
  --bg-surface: rgba(255, 255, 255, 0.84);
  --bg-elevated: #ffffff;
  --brand-purple: #8b5cf6;
  --brand-cyan: #06b6d4;
  --brand-gradient: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%);
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-tertiary: #94a3b8;
}
```

Add classes for:

- `.app-shell`, `.app-shell__sidebar`, `.app-shell__topbar`, `.app-shell__content`
- `.page-hero`, `.page-hero__status`, `.page-hero__actions`
- `.scene-card`, `.utility-card`, `.metric-pill`, `.action-rail`
- `.detail-summary-band`, `.decision-rail`

- [ ] **Step 4: Run lint and build after the shared foundation**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npm run lint
npm run build
```

Expected: PASS.

---

### Task 3: Rebuild Platform And Project Shells

**Files:**
- Modify: `web/src/layouts/MainLayout.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Reuse: `web/src/components/layout/AppShell.tsx`

- [ ] **Step 1: Refactor platform shell to the new console frame**

Replace inline shell markup in `MainLayout.tsx` with `AppShell`, add:

- `data-testid="platform-shell"`
- elevated brand block in the sidebar
- narrative topbar title and search rail
- sidebar sections with stronger current-state treatment

- [ ] **Step 2: Refactor project shell to the new workspace frame**

Replace inline shell markup in `ProjectLayout.tsx` with `AppShell`, add:

- `data-testid="project-shell"`
- `data-testid="project-context-panel"`
- stronger project identity panel
- iteration/status context card
- task-oriented header rail for project pages

- [ ] **Step 3: Run the new shell Playwright spec**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npx playwright test e2e/design-system-shell.spec.ts --project=chromium
```

Expected: the shell-related assertions now pass while detail-specific assertions may still fail.

---

### Task 4: Convert Auth And Dashboard Families

**Files:**
- Modify: `web/src/pages/auth/Login.tsx`
- Modify: `web/src/pages/auth/Register.tsx`
- Modify: `web/src/pages/ProjectList.tsx` is not used
- Modify: `web/src/pages/projects/ProjectList.tsx`
- Modify: `web/src/pages/Dashboard.tsx`
- Modify: `web/src/pages/projects/ProjectDashboard.tsx`
- Reuse: `web/src/components/layout/PageHero.tsx`
- Reuse: `web/src/components/layout/MetricRail.tsx`

- [ ] **Step 1: Bring auth pages into the brand-story family**

Ensure both auth pages share:

- left-side story panel
- right-side clean auth form panel
- clearer narrative hierarchy
- lower-noise gradients than the current version

- [ ] **Step 2: Convert platform dashboard/project list into platform-family pages**

Add `PageHero` and `MetricRail` to `ProjectList.tsx` and `Dashboard.tsx`, with stronger scene cards and explicit action rails.

- [ ] **Step 3: Convert project dashboard into a workspace workbench**

Update `ProjectDashboard.tsx` to use:

- narrative hero
- summary rail
- scene cards for iteration and AI abilities
- clearer split between workbench summary and recent activity

- [ ] **Step 4: Run targeted verification**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npm run lint
npm run build
npx playwright test e2e/browser-prd-flows.spec.ts --project=chromium --grep "登录后进入项目列表"
```

Expected: PASS.

---

### Task 5: Convert Defect List And Detail Into The New Families

**Files:**
- Modify: `web/src/pages/defects/DefectList.tsx`
- Modify: `web/src/pages/defects/DefectDetail.tsx`

- [ ] **Step 1: Convert defect list into action-rail list page**

Update `DefectList.tsx` so the page includes:

- narrative hero
- explicit action rail for search/filter/create
- stronger summary pill rail
- calmer data stage card for the table

- [ ] **Step 2: Convert defect detail into reading-first workbench**

Update `DefectDetail.tsx` to include:

- `data-testid="defect-summary-band"`
- `data-testid="defect-decision-rail"`
- summary band above the reading content
- AI conclusion as a scene card with evidence/action grouping
- decision rail separated from main reading flow

- [ ] **Step 3: Run defect-focused verification**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npx playwright test e2e/design-system-shell.spec.ts --project=chromium
npx playwright test e2e/defect-detail-redesign.spec.ts --project=chromium
```

Expected: PASS.

---

### Task 6: Final Regression And Commit

**Files:**
- Verify current worktree changes only

- [ ] **Step 1: Run full required verification**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system/web
npm run lint
npm run build
npx playwright test e2e/browser-prd-flows.spec.ts --project=chromium
npx playwright test e2e/defect-detail-redesign.spec.ts --project=chromium
npx playwright test e2e/design-system-shell.spec.ts --project=chromium
```

Expected: PASS.

- [ ] **Step 2: Review git diff for unintended drift**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system
git status --short
git diff --stat
```

Expected: only design-system-related files changed.

- [ ] **Step 3: Commit**

Run:

```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/codex-web-design-system
git add web/src/App.tsx web/src/index.css web/src/layouts/MainLayout.tsx web/src/layouts/ProjectLayout.tsx web/src/pages/auth/Login.tsx web/src/pages/auth/Register.tsx web/src/pages/Dashboard.tsx web/src/pages/projects/ProjectList.tsx web/src/pages/projects/ProjectDashboard.tsx web/src/pages/defects/DefectList.tsx web/src/pages/defects/DefectDetail.tsx web/src/components/layout/AppShell.tsx web/src/components/layout/PageHero.tsx web/src/components/layout/MetricRail.tsx web/e2e/design-system-shell.spec.ts docs/superpowers/plans/2026-04-13-web-design-system-implementation.md
git commit -m "feat: apply web design system shell"
```

