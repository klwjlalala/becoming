# Node local agent acceptance checkpoint — 2026-11-27

Validated runtime commit: `bfa3043eb22ba2a3b6fd292c02bbc4ed272191c0`.
- [Real-model acceptance run 45951614031](https://github.com/klwjlalala/becoming/actions/runs/45951614031): success.
- [Node, gateway, fake-provider HTTP regression 45951614035](https://github.com/klwjlalala/becoming/actions/runs/45951614035): success.
- [Original Python regression 45951614028](https://github.com/klwjlalala/becoming/actions/runs/45951614028): success.
- [Raw synthetic report archive 15177601192](https://github.com/klwjlalala/becoming/actions/runs/45951614031/artifacts/15177601192) (expires 2026-12-11).
- Same repository-configured model, 124 calls: 24 functional, 39 scenarios, 61 longitudinal. All three functional groups passed, including all seven growth tools. Nine scenario cases and all 30 longitudinal turns completed; 11 active claims and seven claims retrieved for the final synthesis.

## Human review of actual output and persisted state

### Nine scenario cases
- intent-001: responded to sharing without unsolicited advice.
- intent-002: asked a targeted question about the reason for changing jobs, no premature recommendation to quit.
- intent-003: preserved stable income and autonomy constraints, suggested low-risk incremental experiments.
- memory-001: retrieved actual memory ID 1 with zero recent-history window, suggested hiking conditionally.
- memory-002: final memory set empty; weather response requested location, no fabricated forecast.
- memory-003: swimming revision active, running revision inactive; recalled ID 2 and answered correctly.
- memory-004: recalled actual IDs 2, 1, 3 (hiking, peaceful forest, dislike of crowded venues) and offered relevant conditional suggestions.
- memory-005: occupational memory persisted, but final unrelated refrigerator query recalled no memory and received a normal technical answer.
- memory-006: swimming preference remained active; a single running outing did not replace it.
These are favorable single-run observations, not a statistical reliability claim.

### Longitudinal review
- No new claims at turns 6 (third-party), 9 (hypothetical), 17 (transient mood), 18 (tentative project reconsideration), 24 (listen-only), 25 (request for advice), 27 (technical question), 30 (synthesis).
- Social preference refined by context. Stable cash flow and autonomy coexist. Entrepreneurship superseded as a means rather than end; the associated claim has seven versions (CREATE, five REFINE, SUPERSEDE). Freedom redefined with chosen constraints. Current AI learning plan and conditional future product work both persisted.
- Turn 24: appropriate listening, zero retrieved claims. Turn 27: appropriate technical reply, zero retrieved claims.
- Final synthesis reflects autonomy, meaningful creation, relationships, financial constraints and changed understanding of freedom. Acknowledges uncertainty. The zero-history/no-understanding baseline cannot synthesize earlier facts.
- Remaining quality gaps: turn 3's meaningful mountaintop experience was not retained in claims and was absent from the synthesis. Turn 23's tentative self-interpretation about control of life was explored naturally but not retained in an active claim. Turn 25 explicitly requests a directional recommendation; response only requests more details despite relevant information. Turn 28's current AI learning goal was stored but not selected among the seven final retrieved claims, so the final response omits it. Three partly overlapping social claims show some redundancy.
- These are product-quality gaps, not failures of persistence, tool execution or safety guarantees. The workflow success is NOT a claim of perfect semantic quality. Only one full live run, a fictional case and a no-history baseline; no claim of real-user longitudinal benefit or universal model compatibility.

## Decision
Accept the current Node/Python local-first agent as a functional development baseline. Stop open-ended protocol polishing. Retain branch separation, no automatic merge to main, no extra live calls for this documentation update. Discuss the next product development phase and use the above gaps as bounded future evaluation targets rather than treating every missed qualitative detail as a migration blocker. Original Python SQLite data migration and full production readiness remain outside this acceptance.
