# Skill Runtime Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Tommy's broad installed-skill prompt injection with a runtime skill system that indexes skill metadata, selects relevant skills per turn, loads bounded guidance progressively, and records activation diagnostics.

**Architecture:** Add a focused `skill_runtime` package for metadata parsing, filesystem indexing, candidate resolution, progressive loading, and activation diagnostics. Keep `skills_forge` responsible for proposing/mining/promoting skills, but move runtime loading decisions into `ContextBuilder`. The old `Installed Skills` prompt section is removed in favor of compact `Available Skill Index` and task-specific `Selected Skills`.

**Tech Stack:** Python 3.11, dataclasses/Pydantic-adjacent DTOs, existing PostgreSQL skill catalog, existing prompt snapshot metadata, pytest.

---

## File Structure

- Create `backend/app/agent_framework/skill_runtime/types.py`: DTOs for metadata, candidates, selected skills, loaded skills, and activation traces.
- Create `backend/app/agent_framework/skill_runtime/metadata.py`: safe frontmatter parsing, metadata normalization, signature generation, path validation helpers.
- Create `backend/app/agent_framework/skill_runtime/indexer.py`: filesystem-to-catalog sync for `SKILL.md` packages under `data/agents/<agent>/skills`.
- Create `backend/app/agent_framework/skill_runtime/resolver.py`: keyword, trigger, explicit mention, vector, tool, and metric ranking.
- Create `backend/app/agent_framework/skill_runtime/loader.py`: bounded metadata/summary/excerpt/full loading and linked asset discovery.
- Create `backend/app/agent_framework/skill_runtime/__init__.py`: stable exports.
- Modify `backend/app/agent_framework/skills_forge/catalog.py`: reuse `skill_runtime.metadata` parser and return richer summaries without keeping duplicate parsing logic.
- Modify `backend/app/agent_framework/prompt_context/builder.py`: call indexer/resolver/loader and pass skill context into sections; persist activation metadata.
- Modify `backend/app/agent_framework/prompt_context/sections.py`: replace `Installed Skills` with `Available Skill Index` and `Selected Skills`.
- Modify `backend/app/agent_framework/prompt_context/budgets.py`: add separate budgets for the two skill sections.
- Modify `backend/app/agent_framework/prompt_context/types.py`: add optional `skill_activations` to `RenderedContext.snapshot()`.
- Test `backend/tests/skill_runtime/test_metadata.py`.
- Test `backend/tests/skill_runtime/test_indexer_loader_resolver.py`.
- Modify `backend/tests/prompt_context/test_context_builder.py`.

## Acceptance Criteria

- A clear skill query selects the expected skill and injects only that skill's bounded guidance.
- A generic query keeps the available index compact and does not inject unrelated skill bodies.
- The old broad `Installed Skills` section no longer appears in prompt context.
- Skill activation diagnostics include candidates, selected skills, reason codes, missing tools, and injected character counts.
- The same input and catalog state produce deterministic selected skill ordering.
- Path traversal for skill reads and asset reads is rejected.
- Existing proposal/version APIs remain compatible.

## Tasks

### Task 1: Metadata Parser and DTOs

**Files:**
- Create: `backend/app/agent_framework/skill_runtime/types.py`
- Create: `backend/app/agent_framework/skill_runtime/metadata.py`
- Create: `backend/app/agent_framework/skill_runtime/__init__.py`
- Test: `backend/tests/skill_runtime/test_metadata.py`

- [ ] Write failing tests for YAML-like frontmatter parsing, list fields, nested `metadata.hermes`, invalid names, path traversal, and deterministic signatures.
- [ ] Run `cd backend && uv run pytest tests/skill_runtime/test_metadata.py -q` and verify failures are due to missing modules.
- [ ] Implement `SkillMetadata`, `SkillPackage`, `parse_skill_markdown`, `normalize_skill_path`, and `signature_text`.
- [ ] Run metadata tests and make them pass.

### Task 2: Indexer and Catalog Parser Replacement

**Files:**
- Create: `backend/app/agent_framework/skill_runtime/indexer.py`
- Modify: `backend/app/agent_framework/skills_forge/catalog.py`
- Test: `backend/tests/skill_runtime/test_indexer_loader_resolver.py`

- [ ] Write failing tests using a fake store proving filesystem skills are indexed into `store.skill_catalog.register_skill` with status `active`, metadata, signature, tool chain, and deterministic relative paths.
- [ ] Write a failing test proving `SkillCatalog.list_skills()` uses the shared parser and does not keep a duplicate frontmatter parser.
- [ ] Implement `SkillIndexer.sync()` with path safety, invalid-package diagnostics, and no behavior change for proposals.
- [ ] Remove the local `_parse_frontmatter` implementation from `skills_forge/catalog.py`.
- [ ] Run focused tests.

### Task 3: Resolver and Loader

**Files:**
- Create: `backend/app/agent_framework/skill_runtime/resolver.py`
- Create: `backend/app/agent_framework/skill_runtime/loader.py`
- Test: `backend/tests/skill_runtime/test_indexer_loader_resolver.py`

- [ ] Write failing tests for explicit mention, trigger match, domain match, semantic fallback via existing activator rows, tool dependency diagnostics, metrics downranking, and deterministic tie-breaking.
- [ ] Write failing tests for progressive load levels: `metadata`, `summary`, `excerpt`, `full`, and asset listing; reject `../` asset paths.
- [ ] Implement resolver scoring with reason codes and bounded selection.
- [ ] Implement loader with per-skill char budgets and linked file discovery.
- [ ] Run focused tests.

### Task 4: ContextBuilder Integration and Old Path Removal

**Files:**
- Modify: `backend/app/agent_framework/prompt_context/builder.py`
- Modify: `backend/app/agent_framework/prompt_context/sections.py`
- Modify: `backend/app/agent_framework/prompt_context/budgets.py`
- Modify: `backend/app/agent_framework/prompt_context/types.py`
- Test: `backend/tests/prompt_context/test_context_builder.py`

- [ ] Write failing tests proving `Installed Skills` is absent, `Available Skill Index` is present, selected skill content appears only when relevant, unrelated skills are not injected, and prompt snapshots carry `skill_activations`.
- [ ] Wire `ContextBuilder` to `SkillIndexer`, `SkillResolver`, and `SkillLoader`.
- [ ] Replace the single `skills` section with `skill_index` and `selected_skills`.
- [ ] Ensure activation metadata is persisted through `persist_snapshot(metadata=...)`.
- [ ] Run prompt context tests.

### Task 5: Verification and Cleanup

**Files:**
- Any files touched above.

- [ ] Run `cd backend && uv run pytest tests/skill_runtime tests/prompt_context/test_context_builder.py tests/skills_forge/test_skills_forge.py -q`.
- [ ] Run `cd backend && uv run ruff check app tests`.
- [ ] Search for old broad prompt text: `rg "Installed Skills|No installed skills|_parse_frontmatter" backend/app/agent_framework`.
- [ ] Remove remaining redundant runtime parsing/injection code, keeping API/UI list compatibility where needed.
- [ ] Run final targeted tests again after cleanup.

