---
description: Spawn multiple agents in parallel — smart context sharing or direct launch
agent: build
subtask: true
---

You are orchestrating parallel agents. The user's request is:

**$ARGUMENTS**

---

## Step 1 — Parse the request

Extract from `$ARGUMENTS`:

1. **Tasks** — what each agent should do. Tasks may be:
   - Pipe-separated: `task one | task two | task three`
   - Comma-separated list after a colon: `fix: thing A, thing B, thing C`
   - Natural language enumeration: `fix the X, update the Y, and rewrite the Z`

2. **Flags** (anywhere in the string):
   - `--shared` — explicitly requests shared context gathering before spawning
   - `--all` — no cap on agent count; spawn one agent per identifiable sub-task
   - `--direct` — skip context gathering, spawn immediately regardless of task overlap

3. **How many agents** — default: one per task. With `--all`: decompose the request into as many sub-tasks as make sense and spawn one agent each.

---

## Step 2 — Decide: shared context or direct?

Apply this decision tree:

```
Do the tasks operate on the SAME files / data / output?
    YES  →  SHARED MODE  (gather context once, pass to all agents)
    NO   →  DIRECT MODE  (spawn immediately, each agent discovers its own context)

--shared flag?  → always SHARED MODE
--direct flag?  → always DIRECT MODE
```

**Examples of SHARED:**
- "Fix the BM25 scorer AND fix the eval test for it" → both need to read retriever.py
- "Update search_agent.md AND rag_assistant.md for the same new rule" → both need to see current prompt content
- "Run tests in batch A, batch B, batch C" → all need the same test harness state

**Examples of DIRECT:**
- "Commit the changes AND update the helm chart" → totally different files/branches
- "Write a sequence diagram AND write an architecture diagram" → independent creative tasks
- "Research topic X AND research topic Y" → independent lookups

---

## Step 3 — SHARED MODE: gather context once

If SHARED MODE, identify what context is shared across tasks and gather it **before** spawning any agent. Run the minimum set of reads/commands needed to answer: "what do all agents need to know?"

Gather that context. Then include it verbatim in **every** agent's prompt so no subagent wastes tokens re-reading the same files.

Typical shared context for this codebase:
- Current file contents: read the relevant files
- Current state: run `python eval/baseline.py` or retrieve test results
- Corpus state: read relevant JSONL entries
- Prompt contents: read prompts/rag_assistant.md and/or prompts/search_agent.md

---

## Step 4 — Spawn agents simultaneously

Use the Task tool. **All agents must be launched in a single response** — send one message with multiple parallel Task tool calls. Never launch sequentially unless task N explicitly depends on the output of task N-1.

**Prompt construction rules:**

For SHARED MODE — prefix every agent prompt with:
```
SHARED CONTEXT (pre-gathered — do not re-read these files):
<paste the gathered context here>
---
YOUR TASK:
<specific task for this agent>
```

For DIRECT MODE — each agent's prompt is self-contained:
```
<specific task for this agent, with enough context for the agent to know where to start>
```

**--all mode:** decompose the goal into the maximum number of meaningful parallel units. There is no cap. If the user said "fix all 8 failing tests", spawn 8 agents.

**Agent type selection:**
- Code changes / file edits → `general`
- Pure research / reading → `explore`
- Git commit → `git-committer`
- Default → `general`

---

## Step 5 — Synthesise results

After all agents complete, synthesise their outputs:
- Report what each agent did (1–2 lines per agent)
- Flag any conflicts (two agents modified the same file differently)
- If commits are needed: spawn a single `git-committer` agent after all work is done
- If tests need verification: run `python eval/baseline.py` or `promptfoo eval` after work completes

---

## Examples

```
/parallel fix the ennane retrieval bug | update the eval test for it
→ SHARED MODE: read retriever.py + vocabulary.jsonl first
→ spawn 2 agents with shared context

/parallel --all fix the 5 failing promptfoo tests
→ SHARED MODE: run promptfoo eval to get current failures, read affected entries
→ spawn 5 agents (one per failing test) with shared failure context

/parallel update helm chart | update kyma values
→ DIRECT MODE: different branches/files
→ spawn 2 agents immediately, no shared context needed

/parallel --direct commit main | commit helm | commit kyma
→ DIRECT MODE (explicit flag): 3 git-committer agents simultaneously

/parallel research BM25 late-chunking best practices | research RRF parameter tuning
→ DIRECT MODE: independent research
→ spawn 2 explore agents simultaneously
```
