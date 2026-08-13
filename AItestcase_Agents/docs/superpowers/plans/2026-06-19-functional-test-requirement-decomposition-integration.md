# Functional Test Requirement Decomposition Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use TDD for behavior changes.

**Goal:** Integrate `requirement_decomposition` into the `functional_test` test point generation flow so test point generation consumes structured `test_seed` context when a source document path is available.

**Architecture:** Keep the existing LangGraph workflow intact. Add a narrow preparation layer before `GeneratorPointWorkflow` runs. Store structured context in workflow state and make `build_requirement_context()` prefer it over raw document text.

**Tech Stack:** Python 3.9+, LangGraph, LangChain, Pydantic v2, pytest.

---

### Task 1: Regression Tests

**Files:**
- Create: `tests/functional_test/test_requirement_decomposition_integration.py`

- [x] **Step 1: Test context priority**

Verify `build_requirement_context()` returns `requirement_context` before `document`.

- [x] **Step 2: Test test_seed formatting**

Verify `build_test_seed_requirement_context()` converts a `TestSeedRecord` into readable context containing module, feature, objects, constraints, permissions, expected results, and uncertain items.

- [x] **Step 3: Test decomposition fallback**

Verify failed decomposition returns empty context metadata and does not raise.

- [x] **Step 4: Run tests and confirm RED**

Run: `python3 -m pytest tests/functional_test/test_requirement_decomposition_integration.py -q`

Expected: FAIL because integration helpers are not implemented yet.

### Task 2: Workflow Integration

**Files:**
- Modify: `agents/functional_test/workflows/case_generator_workflow.py`

- [x] **Step 1: Extend workflow state**

Add optional state fields for `document_path`, `requirement_context`, and `decomposition_report`.

- [x] **Step 2: Add test_seed context formatter**

Implement a deterministic formatter from `TestSeedRecord` to compact Markdown-like context.

- [x] **Step 3: Add decomposition preparation helper**

Implement a helper that calls `run_decomposition()` only when `document_path` is available, then returns context and metadata. Failures must be logged and downgraded.

- [x] **Step 4: Wire into test point generation**

Call the helper before invoking `GeneratorPointWorkflow` and pass `requirement_context` into the subworkflow.

### Task 3: Tool Input Propagation

**Files:**
- Modify: `agents/common/tools/tools.py`

- [x] **Step 1: Preserve absolute document path**

Return the resolved path from document reading.

- [x] **Step 2: Pass document_path into workflows**

Set `document_path` in both `generator_test_points` and `generator_case` workflow inputs.

### Task 4: Prompt Updates

**Files:**
- Modify: `agents/functional_test/prompts/generator_test_point.py`
- Modify: `agents/functional_test/prompts/verify_test_points_coverage.py`

- [x] **Step 1: Add structured context rules**

Tell the model how to consume `test_seed` fields and how to treat uncertain items.

- [x] **Step 2: Keep JSON output unchanged**

Do not change output schema.

### Task 5: Verification

- [x] **Step 1: Run focused tests**

Run: `python3 -m pytest tests/functional_test/test_requirement_decomposition_integration.py -q`

- [x] **Step 2: Run related tests**

Run: `python3 -m pytest tests/requirement_decomposition/test_llm_only_pipeline.py tests/functional_test/test_requirement_decomposition_integration.py -q`

- [x] **Step 3: Run compile check**

Run: `python3 -m compileall agents/functional_test agents/common requirement_decomposition tests/functional_test -q`
