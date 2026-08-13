# Requirement Decomposition Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build phase one of the requirement decomposition skill: configuration, Pydantic models, Markdown parsing, section chunking, and JSON/Markdown/test_seed output.

**Architecture:** Implement a new `requirement_decomposition` package with small modules matching the approved design. The phase-one pipeline does not call LLM; it converts Markdown sections into draft Requirement records so later phases can attach semantic extraction and evidence checks.

**Tech Stack:** Python 3.9+, Pydantic v2, PyYAML, pytest.

---

### Task 1: Phase-One Behavior Tests

**Files:**
- Create: `tests/requirement_decomposition/test_phase1_pipeline.py`

- [x] **Step 1: Write failing tests**

Tests cover config loading, Markdown section parsing, Pydantic model defaults, test_seed generation, and end-to-end phase-one output files.

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/requirement_decomposition/test_phase1_pipeline.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'requirement_decomposition'`.

### Task 2: Core Package and Data Models

**Files:**
- Create: `requirement_decomposition/__init__.py`
- Create: `requirement_decomposition/models/schema.py`
- Create: `requirement_decomposition/config/loader.py`

- [x] **Step 1: Implement Pydantic models**

Define project/source/output/config models, section models, Requirement, facts, suggestions, evidence, and pipeline result.

- [x] **Step 2: Implement config loader**

Load YAML config, merge optional `source_path`, and expose output settings.

### Task 3: Markdown Parser and Section Chunker

**Files:**
- Create: `requirement_decomposition/parser/document_parser.py`
- Create: `requirement_decomposition/chunker/section_chunker.py`

- [x] **Step 1: Implement Markdown parser**

Read Markdown file, preserve raw content, and create source metadata.

- [x] **Step 2: Implement section chunker**

Split by Markdown headings, preserve heading path and source quote.

### Task 4: Output Generators and Pipeline

**Files:**
- Create: `requirement_decomposition/generator/json_generator.py`
- Create: `requirement_decomposition/generator/markdown_generator.py`
- Create: `requirement_decomposition/generator/test_seed_generator.py`
- Create: `requirement_decomposition/pipeline.py`

- [x] **Step 1: Implement generators**

Write full JSON, per-requirement Markdown, and test_seed JSON output.

- [x] **Step 2: Implement phase-one pipeline**

Load config, parse Markdown, chunk sections, create draft requirements, generate outputs, and return a structured result.

### Task 5: Verification

**Files:**
- Modify: `pyproject.toml`

- [x] **Step 1: Include new package in setuptools config**

Add `requirement_decomposition*` to package discovery.

- [x] **Step 2: Run phase-one tests**

Run: `pytest tests/requirement_decomposition/test_phase1_pipeline.py -q`

Expected: all tests pass.

- [x] **Step 3: Run broader pytest suite if practical**

Run: `pytest -q`

Expected: either all tests pass, or report unrelated pre-existing collection/import failures.
