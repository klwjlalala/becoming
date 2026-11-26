# Dynamic Personal Understanding V1 — Live Evaluation Review

## Scope

This review covers PR #7, `feat/dynamic-personal-understanding-v1`. All live scenarios use fictional data and isolated in-memory SQLite databases. No real user conversation data is included.

## Live runs

| Run | Commit | Scenario | Model calls | Result | Important qualification |
|---|---|---:|---:|---|---|
| [Initial live run](https://github.com/klwjlalala/becoming/actions/runs/45811203777) | `dda64f7` | 30 turns | 39 / 80 | Completed; no model/update errors | Fixture dates were not injected into transcript timestamps. Valid as an ordered multi-turn smoke test, not a time-gap evaluation. |
| [Date-aware live run](https://github.com/klwjlalala/becoming/actions/runs/45813188214) | `0deea31` | 30 turns | 39 / 60 | Completed; no model/update errors | Fixture dates were persisted as each turn's `created_at`, so the update engine received the 2024–2026 timeline. |

The date-aware run validated 30 turns, 28 source-bound evidence labels, and 11 human-review criteria. The report intentionally has no automatic quality verdict.

## Human review of the date-aware run

### Behaviors observed

- Refined a broad “不喜欢社交” self-description into a context-dependent understanding, retaining old evidence as qualifying context and adding later evidence across dates.
- Preserved the tension between preference for autonomous time and the need for stable income / family cash flow.
- Updated the product/entrepreneurship understanding after the user's explicit correction; the current understanding distinguishes creative interests from entrepreneurship as a means.
- Retained the current one-year intention to learn AI deeply before rushing to launch a product.
- Stored the mountain-top / city-observation moment as a low-support, event-scoped experience rather than inferring a stable personality trait.
- Explicit listening requests, a third-party-only story, and a transient mood message suppressed personal-context retrieval.
- The final synthesis was cautious, separated stated preferences from interpretation, and described changes over time.

### Issues found and addressed after the live run

1. **Meaningful experience retrieval.** The mountain experience was stored but was not selected for the final “what kind of life do I want?” synthesis. Ranking now gives event-level experience evidence an additional relevance boost for life-meaning / desired-life queries. A deterministic regression test verifies that this experience ranks ahead of generic values claims.
2. **Unrelated high-support retrieval.** The date-aware run showed a Python question retrieving two unrelated high-support claims. The cause was an unconditional support-level score bonus. The bonus now applies only after lexical relevance has been established. A regression test covers the Python query.
3. **Evidence lineage during refinement.** Existing versions could lose evidence that remained relevant after a refinement. The update protocol now allows the model to select prior evidence IDs from the target claim's current version; the program validates ownership before reattaching them.
4. **Retrieval suppression.** Explicit listen-only turns, clearly third-party-only venting, and common transient-mood messages now avoid unnecessary personal-context injection.
5. **Evaluation time fidelity.** The longitudinal harness now writes each fixture date into the transcript row before the understanding engine processes it.

## Current deterministic verification

- **166 offline tests pass** on the current branch head.
- The suite includes evidence-lineage validation, forged prior-evidence rejection, retrieval suppression, irrelevant high-support retrieval, meaningful-experience ranking, and simulated timestamp persistence.
- Latest passing workflow: [Functional tests](https://github.com/klwjlalala/becoming/actions/runs/45814505652).

The final retrieval-ranking correction was made after the date-aware live run. Its deterministic behavior is covered by tests, but a further real-model synthesis run has not yet been performed.

## Remaining limitations

- Important-change detection still uses a bounded keyword trigger, not a semantic classifier.
- Normal evidence batches run synchronously; a GUI/service deployment needs a background worker.
- Retrieval is still lexical + rule-based. There is no vector retrieval or semantic reranker.
- Listen-only / third-party / transient-mood suppression is a conservative phrase-based guard, not a general intent classifier.
- Sensitive-content detection is a limited rule set, not a complete privacy guarantee.
- SQLite is not encrypted. This branch is a research prototype, not production-ready storage or a complete privacy/security implementation.
- The live reports require human semantic review; successful workflow completion is not a quality pass.

## Acceptance status

PR #7 remains **Draft**. Do not merge or claim long-term relationship quality is proven until the remaining retrieval correction has been reviewed in a targeted live-model check and the full PR stack has been combined and regression-tested.
