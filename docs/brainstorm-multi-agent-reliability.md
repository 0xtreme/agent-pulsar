# Brainstorm: Multi-Agent Reliability Architecture

**Date:** 2026-03-19
**Status:** Brainstorming — not yet a design decision

---

## The Problem

Single-agent personal assistants (OpenClaw, Hermes, etc.) degrade as memory grows.
Once memory.md or context reaches a certain size, the agent:
- Forgets things it previously knew
- Hallucinates or confuses contexts
- Misses instructions buried in long context
- Mixes up domains (work vs personal vs fitness)

This is confirmed by research:
- "Context rot" — model accuracy degrades as input context grows
- "Lost-in-the-middle" — LLMs exhibit recency bias and overlook mid-passage information
- OpenAI's o3 hallucinated 33% on factual benchmarks (more than its predecessor)
- OpenClaw: 512 security vulnerabilities, $300-750/month runaway costs, agents making
  unsanctioned purchases

**Core insight:** The problem isn't "bad AI." It's too much irrelevant context
diluting the model's attention. Small, focused context = reliable agent.

---

## Pain Point Validation

Before jumping to multi-agent as the solution, we need to be honest about which
problems actually require it vs. which are solvable other ways.

| Pain Point | Multi-agent needed? | Real solution |
|---|---|---|
| Credential security | **No** | Vault + MCP + Token Broker (already designed) |
| Hallucination | **Partially** | Small, relevant context (achievable either way) |
| Context confusion | **Yes** | Structural isolation between domains |
| Degradation over time | **Yes** | Capped memory per agent, no unbounded growth |
| Catastrophic actions | **Partially** | Guardrails + approval flows (not agent count) |
| Coordination reliability | **Multi-agent makes this WORSE** | Need strong deterministic supervisor |

**The genuine case for multi-agent:** Context confusion and degradation over time.
These are the problems that destroy user trust. Once the assistant mixes up your
work and personal contexts, or forgets things it knew last week, you stop using it.

**The honest tradeoff:** Multi-agent swaps one type of unreliability (context rot)
for another (coordination complexity). The deterministic supervisor is how we
manage that tradeoff — it needs to be rock-solid because it's the foundation
everything else rests on.

**What multi-agent does NOT solve on its own:**
- Security → already handled by Vault + MCP credential scoping
- Hallucination → caused by model limits, not architecture
- Rogue actions → needs guardrails and human-in-the-loop, not more agents

---

## The Opportunity

Nobody has combined these three things:
1. **Orchestration** — multi-agent coordination (CrewAI does this, but for enterprise)
2. **Scoped memory** — focused context per agent (Mem0/Zep do storage, not orchestration)
3. **Reliability as core design goal** — not an afterthought

The market has:
- Memory frameworks (Mem0, Zep, Letta) — storage layer only, no orchestration
- Agent frameworks (CrewAI, LangGraph) — orchestration, no reliability focus
- Personal assistants (OpenClaw, Hermes) — single agent, breaks at scale

Gap: **Reliable personal AI assistant via multi-agent orchestration with scoped memory.**

---

## Key Architecture Decisions (In Progress)

### 1. Non-AI Supervisor (Deterministic Routing)

**Decision:** The supervisor/router should NOT be an AI model.

**Reasoning:**
- Deterministic = same input always routes the same way, no hallucination in routing
- Fast = vector search is milliseconds, not seconds waiting for LLM
- Cheap = no tokens burned on routing decisions
- Testable = unit-testable deterministic logic
- CrewAI validated this approach: their "Flows" (deterministic) + "Crews" (AI execution)
  pattern is described as "the winning pattern"

**Current thinking — two-path supervisor:**
- **Fast path (vector only):** Short, clear inputs → embed → vector similarity match
  against skill index + memory index → route. No LLM involved. Handles ~80% of requests.
- **Slow path (LLM-assisted parsing):** Long or ambiguous inputs → fast cheap model
  (Haiku) extracts intents and entities → vector search matches each intent to
  skills + memory → deterministic routing. The LLM reads/parses, the code routes.

**Open question:** Can vector similarity reliably classify intent from casual
natural language? "Handle my morning" is vague. But if memory contains
"morning workout at 7am" and "standup at 9am," those items would match via
vector search without needing LLM interpretation.

### 2. Multiple Focused Agents (Not One Big Agent)

**Decision:** Multiple agents with small, scoped context per task.

