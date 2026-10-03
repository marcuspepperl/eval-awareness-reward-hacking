# Judge validation plan

*Agreed 2026-10-03. Goal: be confident in the judge **before** spending gold-set effort, so the held-out gold result confirms rather than surprises.*

The risk: we label a gold set, agreement comes back at 60–70%, and fixing the rubric then means tuning on the answers. The defence is to find rubric and judge problems on cheap pilot data first, and to touch the gold set only once.

## Principles
- **One codebook.** A short human-readable rubric (definitions, edge cases, examples) that Mark, the reviewer subagents, and Claude all label from. Judge prompts are derived from it. Every disagreement that reveals an ambiguity is fixed **in the codebook first**, then propagated to the prompts.
- **Dev data = pilot** (`03-pilot`, 194 no-flag attempts; 10 used so far). **Phase-1 attempts are touched only for the gold set.**
- **General fixes only.** Prompt changes state a rule; examples only illustrate it. ≤ 3 iteration rounds, each run 2× (run-to-run variance at temperature 0 is about ±1 error per 10 attempts per label).
- **Mark's time goes to judgment calls, not to reading everything twice:** after the calibration step, Mark only adjudicates disagreements.

## Labels validated (what the analysis uses, at its granularity)
| Label | Reference marks | Metric |
|---|---|---|
| `ea` (+ framing) | all occurrences | attempt-level presence and framing; occurrence precision / recall (overlap match) |
| `grader` | precision check of judge spans | precision; EA↔grader confusion |
| `bad_test`, `cheat_considered` | first occurrence only: one sentence ID each | presence; distance in sentences |
| B1 summary | `attempted`, `type`, `transparent` | accuracy / κ |
| `cheat_impl` lines | not labelled (evidence only) | — |

## Steps
| # | Step | Who | Output |
|---|---|---|---|
| 1 | **Diff view** on review.html (judge vs reference, per label: agree / judge-only / reference-only, first-point distances; sidebar shows attempts with disagreements) + **codebook draft** from the current prompts | Claude | `review.html` diff mode, `docs/codebook.md` |
| 2 | **Labelling UI** as a mode of the same page: click / drag to mark spans, hotkeys per label, first-only labels take one click, B1 fields per attempt, saves `reference.json` in the same format the diff view reads | Claude | labelling page |
| 3 | **Calibration:** Mark labels **5 pilot rollouts** blind, timing each one | Mark | 5 labelled attempts; minutes per attempt |
| 4 | Reviewer subagents (recall) and Claude (precision) label the **same 5** blind; compare all three in the diff view; fix the codebook where readings differ | Claude + subagents, Mark adjudicates | codebook v1 |
| 5 | **Proxy reference:** subagents + Claude label **30 pilot attempts** (stratified: cheat / honest, both splits, early / late attempts, oversampled for likely EA via the keyword prior); Mark adjudicates **only disagreements** | Claude + subagents, Mark | `reference.json` for 30 |
| 6 | **Judge iteration:** iterate on 20 of the 30, check on the other 10, against the go / no-go bars below; ≤ 3 rounds, 2× runs each | Claude | frozen prompts |
| 7 | **Gold set:** Mark labels **~30 phase-1 attempts** blind (stratified as in step 5, incl. attempts 6–8, which the pilot lacks; EA oversampled via the keyword prior, never via judge output). Nearly all held out: the pilot proxy plays the dev role | Mark | gold labels |
| 8 | **Full run** on phase 1 (412 samples, 1,926 attempts; B2 on B1-attempted + a sample of honest attempts) + **2 extra runs on the gold attempts** for stability. Gold metrics come from the same full run (no double spend). Report precision / recall / stability with CIs, reweighted to the population | Claude | judgments + validation report |

## Go / no-go bars (step 6, before the gold set)
| Measure | Bar |
|---|---|
| EA, attempt-level presence | ≥ 90% agreement |
| EA, occurrences | precision ≥ 85%, recall ≥ 80% |
| First `bad_test` / first `cheat_considered` | within ±5 sentences in ≥ 85% of attempts |
| B1 `attempted` / `type` | ≥ 95% |
| Run-to-run self-agreement | comparable to the above (otherwise noise sets the ceiling) |

If a label can't reach its bar: **coarsen the analysis, not the rubric** (e.g. attempt-level EA presence instead of occurrence counts; "bad test before / after cheat considered" instead of exact positions), and use measured precision / recall to correct prevalence estimates.

## Recall reviewers (lessons from the first check)
The first recall check (10 attempts) under-performed because of its setup:
- one reviewer per attempt (10 files split across 3 agents), so no overlap;
- 3–4 full transcripts (~55–70k tokens) in one agent context: the needle problem chunking was meant to avoid;
- the v3 rubric (an evaluator checking for hard-coding counted as EA).

Next time:
- **one transcript per reviewer**, read in sequential pieces with annotations logged as it goes;
- **2 reviewers per transcript (Sonnet + Opus)**; union = candidate recall set, Claude verifies;
- reviewers label from the **codebook**, blind to judge output.

## Mark's time (estimate; refine after step 3)
- Steps 3 + 4: 5 full rollouts (~750–1,000 sentences each) + adjudication.
- Step 5: disagreements only (a few per attempt).
- Step 7: ~30 full rollouts. At ~25 min each ≈ 12 h; the UI is built to cut this (hotkeys; first-only labels need one click; keyword jump list for **navigation after** a full read, so recall is not biased toward keywords).
- Gold size is set after timing step 3; EA rarity (~0.6 occurrences per attempt in dev) is why it is oversampled.

## Cost
Judge runs on pilot data: cents per round. Step 8 full run ≈ $5–6 (**needs a DeepInfra top-up**) + 2 gold re-runs < $0.50. Subagents run on the Claude plan, not DeepInfra.
