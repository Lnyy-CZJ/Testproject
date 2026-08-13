# Requirement Decomposition Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the anti-hallucination layer: field evidence, Grounding Check, facts/suggestions separation, and unsupported fact downgrade.

**Architecture:** Add focused modules for evidence binding, grounding checks, and anti-hallucination post-processing. The LLM chain still creates draft facts, then this phase verifies those facts against the source quote and moves unsupported fact values into `test_design_suggestions`.

**Tech Stack:** Python 3.9+, Pydantic v2, pytest.

---

### Task 1: Phase-Three Tests

**Files:**
- Create: `tests/requirement_decomposition/test_phase3_anti_hallucination.py`

- [x] **Step 1: Write failing tests**

Tests cover explicit field evidence, unsupported fact detection, downgrade from facts to suggestions, and pipeline-level grounding summary.

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase3_anti_hallucination.py -q`

Expected: FAIL because evidence binder, grounding checker, and anti-hallucination post-processing are not implemented.

### Task 2: Evidence Binder

**Files:**
- Create: `requirement_decomposition/llm/evidence_binder.py`

- [x] **Step 1: Implement field evidence extraction**

Generate `FieldEvidence` entries for title, description, test_objects, constraints, state_model, permissions, and acceptance_criteria.

- [x] **Step 2: Classify evidence type**

Mark values as `explicit` when grounded in the source quote and `inferred` when not grounded.

### Task 3: Grounding Check

**Files:**
- Create: `requirement_decomposition/llm/grounding_checker.py`

- [x] **Step 1: Implement requirement-level Grounding Check**

Use field evidence to produce `passed` and `unsupported_items`.

### Task 4: Facts/Suggestions Partitioning

**Files:**
- Create: `requirement_decomposition/validator/anti_hallucination.py`
- Modify: `requirement_decomposition/pipeline.py`

- [x] **Step 1: Downgrade unsupported facts**

Remove unsupported constraints, test objects, permissions, GWT items, and state transitions from `requirement_facts`.

- [x] **Step 2: Preserve unsupported values as suggestions**

Append downgraded values to `test_design_suggestions.test_generation_hints` with field context.

- [x] **Step 3: Integrate into pipeline**

Run anti-hallucination after LLM field extraction and update `grounding_summary`.

### Task 5: Verification

**Files:**
- Modify: tests as needed

- [x] **Step 1: Run phase-three tests**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase3_anti_hallucination.py -q`

Expected: all tests pass.

- [x] **Step 2: Run all tests**

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [x] **Step 3: Run compile check**

Run: `python3 -m compileall requirement_decomposition tests/requirement_decomposition -q`

Expected: exit code 0.
