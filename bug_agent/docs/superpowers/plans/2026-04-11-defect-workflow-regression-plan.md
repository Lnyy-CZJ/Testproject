# Defect Workflow Regression Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the blocking defect workflow regression, remove the obsolete runtime `confirmed` path, add deterministic AI analysis failure verification, and re-run UAT coverage for `DEF-04` and `REG-03`.

**Architecture:** Consolidate runtime defect transitions onto the shared workflow matrix in the model layer, remove the legacy `confirmed` branch from active runtime flow, and add a development-only deterministic AI failure path so analysis failure UX can be re-verified without external provider randomness.

**Tech Stack:** Go, Gin, GORM, React, TypeScript, Playwright

---

### Task 1: Freeze the expected workflow in tests

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/model/workflow_test.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/service/workflow_test.go`
- Create or modify: targeted defect handler tests under `/Users/jame/Workspace/bug_agent/server/internal/handler/`

- [ ] Step 1: Write failing tests for the PRD lifecycle and obsolete `confirmed` removal.
- [ ] Step 2: Run only those tests and verify they fail for the current regression.
- [ ] Step 3: Capture exact failure messages for `pending_analysis/analyzing/pending_fix` and `confirmed` assumptions.

### Task 2: Unify runtime workflow validation

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/model/workflow.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/handler/defect.go`

- [ ] Step 1: Update the shared transition matrix to the PRD lifecycle.
- [ ] Step 2: Remove handler-local transition logic and delegate to `model.IsValidDefectTransition`.
- [ ] Step 3: Re-run the failing workflow tests until they pass.

### Task 3: Add deterministic analysis failure verification

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/ai/factory.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/service/analysis.go` or `/Users/jame/Workspace/bug_agent/server/internal/handler/agent.go`
- Add tests in `/Users/jame/Workspace/bug_agent/server/internal/handler/` or `/Users/jame/Workspace/bug_agent/server/internal/service/`

- [ ] Step 1: Add a non-release-only deterministic AI failure trigger.
- [ ] Step 2: Write a failing test that proves status rollback and failure comment persistence.
- [ ] Step 3: Implement the minimal change to make that test pass.

### Task 4: Reconcile frontend actions if needed

**Files:**
- Inspect and modify only if necessary: `/Users/jame/Workspace/bug_agent/web/src/pages/defects/DefectDetail.tsx`

- [ ] Step 1: Verify frontend action buttons still match backend transitions.
- [ ] Step 2: If inconsistent, make the minimal UI change.
- [ ] Step 3: Run targeted frontend regression.

### Task 5: Re-run verification and UAT closure

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/docs/UAT_SMOKE_CHECKLIST_PHASE4.md`

- [ ] Step 1: Run targeted Go tests for workflow and analysis failure.
- [ ] Step 2: Run targeted browser or API smoke for `DEF-04` and `REG-03`.
- [ ] Step 3: Update the UAT checklist with fresh evidence and final status.
