# Bilingual Stage Directory Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 16 个关系阶段的截图交付目录改为“英文标签+中文释义”，同时保持内部阶段枚举、E2E Case、渲染清单和 QA 引用一致。

**Architecture:** 内部 `target_stage` 继续使用稳定枚举；在 `dataset.cjs` 增加唯一的阶段到交付目录映射，所有图片路径消费者通过同一函数取目录名。重新原子生成截图与源数据，避免对 448 个路径做不可追溯的散落字符串替换。

**Tech Stack:** Node.js CommonJS、Playwright、Node test runner、Python E2E loader。

**Spec:** 用户本轮请求及既有 16 阶段关系表。

## Global Constraints

- 目录名严格使用下方 16 个字面量，不添加空格、下划线或括号。
- `target_stage`、`case_id` 和黄金阶段保持原枚举，不改后端协议。
- 根目录已有散装 PNG 不删除、不覆盖。
- E2E media、manifest 和 QA 首尾图路径必须指向新目录。
- 不提交或推送 Git；所有修改留在用户当前工作区。

---

### Task 1: 冻结双语目录行为

**Files:**
- Modify: `tests/chat_fixture_generator.test.cjs`

**Interfaces:**
- Consumes: `artifacts.buildRenderTasks`、`artifacts.writeSourceArtifacts`、`qa.buildContactSheetPlans`、`generator.assertFreshDestinations`。
- Produces: 对 16 个新目录字面量及下游路径的失败回归测试。

- [x] **Step 1: 添加使用手写目录字面量的行为测试**
- [x] **Step 2: 运行目标测试，确认因仍输出旧枚举目录而失败**

### Task 2: 集中实现目录映射

**Files:**
- Modify: `tools/chat_fixture_generator/dataset.cjs`
- Modify: `tools/chat_fixture_generator/artifacts.cjs`
- Modify: `tools/chat_fixture_generator/qa.cjs`
- Modify: `tools/chat_fixture_generator/generate.cjs`
- Modify: `tests/chat_fixture_generator.test.cjs`

**Interfaces:**
- Produces: `stageDirectoryName(stage): string`，非法枚举抛出 `RangeError`。
- Consumers: 渲染任务、E2E media、输出结构校验、QA 图片索引、生成预检和原子提交。

- [x] **Step 1: 在 `dataset.cjs` 定义 16 项冻结映射与查询函数**
- [x] **Step 2: 将所有交付图片路径消费者切换到该查询函数**
- [x] **Step 3: 保留 Transcript/Gold 的内部枚举目录与标签**
- [x] **Step 4: 运行目标测试，确认新路径契约通过**
- [x] **Step 5: 运行完整 Node 测试，排除协议和渲染回归**

### Task 3: 原子更新正式数据集

**Files:**
- Replace generated directories under: `/Users/admin/人际关系项目/dating assitsatant/测试数据/聊天截图测试数据/`
- Replace generated artifacts under: `datasets/relationship-stage-positive-v1/`

**Interfaces:**
- Consumes: `npm run generate:positive-stages`。
- Produces: 16 个双语目录、448 张 PNG、80 份 Case/Transcript、黄金标注、manifest 与 QA。

- [x] **Step 1: 将当前 16 个旧阶段目录与源数据移动到废纸篓中的唯一备份目录**
- [x] **Step 2: 运行完整生成命令，原子发布新目录和源数据**
- [x] **Step 3: 运行 `npm run validate:positive-stages`**
- [x] **Step 4: 使用正式 Python CLI 加载并解码 80 Case/448 media**
- [x] **Step 5: 核对 16 个目录字面量、448 个唯一 SHA 和根级历史 PNG**
