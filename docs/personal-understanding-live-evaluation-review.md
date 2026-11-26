# Dynamic Personal Understanding V1 — Live Evaluation Review

## Scope

This review covers PR #7, `feat/dynamic-personal-understanding-v1`. All live scenarios use fictional data and isolated in-memory SQLite databases. No real user conversation data is included.

## Live runs

| Run | Commit | Scenario | Model calls | Result | Important qualification |
|---|---|---:|---:|---|---|
| [Initial live run](https://github.com/klwjlalala/becoming/actions/runs/45811203777) | `dda64f7` | 30 turns | 39 / 80 | Completed; no model/update errors | Fixture dates were not injected into transcript timestamps. Valid as an ordered multi-turn smoke test, not a time-gap evaluation. |
| [Date-aware live run](https://github.com/klwjlalala/becoming/actions/runs/45813188214) | `0deea31` | 30 turns | 39 / 60 | Completed; no model/update errors | Fixture dates were persisted as each turn's `created_at`, so the update engine received the 2024–2026 timeline. |
| [Final retrieval recheck](https://github.com/klwjlalala/becoming/actions/runs/45815014202) | `130e302` | 30 turns | 39 / 50 | Completed; no model/update errors | Re-ran after relevance-gated support ranking and event-level experience retrieval changes. |

The date-aware runs validated 30 turns, 28 source-bound evidence labels, and 11 human-review criteria. All live runs use fictional data and the reports intentionally have no automatic quality verdict.

## Human review of the date-aware run

### Behaviors observed

- Refined a broad “不喜欢社交” self-description into a context-dependent understanding, retaining old evidence as qualifying context and adding later evidence across dates.
- Preserved the tension between preference for autonomous time and the need for stable income / family cash flow.
- Updated the product/entrepreneurship understanding after the user's explicit correction; the current understanding distinguishes creative interests from entrepreneurship as a means.
- Retained the current one-year intention to learn AI deeply before rushing to launch a product.
- Stored the mountain-top / city-observation moment as a low-support, event-scoped experience rather than inferring a stable personality trait.
- Explicit listening requests, a third-party-only story, and a transient mood message suppressed personal-context retrieval.
- The final synthesis was cautious, separated stated preferences from interpretation, and described changes over time.
- In the final retrieval recheck, the Python question selected zero personal claims; explicit listen-only, third-party-only, and transient-mood turns also selected zero claims.
- The final life-direction query retrieved the event-level mountain experience after the ranking correction. The model still chose not to mention it in its final synthesis, avoiding an unsupported inference from a single emotional event.

### Issues found and addressed after the live run

1. **Meaningful experience retrieval.** The first date-aware run stored the mountain experience but did not retrieve it for the final “what kind of life do I want?” synthesis. Ranking now gives event-level experience evidence an additional relevance boost for life-meaning / desired-life queries. The final live recheck confirmed the event was retrieved; the model chose not to cite it in the final answer, which avoided over-interpreting a single experience. A deterministic regression test verifies ranking priority.
2. **Unrelated high-support retrieval.** The date-aware run showed a Python question retrieving two unrelated high-support claims. The cause was an unconditional support-level score bonus. The bonus now applies only after lexical relevance has been established. The final live recheck confirmed the Python question selected zero personal claims, and a deterministic regression test covers the case.
3. **Evidence lineage during refinement.** Existing versions could lose evidence that remained relevant after a refinement. The update protocol now allows the model to select prior evidence IDs from the target claim's current version; the program validates ownership before reattaching them.
4. **Retrieval suppression.** Explicit listen-only turns, clearly third-party-only venting, and common transient-mood messages now avoid unnecessary personal-context injection.
5. **Evaluation time fidelity.** The longitudinal harness now writes each fixture date into the transcript row before the understanding engine processes it.

## Current deterministic verification

- **168 offline tests pass** on the current branch head.
- The suite includes evidence-lineage validation, forged prior-evidence rejection, retrieval suppression, irrelevant high-support retrieval, meaningful-experience ranking, simulated timestamp persistence, and a combined service-loop test with long memory + dynamic personal understanding + growth tools enabled together.
- The unified CLI startup path with all optional modules enabled is also covered.
- Latest passing workflow: [Functional tests](https://github.com/klwjlalala/becoming/actions/runs/45832330603).

The final retrieval-ranking correction was followed by a third date-aware real-model run. The live recheck confirmed that the Python query no longer injects unrelated claims and that the event-level experience is available to the final life-direction query. The model did not mention that experience in its answer; this is recorded as a cautious omission rather than a failed retrieval.

## Full-stack integration audit

- PR #1–#7 form a linear dependency chain: each PR targets the immediately preceding feature branch; all seven currently report mergeable, and the latest head is not behind `main`.
- The latest branch contains 88 commits ahead of `main` and passes the full deterministic suite.
- No GitHub review submissions or inline review threads are currently recorded for these PRs; mergeability and CI success are not substitutes for human review.
- The deterministic service-loop integration test now runs long memory, personal understanding, and growth tools together through the same `GrowthAgent` and transcript store. A separate CLI test verifies that all optional modules can be enabled together from the unified entry point.
- These checks establish wiring and data-flow compatibility. They do not prove the combined behavior is semantically reliable under real-model use.

## Remaining limitations

- Important-change detection still uses a bounded keyword trigger, not a semantic classifier.
- Normal evidence batches run synchronously; a GUI/service deployment needs a background worker.
- Retrieval is still lexical + rule-based. There is no vector retrieval or semantic reranker.
- Listen-only / third-party / transient-mood suppression is a conservative phrase-based guard, not a general intent classifier.
- Sensitive-content detection is a limited rule set, not a complete privacy guarantee.
- SQLite is not encrypted. This branch is a research prototype, not production-ready storage or a complete privacy/security implementation.
- The live reports require human semantic review; successful workflow completion is not a quality pass.

## Acceptance status

PR #7 remains **Draft**. Three live runs and 166 offline tests provide useful evidence of functionality, but do not prove long-term relationship quality. Before merge, combine the full PR dependency chain, run the full regression suite, and conduct broader human review with additional scenarios and real usage over time.
