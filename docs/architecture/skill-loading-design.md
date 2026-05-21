# Skill Loading Design

## Purpose

This document defines the target design for upgrading Tommy's skill module from a
simple installed-skill prompt section into a runtime capability system closer to
advanced agent products.

The goal is not to make skills own orchestration. Skills should package reusable
domain procedures, rules, examples, and assets. The runtime should decide when a
skill is relevant, load only the useful parts, explain that decision, and record
whether the skill helped.

## Current Baseline

Tommy already has useful foundations:

- `SkillCatalog` scans `SKILL.md` files under the agent data root.
- Skill proposals can be created, applied, rejected, and versioned.
- PostgreSQL has skill proposal, version, catalog, embedding, status, and metric
  tables.
- `ContextBuilder` includes installed skills in the model-visible context.
- `skills_forge` can mine, validate, promote, retire, and track skill catalog
  records.

The main limitation is that installed skills are still treated mostly as prompt
text. The runtime does not yet perform strong skill discovery, candidate ranking,
progressive loading, activation tracing, or post-run feedback.

## Design Principles

1. Skills are procedural memory, not workflow orchestration.
   A skill describes how to perform a class of tasks. LangGraph remains
   responsible for fixed business stages, retries, approvals, and state
   transitions.

2. Skill loading must be progressive.
   The runtime should first load metadata, then select candidates, then inject
   bounded excerpts or summaries, and only read full skill content when needed.

3. Context budget is a first-class constraint.
   No vertical domain should solve relevance by dumping every matching skill into
   the prompt.

4. Runtime state remains in PostgreSQL.
   Skill files are human-editable source material. PostgreSQL is the runtime
   index for activation, search, status, metrics, and provenance.

5. Every activation should be explainable.
   A run trace should answer: which skills were candidates, which were loaded,
   why they were loaded, how many characters they consumed, and what happened
   after use.

6. Tool access should be explicit.
   Skills may recommend or require tools, but trusted runtime values and
   permissions are still enforced by the tool runtime, not by skill text.

## Target Skill Package

Each skill should remain centered on a `SKILL.md` file, with frontmatter expanded
into structured metadata.

Recommended frontmatter:

```yaml
name: xhs-content-planner
description: Plan, draft, validate, and prepare Xiaohongshu notes.
version: 1
domains:
  - xhs
  - content-ops
triggers:
  - 小红书
  - xhs
  - 种草文案
  - 标题优化
required_tools:
  - create_xhs_content_job
  - validate_xhs_note_json
  - check_xhs_content_risk
safety_notes:
  - Do not publish directly without explicit human confirmation.
activation_examples:
  - "帮我写一篇小红书笔记"
  - "检查这篇小红书内容有没有风险"
input_contract: "User brief, product facts, desired audience, optional images."
output_contract: "Structured title/body/hashtags/risk report."
```

The markdown body should be treated as the deeper instruction layer. It can
include:

- task boundaries
- step-by-step procedure
- quality bar
- examples
- common failure modes
- tool usage notes
- domain-specific checks
- output templates

Large examples, templates, rubrics, and assets should live under the skill
directory and be loaded only when the selected skill requests them.

## Runtime Loading Pipeline

The target loading pipeline has five stages.

### 1. Index

At startup, maintenance time, or skill apply time:

- read `SKILL.md` frontmatter
- parse metadata and body summary
- compute or refresh signature text
- write searchable metadata to PostgreSQL
- embed signature text when an embedder is available
- mark missing or invalid skills as stale, not silently ignored

Source of truth:

- file system: full skill content and assets
- PostgreSQL: runtime index, status, metrics, embedding, provenance

### 2. Candidate Retrieval

For each run, the resolver should produce candidates from multiple signals:

- explicit user mention of a skill name or domain
- keyword and trigger matching
- PostgreSQL full-text search over name, description, triggers, and signature
- pgvector similarity over skill signature embeddings
- required tool compatibility
- current session context pact and active goals
- historical success and failure metrics

