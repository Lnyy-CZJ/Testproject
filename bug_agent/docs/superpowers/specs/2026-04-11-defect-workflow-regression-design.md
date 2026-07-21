# Defect Workflow Regression Fix Design

## Background

Phase 4 UAT found one real blocking defect and one reproducibility gap:

1. `DEF-04`: after assigning a defect, runtime status becomes `pending_analysis`, but subsequent transitions are validated against a different workflow and can return `400` for valid PRD actions.
2. `REG-03`: analysis-failure feedback cannot be deterministically re-verified because the current AI analysis path has no controllable failure injection.

Current code has two conflicting runtime workflow definitions:

- `/Users/jame/Workspace/bug_agent/server/internal/handler/defect.go` maintains a local `isValidTransition` map.
- `/Users/jame/Workspace/bug_agent/server/internal/model/workflow.go` maintains a separate transition matrix that still contains the historical `confirmed` state.

The PRD and current frontend both use the Phase 3/4 lifecycle:

`pending_assign -> pending_analysis -> analyzing -> pending_fix -> fixing -> pending_verify -> fixed`

`confirmed` is a historical branch that is no longer part of the active PRD or UI flow.

## Goals

1. Remove runtime ambiguity by making the backend use a single defect workflow definition.
2. Align runtime transitions with the PRD and current frontend behavior.
3. Preserve the existing analysis failure UX: failed AI analysis rolls status back to `pending_analysis` and writes a readable failure comment.
4. Make `REG-03` reproducible in local/UAT environments without depending on external AI provider instability.

## Non-Goals

1. No attempt to preserve backward compatibility for the obsolete `confirmed` state in active workflows.
2. No redesign of the full defect domain model.
3. No attempt to convert blocked Yunxiao tests into passing tests without real external credentials and tenant data.

## Design Decisions

### 1. Single runtime workflow source

The runtime system will use `/Users/jame/Workspace/bug_agent/server/internal/model/workflow.go` as the single transition source.

`/Users/jame/Workspace/bug_agent/server/internal/handler/defect.go` will stop maintaining its own local transition map and will delegate validation to `model.IsValidDefectTransition(...)`.

### 2. Remove `confirmed` from the active matrix

The active matrix will be updated to match the PRD and current UI:

- `pending_assign -> pending_analysis`
- `pending_analysis -> analyzing | rejected`
- `analyzing -> pending_fix | rejected`
- `pending_fix -> fixing | suspended`
- `fixing -> pending_verify | pending_fix | suspended`
- `pending_verify -> fixed | pending_fix`
- `fixed -> completed | reopened`
- `completed -> reopened`
- `rejected -> reopened`
- `suspended -> pending_fix | reopened`
- `reopened -> analyzing | pending_fix | rejected`

The historical `confirmed` state will be removed from the active transition matrix and transition tests.

### 3. Deterministic analysis-failure hook

A local/UAT-only failure injection path will be added to AI client creation or analysis execution.

Scope:
- available only when server mode is not `release`
- triggered by an explicit project AI configuration marker
- produces a deterministic error before any external AI call

Recommended trigger:
- provider: `mock-fail`

Behavior:
- `TriggerAnalysis` starts as usual
- async analysis fails deterministically
- defect status rolls back to `pending_analysis`
- failure comment is written
- frontend polling surfaces the existing error message path

This keeps production behavior unchanged while making `REG-03` testable.

## Files Expected To Change

### Backend
- `/Users/jame/Workspace/bug_agent/server/internal/model/workflow.go`
- `/Users/jame/Workspace/bug_agent/server/internal/model/workflow_test.go`
- `/Users/jame/Workspace/bug_agent/server/internal/handler/defect.go`
- `/Users/jame/Workspace/bug_agent/server/internal/service/workflow_test.go`
- `/Users/jame/Workspace/bug_agent/server/internal/ai/factory.go`
- `/Users/jame/Workspace/bug_agent/server/internal/handler/agent.go` or `/Users/jame/Workspace/bug_agent/server/internal/service/analysis.go`
- new targeted handler/service tests for defect transition and analysis failure

### Frontend
- only if current detail page still exposes actions inconsistent with the backend after workflow unification
- likely file: `/Users/jame/Workspace/bug_agent/web/src/pages/defects/DefectDetail.tsx`

### Docs
- `/Users/jame/Workspace/bug_agent/docs/UAT_SMOKE_CHECKLIST_PHASE4.md`
- `/Users/jame/Workspace/bug_agent/docs/superpowers/plans/2026-04-11-defect-workflow-regression-plan.md`

## Testing Strategy

1. Add failing backend tests for the actual PRD path:
   - assign defect -> `pending_analysis`
   - `pending_analysis -> analyzing`
   - `analyzing -> pending_fix`
2. Add failing tests proving obsolete `confirmed` transitions are invalid.
3. Add deterministic analysis failure test proving:
   - async trigger starts
   - status rolls back to `pending_analysis`
   - failure comment is persisted
4. Re-run targeted browser/UAT validation for:
   - `DEF-04`
   - `REG-03`

## Risks

1. Existing historical tests still assume `confirmed`; they must be rewritten rather than patched around.
2. Deterministic failure injection must be gated out of `release` mode to avoid accidental production exposure.
3. If frontend still renders stale actions after backend alignment, a small UI action update may still be required.

## Acceptance

1. `DEF-04` becomes `PASS` in UAT.
2. `REG-03` becomes reproducible and can be verified with deterministic failure behavior.
3. Runtime defect workflow is defined in one place only.
4. No active runtime path depends on `confirmed`.