**Reasoning:**
- Each agent gets only the memory and context relevant to its piece of the task
- No single agent is overwhelmed with cross-domain information
- Context per agent stays small → reliable output
- Aligns with credential isolation (payroll agent doesn't see calendar API keys)

**How it works:**
- Supervisor identifies which domains/skills a task touches
- Pulls relevant memory items for each domain (not full memory, just relevant bits)
- Each agent gets a small, curated context slice
- Agents execute in parallel when independent

### 3. Memory Architecture

**Decision:** Memory should NOT be flat files (memory.md). Should be structured
and retrievable.

**Options being considered:**
- Vector store (embeddings) — simple, good for similarity search
- Knowledge graph (entities + relationships) — better for cross-domain links
  (e.g., "user injured knee" links to fitness AND calendar constraints)
- Mem0 or similar existing framework — don't reinvent the storage layer

**Key principles:**
- Memory is organized by domain (personal, work, fitness, calendar, etc.)
- Each domain's memory is capped (small = reliable)
- Memory hygiene: stale entries pruned, conflicts resolved, duplicates merged
- Memory items are individually retrievable (not "load the whole file")

**Open question:** Fixed domain segments vs. dynamic clustering? Should domains
be predefined or should the system discover natural groupings as memory grows?

### 4. Cross-Domain Coordination

**The hard problem:** User says "meeting at 3pm, pickup at 3:30, gym after — figure it out."
This touches work + personal + fitness. No single agent has the full picture.

**Current thinking:**
- Supervisor detects it's cross-domain (vector search returns multiple domain matches)
- Pulls relevant items from each domain (not all memory, just scheduling-related)
- Routes to a purpose-built coordination agent with the assembled mini-context
- That context is still small because it's filtered per-domain
- Coordination agent resolves conflicts, produces unified plan
- Individual domain agents update their memory with the result

**Open question:** Does the coordination agent need its own persistent memory, or
is it purely stateless (just takes inputs, reasons, outputs)?

### 5. The Combiner (Seamless UX)

**Decision:** The user must never see the multi-agent structure. One message in,
one message out.

**Requirements:**
- No "Agent A says... Agent B says..." in responses
- Single, natural reply as if one person handled everything
- Graceful partial response if one sub-agent fails
- Response time should feel like talking to one agent

**How it works:**
- Takes outputs from all agents that worked on a task
- Detects conflicts between outputs
- Synthesizes into a single natural language response
- Doesn't need persistent memory — just synthesis skill
- Uses a capable model (Opus) but with minimal context (just agent outputs)

### 6. Authentication

**Decided and implemented:**
- Removed LiteLLM, using native SDKs (Anthropic, OpenAI, Google Gemini)
- Anthropic supports both API key and OAuth token (CLAUDE_CODE_OAUTH_TOKEN
  from `claude setup-token` for subscription users)
- OpenAI and Google: API key based

### 7. Deployment Model

**Decided:**
- Self-hosted on personal hardware (Mac Mini, VPS, laptop)
- Docker Compose for infrastructure (Redis, PostgreSQL)
- Cloud/Kubernetes only if we pursue hosted SaaS (Phase 4, optional)
- Same model as OpenClaw — everyone runs their own instance

---

## Open Questions (Need Further Discussion)

1. **Memory storage technology:** Mem0 vs. custom vector store vs. knowledge graph?
   Should we use an existing framework or build a thin layer?

2. **Domain segmentation:** Predefined domains (personal, work, fitness, calendar)
   or auto-discovered via clustering? What happens when a new domain emerges?

3. **Memory cap strategy:** Hard cap (max N items per domain) or soft cap
   (relevance-based pruning)? What's the right N?

4. **Combiner design:** Simple template-based merging or LLM-powered synthesis?
   When is an LLM needed for combining vs. when is concatenation enough?

5. **Latency budget:** If fast path is <100ms and slow path is ~1s (Haiku parse),
   what's the acceptable end-to-end time including agent execution?

6. **Memory conflict resolution:** When two domains have contradictory info,
   who resolves it? The supervisor? A dedicated hygiene agent? The user?

7. **Learning from corrections:** When the user corrects an agent ("no, I said
   Tuesday not Thursday"), how does that correction propagate to the right
   memory domain without touching others?

8. **Skill discovery:** How does the system handle a completely new type of
   request it's never seen? Fall back to general agent? Ask the user?

---

## Research References

- Context rot and lost-in-the-middle: MMC Ventures "Agentic Enablers" report
- Hallucination rates: Duke University "Why LLMs Still Hallucinate in 2026"
- OpenClaw security: Cisco blog, Kaspersky report (512 vulnerabilities)
- Memory frameworks comparison: Letta forum, DEV.to "4 Architectures"
- CrewAI Flows + Crews pattern: CrewAI blog "Missing Architecture for Production AI"
- Mem0 research paper: arxiv.org/pdf/2504.19413

---

## Next Steps

- Continue brainstorming on open questions above
- Research Mem0 integration feasibility
- Prototype the vector-based routing (can it handle real user inputs?)
- Revisit design.md and requirements.md once architecture is agreed
