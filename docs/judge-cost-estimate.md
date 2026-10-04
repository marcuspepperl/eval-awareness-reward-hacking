# LLM judge cost estimate: both harnesses

*2026-10-04. Judge: GLM-5.3-Flash on DeepInfra (`deepinfra-raw/glm53flash`, reasoning effort high, temperature 0), $0.075 / $0.25 per M input / output tokens, no cached-token discount observed on the raw path. Replaces the earlier $5–6 guess in [judging.md](judging.md), which was made before any judge run.*

## Measured rates (judge v6 on the 10 dev attempts)
| Pass | Cost driver | Rate |
|---|---|---|
| A (EA + grader) | reasoning length | **$0.079 per M reasoning chars** (input 466k + output 43k tokens for 583k chars; includes per-chunk overhead: setup, task, `[ctx]`, instructions) |
| B2 (first bad test / first cheat considered) | reasoning length | **$0.072 per M reasoning chars** |
| B1 (cheat verdict) | one call per attempt / episode | **≈ $0.0004 per call** |

Retries for invalid outputs add ≈ 5%. Track B chunks also carry compressed tool context, counted as extra "reasoning chars" at the same rate.

## Volumes
| | Track A (minimal) | Track B (agentic) |
|---|---|---|
| Units | 412 rollouts = 1,926 attempts (phase 1, 103 problems × 2 splits × 2 epochs) | 412 episodes, assuming the same 103 × 2 × 2 (one-off measured; conflicting assumed similar length) |
| Judged chars per unit | 47.4k per attempt (measured, phase 1) | 185.5k per episode = 164.5k reasoning + 12.5k compressed tool calls + 8.5k compressed tool outputs (measured, run 37) |
| Total judged chars | 91.4M | 76.4M |
| B2 subset (cheats + a sample of honest units; no longer the default) | ≈ 700 attempts (≈ 33M chars) | ≈ 50% of episodes (≈ 38M chars) |

## Full-run judge cost
| Pass | Track A | Track B |
|---|---|---|
| A (EA + grader), all units | $7.2 | $6.0 |
| B1 (cheat verdict, + disclosure in Track B), all units | $0.8 | $0.2 |
| B2 timing, **all units** (default; subset in brackets) | $6.6 ($2.4) | $5.5 ($2.8) |
| 2 extra runs on the gold units (stability) | $0.4 (≈ 30 attempts) | $0.9 (≈ 15 episodes) |
| Retries (+5%) | $0.5 | $0.5 |
| **Total** (B2 on all units; subset in brackets) | **≈ $16** (≈ $11) | **≈ $13** (≈ $10) |

## Validation and iteration (before the full runs)
| Item | Track A | Track B |
|---|---|---|
| Calibration + proxy iteration (30 pilot attempts / 20 episodes, ≤ 3 rounds × 2 runs) | ≈ $1.5 | ≈ $3.5 |
| Smoke / adaptation runs | — | ≈ $0.5 |

## Total judge budget
| | Low | Expected | High |
|---|---|---|---|
| Track A | $12 | **$17** | $24 |
| Track B | $12 | **$17** | $28 |
| **Both** | **$24** | **≈ $34** | **$52** |

*Low* = B2 on a subset, one validation round. *Expected* = **B2 on all units** (the default since 2026-10-04: noticing the bad test is needed on honest units too), full validation (≤ 3 rounds). *High* = B2 on all units, one extra full re-run of pass A after a prompt fix, and Track B conflicting episodes 1.5× longer than one-off.

## Sensitivity
- Track B cost is driven by the long tail: p90 episode is 2.1× the mean (396k reasoning chars), max 6.9× (1.27M). A few very long episodes can move the total by ±$2.
- One Track B epoch instead of two halves the Track B full run (≈ $5–6).
- Dropping tool context from Track B chunks saves ≈ 11%.
- Effort `low` instead of `high` on the judge: output tokens were similar in the v3 test, so roughly the same cost; not recommended (precision dropped).
- A bigger judge (e.g. a frontier model) for escalation only, on failed or disputed units, adds little if under ~5% of units.

## For context: policy-model generation (not judge)
| | Spent | Still to run (estimate) |
|---|---|---|
| Track A phase 1 (412 rollouts) | $5.52 | — |
| Track B run 37 (103 one-off episodes) | $9.16 (135M input, 5.9M output tokens) | full 412 episodes ≈ $37 (≈ $28 more, if conflicting is similar) |
| Track A phase 2, attempt-level resample (≈ 400 histories × 6 conditions × 3 samples) | — | ≈ $20 (≈ $10 with half the conditions or samples) |
| Track B phase 2 (prefill design not decided) | — | likely ≈ $40–80: an episode costs ~7× a Track A rollout to generate ($0.089 vs $0.013) |

**Suggested DeepInfra top-up for judging alone: ≈ $40** (expected case with margin; the high case is ≈ $52). With the remaining generation runs: ≈ $110–170 total, depending on the Track B phase-2 design.
