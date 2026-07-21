# Multi-Repo Fix Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support one defect fix spanning multiple agents, repositories, build checks, and pull requests.

**Architecture:** A defect fix is represented by a `fix_task_group`. Existing `fix_tasks` become executable units under that group, each bound to one analysis report and one agent/repository execution path. The first rollout keeps existing unit execution code and changes creation/orchestration, then frontend group presentation can be refined independently.

**Tech Stack:** Go, GORM, PostgreSQL, React, TypeScript, Ant Design.

---

### Phase 1: Backend Group Foundation

- [x] Add `FixTaskGroup` model and `fix_tasks.group_id`.
- [x] Add group migration coverage via AutoMigrate and test DB migration.
- [x] Add service test proving multiple latest auto-fixable reports create one group with multiple units.
- [x] Implement `CreateAutoFixGroup` to select one latest fixable report per agent.
- [x] Preserve single-report behavior by returning a normal single unit when only one report is fixable.
- [x] Start each unit independently and aggregate group status after unit completion.

### Phase 2: API Compatibility

- [x] Change `POST /defects/:id/fix-tasks` to create a group when multiple units are needed.
- [x] Return `groupId` and `units` in the create response while preserving `taskCode`, `status`, and `defectId`.
- [x] Keep `GET /defects/:id/fix-tasks` returning unit tasks for backward-compatible frontend display.

### Phase 3: Frontend Type Readiness

- [x] Add `groupId`, `analysisReportId`, and `projectRepoId` to `FixTask`.
- [x] Add `partially_failed` display label/color.
- [x] Type the create response with optional `units`.

### Phase 4: Follow-Up UI Upgrade

- [ ] Add `GET /defects/:id/fix-task-groups`.
- [ ] Render grouped fix cards with nested units.
- [ ] Show per-unit repo, PR, build result, token usage, and retry action.
- [ ] Add unit-level retry API.

### Phase 5: Repository Precision

- [ ] Add explicit `project_repo_id` selection during group creation.
- [ ] Resolve reports by affected file path first, then agent type as a fallback.
- [ ] Pass selected `project_repo_id` into clone execution to avoid ambiguity when one agent owns multiple repos.
