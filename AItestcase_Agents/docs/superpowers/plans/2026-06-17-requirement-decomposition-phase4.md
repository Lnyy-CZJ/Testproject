# Requirement Decomposition Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quality gates: Schema validation, quality scoring, confirmed_candidate gate, risk_tags enum validation, and state_model validation.

**Architecture:** Keep validation logic in `requirement_decomposition/validator`. The pipeline runs anti-hallucination first, then quality gate validation, then output generation. Passing requirements become `confirmed_candidate`; manual `confirmed` remains out of scope.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest.

---

### Task 1: Phase-Four Tests

**Files:**
- Create: `tests/requirement_decomposition/test_phase4_quality_gate.py`

- [x] **Step 1: Write failing tests**

Tests cover Schema validation, risk_tags enum cleanup, state_model validation, quality scoring, confirmed gate, and pipeline-level quality report.

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase4_quality_gate.py -q`

Expected: FAIL because phase-four validator modules are not implemented.

### Task 2: Schema, Risk Tag, and State Model Validators

**Files:**
- Create: `requirement_decomposition/validator/schema_validator.py`
- Create: `requirement_decomposition/validator/risk_tag_validator.py`
- Create: `requirement_decomposition/validator/state_model_validator.py`

- [x] **Step 1: Implement schema validation**

Validate Requirement objects and raw dicts using Pydantic.

- [x] **Step 2: Implement risk_tags enum validation**

Keep only PRD-approved risk tags and report enum issues.

- [x] **Step 3: Implement state_model validation**

Validate transition states, non-empty trigger, and duplicate transitions.

### Task 3: Quality Scoring and Confirmed Gate

**Files:**
- Create: `requirement_decomposition/validator/quality_validator.py`
- Create: `requirement_decomposition/validator/confirmed_gate_validator.py`

- [x] **Step 1: Implement quality scoring**

Compute completeness, traceability, evidence, grounding, schema rates, unsupported fact count, status counts, and issue list.

- [x] **Step 2: Implement confirmed_candidate gate**

Set status to `confirmed_candidate` only when configured requirements pass; otherwise keep `draft`.

### Task 4: Pipeline Integration

**Files:**
- Modify: `requirement_decomposition/pipeline.py`

- [x] **Step 1: Run validators after anti-hallucination**

Apply risk tag cleanup, state model validation, quality scoring, and confirmed gate before generating outputs.

- [x] **Step 2: Emit final quality report**

Write updated `quality_report` to top-level JSON and return result.

### Task 5: Verification

**Files:**
- Modify: tests as needed

- [x] **Step 1: Run phase-four tests**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase4_quality_gate.py -q`

Expected: all tests pass.

- [x] **Step 2: Run all tests**

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [x] **Step 3: Run compile check**

Run: `python3 -m compileall requirement_decomposition tests/requirement_decomposition -q`

Expected: exit code 0.
