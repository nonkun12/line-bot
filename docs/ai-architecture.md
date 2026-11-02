# AI architecture — canonical inventory and operating model

This architecture groups the existing implementation into layers without
claiming that every entry is a separate, continuously running LLM.

## Layers

1. **Management and coordination** — Management AI classifies and plans work;
   Control Tower observes outcomes and produces bounded self-improvement
   decisions. They coordinate; neither bypasses approval gates.
2. **Discovery and planning** — Idea AI and Work Finder identify opportunities
   and candidate tasks. Discovery output is not execution authorization.
3. **Specialist execution** — 23 existing `agents/*/node.py` handlers, grouped
   by domain in `core.agent_architecture.SPECIALIST_MODULES`.
4. **Quality and safety** — Creator-Critic challenges proposals; REA performs
   read-only safety/scope inspection. A review pass is not a merge approval.
5. **Operations and recovery** — Maintenance AI diagnoses evidence; Recovery AI
   decides bounded resume/hold paths; Hermes Advisor provides bounded local
   assistance. Maintenance remains read-only.

## Inventory counts

- 23 specialist handler modules.
- 9 orchestration, planning, review, safety, and operations components.
- 32 total inventory units. This is not a count of independent model instances.
- The 18 `AgentRole` values in `core.multi_agent` are routing/task categories,
  not additional agents, and are deliberately not added to this count.

## Runtime truth

The inventory is metadata only. It does not import handlers, instantiate model
providers, grant tool permissions, or change routing. Runtime activation and
health must be reported separately from source-code presence. Missing or
unverified runtime evidence must be displayed as unknown, never as running.

## Safety boundaries

- Keep read-only requests outside the development/PR route.
- Discovery and proposal generation never grants execution approval.
- Specialist permissions remain least-privilege and repository-scoped.
- Autonomous code changes use branches, tests, review, and separate merge/deploy
  gates.
- Maintenance AI does not retry tasks, clear holds, write files, merge, or deploy.
- Recovery AI may only resume through the existing explicit cause-fixed and
  review-confirmation gates.
