# Requirement Decomposition Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the LLM decomposition chain for prompt loading, injectable LLM calls, Requirement splitting, and test object / constraint / state / permission / GWT extraction.

**Architecture:** Keep phase-two LLM behavior behind small modules under `requirement_decomposition/llm`. The pipeline accepts an injectable client for tests and future production clients; each extractor consumes one Requirement draft plus its source section and returns validated Pydantic data.

**Tech Stack:** Python 3.9+, Pydantic v2, PyYAML, pytest.

---

### Task 1: Phase-Two Tests

**Files:**
- Create: `tests/requirement_decomposition/test_phase2_llm_chain.py`

- [x] **Step 1: Write failing tests**

Tests cover prompt loading, JSON fence parsing, individual LLM extraction, and end-to-end pipeline integration with an injectable fake client.

- [x] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase2_llm_chain.py -q`

Expected: FAIL because prompt loader, client, splitter, extractor modules, and `llm_client` pipeline argument are not implemented yet.

### Task 2: Prompt Loader and Prompt Files

**Files:**
- Create: `requirement_decomposition/llm/prompt_loader.py`
- Create: `prompts/requirement_split.md`
- Create: `prompts/test_object_extract.md`
- Create: `prompts/constraint_extract.md`
- Create: `prompts/state_model_extract.md`
- Create: `prompts/permission_extract.md`
- Create: `prompts/gwt_generate.md`

- [x] **Step 1: Implement prompt loader**

Load prompt markdown files, parse `prompt_name` and `version`, and render `{{ variable }}` placeholders.

- [x] **Step 2: Add phase-two prompt templates**

Each template must declare prompt metadata and require JSON-only output.

### Task 3: LLM Client and JSON Parsing

**Files:**
- Create: `requirement_decomposition/llm/llm_client.py`

- [x] **Step 1: Implement client protocol and call helper**

Define `LLMClient` protocol and `LLMCall` metadata object.

- [x] **Step 2: Implement robust JSON parsing**

Parse raw JSON and fenced JSON responses. This is shared by splitter and extractors.

### Task 4: Requirement Splitter and Extractors

**Files:**
- Create: `requirement_decomposition/llm/requirement_splitter.py`
- Create: `requirement_decomposition/llm/test_object_extractor.py`
- Create: `requirement_decomposition/llm/constraint_extractor.py`
- Create: `requirement_decomposition/llm/state_model_extractor.py`
- Create: `requirement_decomposition/llm/permission_extractor.py`
- Create: `requirement_decomposition/llm/gwt_generator.py`

- [x] **Step 1: Implement Requirement draft parsing**

Transform LLM requirement split output into typed drafts.

- [x] **Step 2: Implement field extractors**

Transform LLM extraction output into existing Pydantic field models.

### Task 5: Pipeline Integration

**Files:**
- Modify: `requirement_decomposition/pipeline.py`

- [x] **Step 1: Add injectable LLM client to `run_decomposition`**

When LLM is enabled, use the LLM chain through an injected client or the default project LLM client.

- [x] **Step 2: Preserve outputs**

Generated requirements still write JSON/Markdown/test_seed files. Phase two requirements remain `draft` until evidence and Grounding Check are implemented in phase three.

### Task 6: Verification

**Files:**
- Modify: tests as needed

- [x] **Step 1: Run phase-two tests**

Run: `python3 -m pytest tests/requirement_decomposition/test_phase2_llm_chain.py -q`

Expected: all tests pass.

- [x] **Step 2: Run all tests**

Run: `python3 -m pytest -q`

Expected: all tests pass.

- [x] **Step 3: Run compile check**

Run: `python3 -m compileall requirement_decomposition tests/requirement_decomposition -q`

Expected: exit code 0.