The output of this stage is a ranked list of candidate skill IDs with scores and
reason codes.

Example reason codes:

- `explicit_mention`
- `trigger_match`
- `domain_match`
- `semantic_match`
- `required_tool_match`
- `context_pact_match`
- `historical_success`

### 3. Selection

The resolver should select a small bounded set, usually one to three skills.

Selection should consider:

- score
- current prompt budget
- skill status: `active`, `shadow`, `retired`
- safety requirements
- missing tool dependencies
- conflicts between candidate skills
- recent failures in the same session

Retired skills should not be injected by default. Shadow skills can be evaluated
in trace or validation mode, but should not silently control production behavior.

### 4. Progressive Load

The resolver should expose multiple levels:

- `metadata`: name, description, triggers, required tools
- `summary`: concise operating guidance generated from the skill
- `excerpt`: selected sections relevant to the task
- `full`: entire `SKILL.md`, only when explicitly needed
- `assets`: examples, templates, or reference files, loaded by request

`ContextBuilder` should usually inject `summary` or `excerpt`, not `full`.

### 5. Trace And Feedback

Each run should persist a skill activation record:

- run ID
- session ID
- agent ID
- candidate skill IDs
- selected skill IDs
- scores
- reason codes
- injected character count
- missing tools
- activation mode
- post-run status, if known

After a run, metrics should update the skill catalog:

- invocation count
- success count
- failure count
- average latency
- tool error count
- human rejection or approval signals
- optional user rating

## ContextBuilder Integration

Skill loading should be owned by `ContextBuilder`, not by graph nodes.

Recommended flow:

```text
state + session + context pact + last user message
  -> SkillResolver.retrieve_candidates
  -> SkillResolver.select
  -> SkillLoader.load_selected
  -> ContextBuilder renders "Selected Skills" section
  -> prompt snapshot stores activation diagnostics
```

The current "Installed Skills" section should eventually become two separate
sections:

- `Available Skill Index`: compact list of high-level capabilities, usually
  small and cheap.
- `Selected Skills`: task-specific instructions from selected skills, bounded
  by context budget.

This keeps the model aware that skills exist without flooding every run with
unrelated procedures.

## Proposed Components

### SkillMetadataParser

Parses frontmatter and validates fields.

Responsibilities:

- normalize paths
- parse YAML frontmatter
- validate required fields
- extract triggers, domains, tools, and contracts
- produce a deterministic signature string

### SkillIndexer

Synchronizes file-system skill packages into PostgreSQL.

Responsibilities:

- scan skill roots
- upsert catalog rows
- update signature embeddings
- detect stale files
- report invalid packages

### SkillResolver

Ranks and selects skills for a run.

Responsibilities:

- combine keyword, FTS, vector, explicit mention, and context signals
- enforce status and tool dependency policies
- return reasoned candidate and selected lists

### SkillLoader

Loads the selected skill content progressively.

Responsibilities:

- load metadata, summaries, excerpts, full content, and assets
- enforce prompt budgets
- avoid duplicate loading
- surface missing files as trace warnings

### SkillActivationRecorder

Persists activation and outcome data.

Responsibilities:

- store candidate and selected diagnostics
- attach activation metadata to prompt snapshots
- update skill usage metrics after run completion

## Schema Direction

Existing `skills` fields already cover part of the target:

- `name`
- `relative_path`
- `description`
- `signature`
- `signature_embedding`
- `tool_chain_json`
- `status`
- counters and metrics

Likely additions or normalized metadata fields:

- `version`
- `domains_json`
- `triggers_json`
- `required_tools_json`
- `safety_notes_json`
- `input_contract`
- `output_contract`
- `last_indexed_at`
- `source_sha256`
- `validation_errors_json`

New table candidates:

- `skill_activations`: per-run candidate and selected skill diagnostics
- `skill_asset_refs`: optional indexed references to examples, templates, or
  other skill-local resources

Do not add these tables before the resolver contract is stable. Start with
metadata parsing and activation diagnostics in prompt snapshot metadata if that
is enough for the first implementation slice.

