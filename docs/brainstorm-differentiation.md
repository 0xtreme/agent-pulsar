# Brainstorm: What Makes Agent Pulsar Worth Building?

**Date:** 2026-03-19
**Status:** Raw thinking — creative exploration, not decisions

---

## What the Research Says Nobody Has Solved

### The Compound Error Problem (Lusser's Law)
This is THE fundamental unsolved problem. If an agent achieves 85% accuracy per
action, a 10-step workflow succeeds only 20% of the time (0.85^10). Even at 99%
per step, a 20-step process is only 82% reliable. 73% of enterprise AI agent
deployments experience reliability failures in year one.

Nobody is designing architectures around this constraint. They're trying to make
each step smarter. The distributed systems answer is different: make each step
independently verifiable and retriable.

### Agent Overconfidence
GPT-5.2-Codex agents predict 73% success when actual is 35%. LLMs don't have
internally coherent confidence. They don't know what they don't know. Current
multi-agent frameworks (CrewAI, LangGraph) don't address this at all — they
trust agent outputs blindly and pass them downstream.

### The Duration Wall
METR's research: near-100% success on tasks taking <4 minutes, <10% on tasks
>4 hours. Current AI can sprint but can't run marathons. Nobody has cracked
reliable long-running autonomous operation.

### Multi-Agent Failure Rates Are Terrible
MAST paper (ICLR/NeurIPS 2025): analyzed 1,642 multi-agent traces across 7
frameworks. Failure rates: 41% to 86.7%. Key finding: "Most failures stem
from poor system design, not model performance."

Gartner: 40%+ of agentic AI projects will be cancelled by end of 2027.

### What Breaks in Existing Frameworks

**CrewAI:**
- One agent fails → entire crew stops. Retry is manual.
- Delegation doesn't actually work (delegating agent never reviews output)
- Debugging is painful — logging described as "a huge pain"
- Requires large proprietary models; small models break it
- Telemetry controversy (collecting prompts without consent)

**LangGraph:**
- Not truly adaptive — only branches in ways the static graph allows
- Hallucination reinforcement: agents in loops repeatedly process own outputs
- Overengineered — senior engineers say "just use Python"
- Version compatibility hell

### Why Personal AI Assistants Haven't Worked

The gap isn't capability — frontier models are smart enough. The problems are:
1. Integration: getting connected to your actual data and tools
2. Compound errors: multi-step tasks fail at exponential rates
3. Security: prompt injection is fundamentally unsolved
4. No graceful degradation: when AI fails, it fails catastrophically
5. Hybrid human-AI is the only pattern that works in production

---

## What's Uniquely Different About Our Angle

### The Core Insight: This Is a Distributed Systems Problem

CrewAI is workflow automation. LangGraph is graph execution. Neither treats
agent orchestration as what it actually is: a distributed systems reliability
problem.

Pavi's background is distributed systems. The patterns from that world are
directly applicable but nobody in the AI agent space is applying them:

- **Circuit breakers** — if an agent fails N times, stop sending it work,
  fall back to a simpler agent or human
- **Idempotent operations** — every agent action can be safely retried
- **Dead letter queues** — failed tasks don't disappear, they're captured
  for retry or human review
- **Saga pattern** — multi-step workflows with compensating actions on failure
- **Backpressure** — don't overwhelm agents, queue and rate-limit
- **Eventual consistency** — agents can work in parallel, results merge later
- **Health checks** — continuous monitoring of agent reliability per task type

Agent Pulsar already has some of this (DLQ, retry, event bus). The insight is
to make this THE differentiator, not just plumbing.

---

## Creative Ideas (Not Copying Anyone)

### Idea 1: Confidence-Gated Execution

Every agent must declare confidence before its output is accepted.

How it works:
- Agent produces result + confidence score (verbalized, not token probability —
  research shows this is 50% better calibrated)
- If confidence > high threshold → auto-accept, pass to next step
- If confidence is medium → lightweight verification (second model spot-check)
- If confidence < low threshold → don't execute, ask the user

Why this matters: It directly attacks the compound error problem. Instead of
blindly chaining 10 steps (20% overall success), you catch uncertain steps
early. A 10-step chain where 3 steps pause for verification is slower but
actually completes successfully.

Nobody does this. CrewAI and LangGraph trust all agent outputs equally.

### Idea 2: Reliability Scoring Per Task Type

Track actual success rates per task type over time.

How it works:
- Every task result is scored (user feedback, output validation, consistency)
- Build a reliability profile: "email.draft: 94% reliable, payroll.run: 67%"
- Use this to dynamically adjust behavior:
  - High reliability → more autonomy, less oversight
  - Low reliability → require user confirmation, use better model
  - Very low → circuit breaker: stop attempting, tell user "I can't reliably
    do this yet"

Why this matters: The system gets MORE reliable over time, not less. It learns
its own limits. OpenClaw gets worse as memory grows; Agent Pulsar gets better
as it accumulates reliability data.

### Idea 3: Graduated Autonomy (Trust Ladder)

New task types start with zero trust. Autonomy is earned, not assumed.

