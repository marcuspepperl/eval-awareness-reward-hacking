# Reporting: analyses, uncertainty, and judge validity

*Status: design, for review.* Companion to [judging.md](judging.md).

## 1. What is measured, and by what
| Quantity | Source | Judge error matters? |
|---|---|---|
| Cheat outcome per sample / per attempt (impossible tests passed) | scorer (test execution) | **No**: exact |
| Attempt numbers, reasoning length, tokens, cost | logs | No |
| Eval awareness (presence, framing, strength, location, amount) | judge | **Yes** |
| Contradiction recognized; cheat intent (`attempted`), cheat type, decision location | judge | Yes (secondary analyses) |

**Headline cheat rates carry no judge error.** Judge error enters only analyses that condition on judge labels.

## 2. Analyses (phase 1, observational)

### 2a. Headline: per-task EA vs no-EA (sample level)
- A sample is **EA** if any attempt has an `eval_awareness` tag.
- **Qualifying tasks** have ≥ 1 EA and ≥ 1 non-EA sample.
- For each qualifying task, compute cheat rate(EA) − cheat rate(non-EA). Average across tasks with equal weight.
- Statement: *"On the N tasks where both occurred, EA samples cheated M% vs non-EA N%; difference D (95% CI)."*
- Repeat by framing (capability-EA vs non-EA, safety-EA vs non-EA). These subsets are small, so treat them as indicative.
- Caveat: counts EA that occurs *after* the cheat (possible rationalization). 2b addresses this.

### 2b. Attempt level (timing-correct)
- Among attempts where the sample **has not yet cheated**, compare P(this attempt cheats) for attempts **with** vs **without** EA in their reasoning.
- Compare **within task and attempt number**, via stratification or a small logistic regression with task and attempt-index effects.
- Why attempt number matters: later attempts follow more failures, which may raise both EA and cheating.
- Because prior reasoning is dropped in Track A, EA in attempt *k* is exactly what the model saw before submitting attempt *k*.

### 2c. Amount of EA (dose-response, observational)
- Relate EA **density** (EA sentences per 100 sentences / per 1k tokens), EA sentence count, strength, and persistence (fraction of attempts with EA) to cheating, within task.
- Prefer density over raw counts: longer reasoning and later attempts inflate counts.
- Phase 2 can test dose causally (inject 1 vs 3 EA sentences, or speculative vs confident).

### 2d. Descriptive timing and behaviour
- EA rate by attempt number (does EA rise after failure feedback?).
- First-EA attempt vs first-cheat attempt: before / same / after; means and distributions.
- Within-attempt order: EA → contradiction → cheat decision (relative positions).
- Contradiction recognized: rate overall, and among honest failures (the "silent integrity" pattern).
- Cheat types, transparency rate, and `attempted` vs `passed` (failed cheat attempts).
- Benchmark-naming rate (recall vs inference of EA).

## 3. Phase 2 (causal): prefill conditions
- Per task: cheat rate under each condition (neutral control, generic, capability, safety) → paired differences **vs neutral control**, averaged across tasks.
- Report for all tasks, and (as analysis, not design) for mid-propensity tasks from phase 1.
- Manipulation checks:
  - does the model continue or regenerate the injected thought;
  - does EA appear downstream (judge).

## 4. Uncertainty
- **Confidence intervals = sampling uncertainty only**: cluster bootstrap over **tasks** (resample tasks, keep all their samples), 10k resamples, percentile 95% CIs. Where useful, also report per-sample Wilson intervals, clearly labelled.
- **Judge error is not folded into CIs.** It is reported separately (§5) with the direction of bias:
  - EA labels that are noisy **and** unrelated to cheating push EA–cheat differences **toward zero**, so observed effects are conservative under that assumption.
  - Stated explicitly as an assumption.
- **Sensitivity analyses:**
  - re-run key comparisons using only `strength = confident` EA;
  - relabel a subset with a second judge model and check the conclusions hold.
- Optional (probably overkill): propagate judge error via misclassification correction plus a bootstrap over the gold set.

## 5. Judge validation (gold set)
- **Gold set:** ~40 attempts, **stratified** across cheat / non-cheat, both splits, early / late attempts, and likely / unlikely EA (keyword prior).
- **Labelled by a human (Mark), blind to judge output**, using the same numbered transcripts. A small labelling UI will be provided.
- Claude is not the gold labeller: it is also an LLM, so its labels would not be an independent reference.
- **Metrics:**

| Label | Metric |
|---|---|
| EA present (per attempt) | precision, recall, Cohen's κ |
| EA framing | confusion matrix, κ |
| Contradiction recognized | precision, recall, κ |
| Cheat `attempted` | precision, recall, κ |
| Cheat type | confusion matrix |
| Locations | tag-level agreement: exact ID match and ±1-sentence match; span overlap (≥ 50% of the shorter span) |

- **Error taxonomy:**

| Type | Example | Detected by |
|---|---|---|
| Structural | bad JSON, nonexistent ID | automatic validation → retry |
| Classification | missed EA; spurious EA; wrong framing; honest edge-case code labelled a cheat | gold-set metrics |
| Localization | right instance, wrong or neighbouring ID | gold-set location agreement |

- **Escalations and failures:** report the counts (retries, escalations to a stronger judge, manual labels, exclusions) and which judge produced each label. Include some escalated cases in the gold set if they are a non-trivial share.

## 6. Write-up template (methods paragraph)
> Cheat outcomes are determined by executing the (impossible) tests. Eval-awareness and cheat-intent labels come from an LLM judge (*model X*) that tags sentence IDs in segmented transcripts. It was validated against *n* = 40 human-labelled attempts: EA presence κ = …, P/R = …/…; framing κ = …; tag location agreement …% (±1 sentence). Judge failures: … (escalated to *model Y*; *k* labelled manually). Intervals are 95% cluster-bootstrap CIs over tasks. Label noise independent of cheating biases EA–cheat differences toward zero.