## Tool Runtime Integration

Skills should be allowed to declare tool needs, but they should not directly
grant permission.

The runtime should use skill metadata to:

- warn when selected skills require missing tools
- optionally narrow tool schemas for a vertical graph
- record which skill influenced a tool call
- require approval for high-risk skill-tool combinations

Permission decisions remain in `ToolRuntime` and `PermissionPolicy`.

## LangGraph Boundary

Use skills for domain procedures and reusable task knowledge.

Extend LangGraph when the vertical scenario needs:

- fixed stages
- durable state transitions
- branching
- retries
- human approval gates
- scheduled or background work
- multi-step tool execution
- post-run evaluation

For a vertical agent, the recommended architecture is:

```text
LangGraph workflow: business stages and control flow
ContextBuilder: context and selected skill injection
Skills: domain playbooks, rubrics, examples, and operating rules
Tools: deterministic external actions
PostgreSQL: runtime state, domain objects, traces, and metrics
Evals: scenario-specific success criteria
```

## Vertical Scenario Example: Xiaohongshu Content Agent

Recommended graph stages:

```text
intake
  -> brief validation
  -> content planning
  -> draft generation
  -> risk check
  -> structured JSON validation
  -> preview preparation
  -> human confirmation
  -> publish assistance
  -> post-run review
```

Skills:

- content style guide
- title patterns
- audience positioning rules
- forbidden claims and risk checklist
- example note templates

Tools:

- `create_xhs_content_job`
- `build_chatgpt_xhs_prompt`
- `validate_xhs_note_json`
- `check_xhs_content_risk`
- XHS browser automation tools

PostgreSQL domain records:

- content jobs
- briefs
- drafts
- risk reports
- approvals
- publishing attempts
- performance feedback

## Implementation Roadmap

### Stage 1: Metadata Without Behavior Change

- Add a robust frontmatter parser.
- Define the expanded skill metadata DTO.
- Index metadata into the existing skill catalog where possible.
- Keep current prompt behavior unchanged.
- Add tests for parsing, path safety, invalid metadata, and catalog sync.

### Stage 2: Candidate Resolver

- Implement keyword and trigger matching.
- Add FTS search over existing catalog fields.
- Return candidates with scores and reason codes.
- Add tests proving relevant skills rank above irrelevant skills.

### Stage 3: Bounded Context Injection

- Replace the current broad installed-skill prompt section with selected skill
  injection.
- Keep a compact available-skill index.
- Persist selected skill diagnostics in prompt snapshot metadata.
- Add tests for prompt budget and deterministic ordering.

### Stage 4: Vector And Metrics

- Use signature embeddings for semantic matching.
- Update invocation and outcome metrics after runs.
- Use metrics as a weak ranking signal.
- Add failure downranking for repeated bad activations.

### Stage 5: Assets, Tools, And UI Trace

- Add progressive asset loading.
- Link selected skills to tool calls.
- Show skill candidates, selected skills, reason codes, and injected chars in
  the frontend trace.

## Acceptance Criteria

The optimized skill loader should satisfy these checks:

- A run with a clear domain query selects the expected skill.
- A generic query does not load unrelated vertical skills.
- Selected skill content stays within the configured context budget.
- The prompt snapshot records selected skills and reason codes.
- Skill activation is deterministic for the same input and catalog state.
- Missing tools or invalid skill metadata are visible as diagnostics.
- Existing session, run, memory, approval, and tool behavior remains stable.

## Non-Goals

- Do not replace LangGraph workflow logic with skill text.
- Do not make every skill a Python plugin in the first iteration.
- Do not load full skill files into every prompt.
- Do not let skill metadata bypass tool permissions.
- Do not introduce a separate runtime database for skill state.

## Bottom Line

Skills should make Tommy more domain-aware without making the core loop larger.
The important upgrade is the loading path: index first, retrieve candidates,
select a small set, load progressively, inject with budget, and record why it
happened. LangGraph should continue to own vertical workflow control, while
skills provide reusable domain procedures and quality standards.