Levels:
1. **Suggest** — agent proposes, user approves every action
2. **Draft** — agent executes but holds output for review before delivery
3. **Act** — agent executes and delivers, user notified after
4. **Silent** — agent handles it, user only sees summary

Promotion rules: after N successful executions at level K with >X% reliability,
automatically promote to level K+1. Demotion: any failure drops back one level.

Why this matters: OpenClaw's failure mode is "give it all access, hope for the
best." Agent Pulsar's model is "prove you can handle it." This is how you
actually build user trust — not by promising reliability, but by demonstrating it
incrementally.

### Idea 4: Step-Level Verification (Not Just Output Verification)

Instead of verifying the final result, verify each intermediate step.

How it works:
- Every agent action has a pre-condition and post-condition
- Pre-condition: checked deterministically before execution (does the input
  make sense? are required params present?)
- Post-condition: checked after execution (does the output match expected
  schema? is it internally consistent? does it contradict known facts?)
- If post-condition fails → retry with different approach or escalate

This is literally contract programming / design-by-contract applied to AI agents.
It's a well-proven pattern in distributed systems but nobody applies it to LLM
agents.

### Idea 5: The Internal Critic Pattern

Each agent runs a lightweight self-consistency check before returning.

How it works:
- Agent generates 2-3 candidate responses (low cost with fast model)
- Check agreement between candidates
- High agreement → confident, return result
- Low agreement → the agent genuinely doesn't know. Flag as uncertain.

This is different from confidence scoring — it's behavioral, not self-reported.
The agent doesn't say "I'm 90% confident." It demonstrates consistency or
inconsistency through its own outputs.

Research backs this: self-consistency-based approaches outperform self-reported
confidence for detecting hallucination.

### Idea 6: Blast Radius Containment

Borrow from infrastructure: limit the blast radius of any single failure.

How it works:
- No single agent action can affect more than one domain
- Cross-domain operations require explicit multi-step approval
- Irreversible actions (sending email, making purchases) always require
  human confirmation regardless of trust level
- Agent errors are isolated — a failure in fitness context doesn't corrupt
  work context

Why this matters: OpenClaw's "agent bought a car" incident. The architecture
should make this impossible, not just unlikely.

### Idea 7: Adaptive Step Decomposition (Counter Lusser's Law)

Design task decomposition to minimize chain depth.

How it works:
- Prefer wide (parallel independent steps) over deep (sequential dependent steps)
- A 10-step sequential chain (20% success at 85%/step) can often be
  restructured as 3 parallel groups of 2-3 steps each
- Each parallel group: ~70% success. With retry: ~90%+
- Overall: much higher than the sequential 20%

The supervisor's job isn't just "decompose the task" — it's "decompose the
task in a way that minimizes compound failure probability."

---

## What Agent Pulsar's Unique Value Proposition Could Be

> "The first personal AI assistant built on distributed systems reliability
> principles — not just smarter agents, but an architecture that gets more
> reliable over time."

The moat isn't better LLM calls. It's:
1. **Confidence-gated execution** — agents that know when they don't know
2. **Graduated autonomy** — trust earned through demonstrated reliability
3. **Reliability scoring** — system learns its own limits per task type
4. **Blast radius containment** — failures can't cascade across domains
5. **Compound error mitigation** — architecture designed around Lusser's Law

None of this requires inventing new AI. It requires applying distributed systems
engineering to AI agent orchestration. That's the intersection nobody else is at.

---

## Honest Risks

- **Complexity**: All this verification and scoring adds latency and cost.
  Need to be smart about when to apply heavyweight checks vs. when fast
  path is fine.
- **Cold start**: Reliability scoring needs data. New users have no history.
  Need sensible defaults and fast learning.
- **User patience**: Graduated autonomy means the system is LESS capable on
  day 1 than OpenClaw. Users might not wait for it to get better.
- **Over-engineering**: Could end up with a beautiful architecture nobody uses
  because it's too complex to set up.
- **The 80/20 trap**: Maybe 80% of personal assistant use cases are simple
  enough that a single agent with good prompts works fine, and the reliability
  problems only matter for the complex 20%.

---

## Open Questions

1. Is the personal assistant market the right target, or should this be a
   framework/platform that others build on?
2. How much of this can be built incrementally on top of what we already have
   vs. requiring a ground-up rethink?
3. What's the MVP that demonstrates the reliability advantage without building
   everything?
4. Who are the early adopters — power users frustrated with OpenClaw, or
   developers building their own agents?

---

## Research Sources

- Compound Error / Lusser's Law: The AI Engineer, Prodigal Tech
- METR Duration Wall: metr.org (March 2025)
- MAST Multi-Agent Failures: arxiv.org/abs/2503.13657 (1,642 traces analyzed)
- Agent Overconfidence: arxiv.org/html/2602.06948
- VeriGuard Formal Verification: arxiv.org/html/2510.05156v1
- Confidence Calibration: ICLR 2025 proceedings
- CrewAI Issues: community.crewai.com, GitHub issues, HN discussions
- LangGraph Issues: Medium critiques, HN discussions
- Personal AI Gap: IBM Think, MIT Technology Review
- Gartner Prediction: 40%+ agentic AI projects cancelled by 2027
