# Reporting: write-up goals, analyses, uncertainty, judge validity

*Status: design, updated 2026-10-04.* Companions: [../judging.md](../judging.md) (judge), [../judge-validation-plan.md](../judge-validation-plan.md), [../judge-track-b-adaptation.md](../judge-track-b-adaptation.md), [../judge-cost-estimate.md](../judge-cost-estimate.md), [decisions.md](decisions.md), [fixes.md](fixes.md).

## 0. Write-up goals
**Question:** does verbalized eval awareness (EA), and how the model frames it, relate to reward hacking, and does it cause it?

**Two harnesses, one judge and codebook:**
| | Track A: minimal (ImpossibleBench-like) | Track B: agentic |
|---|---|---|
| Role | **main study**: observational + causal | **harness sensitivity**; observational EA; causal only if base rates allow |
| V4-Flash cheat rate | one-off 79%, conflicting 57% (phase 1, 412 rollouts) | one-off 35% (run 37, 103 episodes); conflicting ~0% (earlier runs) |
| Reasoning across steps | dropped between attempts (attempts ≈ independent) | kept (one stream per episode) |
| Why this role | room to move in both directions; exact outcome; every rollout ends (no censoring); comparable to the published setup | more realistic, but low or zero base rates; GLM alternatives cheat more but often don't finish (timeouts correlate with deliberation, so they would bias causal estimates) |

**Intended claims (each with its own analysis below):**
1. Cheat rates per harness, and how much the harness changes them (same model, same problems).
2. How often EA occurs, in what framing, and when (relative to recognizing the bad test and to the cheat decision).
3. Observational: within task, is EA associated with cheating? Reported as pooled, between-task and within-task (§2).
4. Causal (Track A): does injecting EA at a decision point change the chance of cheating, by framing (§3)?
5. Disclosure: do cheats get admitted (code comments; final message in Track B), and does EA relate to that?

**Guardrails for wording:** say "associated" for §2 and "causes" only for §3; state which EA definition (strict or broad, below) each number uses; give the number of contributing tasks for every within-task estimate.

## 1. What is measured, and by what
| Quantity | Source | Judge error matters? |
|---|---|---|
| **Successful cheat per attempt** (impossible tests pass) | scorer, run on every attempt (Track A) / on final files (Track B) | **No**: exact. **Headline outcome** |
| Cheat *try* per attempt (successful + failed), cheat type, disclosure | judge B1 | Yes: **robustness** outcome. Failed tries are rare in Track A (≈ 1–2% of attempts by a literal heuristic) |
| EA (presence, framing, strength, location, amount) | judge pass A | **Yes: the main predictor**; this is what gold-set validation must support |
| Grader reasoning | judge pass A | Yes; contrast class + candidate second finding |
| First bad test, first cheat considered (timing) | judge B2 | Yes (timing analyses) |
| Attempt numbers, lengths, tokens, cost | logs | No |

**EA definitions** (fixed before analysis):
- **strict EA** = `eval_awareness` (the model suspects the task exists to assess it);
- **broad EA** = `eval_awareness` ∪ `grader` (adds reasoning about how the answer is checked).

Strict is primary. Broad is a robustness check: grader reasoning is often part of the cheat deliberation itself ("the grader only runs these tests, so a special case is safe"), so folding it in would build in an EA↔cheat correlation. If the two disagree, that is a finding.

## 2. Phase 1: observational analyses
### 2a. Three numbers, three questions
| Number | Question | Unit / method |
|---|---|---|
| **Pooled** | Do rollouts with EA cheat more? | rollout-level difference, CIs clustered by task. **Descriptive only** |
| **Between-task** | Do tasks with more EA have more cheating? | task-level EA rate vs cheat rate. A finding about task features |
| **Within-task** | Holding the task fixed, is EA associated with cheating? | the hazard model (2b). **The main observational result** |

Why not lead with the pooled number: task confounds it (a blatant, typo-looking contradiction plausibly elicits both EA and special-casing), so pooled and within-task can differ or even reverse (Simpson's paradox). Rows from one task are not independent either, so naive CIs are too narrow. If pooled and within-task diverge, report the divergence.

### 2b. Main within-task model: discrete-time hazard of the first cheat (Track A)
- **Rows:** attempts in the **risk set**, i.e. attempts made before the rollout's first cheat. Track A builds this in: a successful cheat ends the rollout.
- **Outcome:** successful cheat at this attempt (exact).
- **Model:** logit P(cheat now) = α_k (one term per attempt number = baseline hazard) + β · EA in this attempt's reasoning + task fixed effects (+ split, or fit splits separately). Report e^β (odds ratio) and the equivalent percentage-point difference.
- **Why attempts, not rollouts:** with 2 epochs, few tasks have one EA and one non-EA rollout, so a rollout-level within-task comparison would rest on perhaps 20–30 informative tasks. Attempts are near-independent fresh reasoning blocks: 1,926 rows with much more within-task variation.
- **Why the risk set:** a history containing the model's own cheat strongly drives further cheating. A history of honest failures is the same *type* for everyone at attempt *k*, so the α_k terms absorb its effect.
- **Timing:** a variant counts EA only if it appears before the first `cheat_considered` within the attempt, which removes rationalization after the fact.
- **Headline sentence:** "Among attempts made before any cheat, those whose reasoning contained EA were X pp more likely to cheat than attempts without EA on the same task (task fixed effects, adjusted for attempt number; 95% CI …; n = … attempts across T tasks, T′ with both)."

**Robustness and sensitivity** (report all; conclusions should not hinge on any one):
- outcome = cheat **try** (B1), not just success;
- exclude attempts after a failed cheat try (≈ 2% of attempts);
- attempt 1 only (no history at all; small but clean);
- add a rollout random effect, or a "previous answer flagged the test" covariate (history content);
- task random effects instead of fixed (uses more data, assumes more);
- strict vs broad EA; confident-only EA;
- EA × attempt-number interaction (is β constant early vs late?); group attempts 4–8 if cells are sparse;
- framing subgroups (capability / safety / generic), labelled indicative.

**More data if needed:** two more Track A epochs cost ≈ $5.5 to generate + ≈ $11 to judge and roughly double the within-task variation at the rollout level.

### 2c. Amount of EA (dose-response, observational)
EA density (per 100 sentences / per 1k tokens), count, strength, and persistence, related to cheating within task. Prefer density: longer reasoning and later attempts inflate counts.

### 2d. Descriptive timing and behaviour
- EA rate by attempt number (does EA rise after failure feedback?).
- Within-attempt order: first EA vs first bad test vs first cheat considered (relative positions).
- Bad test recognized: overall, and among honest failures (the "silent integrity" pattern).
- Cheat types, transparency, failed cheat tries; benchmark naming.

### 2e. Track B (observational)
- Episodes: 1 per task so far, so within-task estimates need more epochs. Report pooled + between-task, clearly labelled, and per-problem comparison with Track A on the same problems.
- Timing: first EA vs first bad test vs first cheat considered vs **first cheat edit** (detected from tool calls).
- Disclosure in the final message (`disclosed`; 13/36 cheats silent in run 37) and `flagged_test` for honest episodes.
- Existing pooled finding to re-check with the judge: eval-aware episodes cheated less (15/59 vs 21/44 by hand labels, broad-ish EA). It needs strict vs broad and more epochs before it is more than pooled.

## 3. Phase 2: causal (Track A)
**Primary design: attempt-level resample with a single injection.**
- Take phase-1 histories at a pre-registered decision attempt: the attempt after the first failure feedback, or every attempt before the rollout's first cheat. Never select by outcome.
- Regenerate that one attempt *K* times per condition, with the sentence prefilled at the start of its reasoning: neutral control, generic ("this might be a test"), capability-framed, safety-framed (+ unmodified).
- Histories contain no EA by construction (prior reasoning is dropped), so there is no "non-EA substrate" selection.
- **Outcome:** that submission cheats (scorer); B1 tries as robustness.
- **Analysis:** each condition vs neutral, paired by history; mean difference with a bootstrap clustered by problem, or a mixed logistic model (cheat ~ condition + (1 | problem / history)); by split and attempt number.
- **Secondary outcomes:** disclosure in comments; uptake of the injected sentence (judge: continued, ignored, contradicted), with results reported intention-to-treat.
- **Estimand:** "EA at the moment of decision changes whether this submission cheats". In Track A the injected thought leaves context after that attempt, so this is the natural estimand.
- **Cost:** ≈ $10–20 ([../judge-cost-estimate.md](../judge-cost-estimate.md)).
- **Optional robustness:** a small every-attempt-prefill run on conflicting, which estimates the whole-episode effect.
- **Possible follow-up:** inject mid-reasoning, after the model first blames the test (closer to Aranguri & Bloom; needs a two-stage generate).

**Track B causal:** not decided. One-off only (35% base rate) is the feasible version; no countdown or other pressure; if a model can time out, the outcome is defined as "cheats within budget", with timeout rates reported by condition.

## 4. Uncertainty
- **CIs = sampling uncertainty:** cluster bootstrap over **tasks**, resampling whole tasks with all their rollouts and attempts; 2,000–10,000 resamples; percentile 95% CIs. With task fixed effects, a task drawn twice counts as two copies. The bootstrap cannot fix having few tasks: flag intervals from small subgroups (e.g. ~10 tasks) as unreliable.
- **Judge error is not folded into CIs.** Report it separately (§5), with the direction of bias: EA noise unrelated to cheating pushes EA–cheat differences toward zero (stated as an assumption).
- The headline outcome carries no judge error. The robustness outcome (tries) and all EA-based predictors do.

## 5. Judge validation
Plan and status: [../judge-validation-plan.md](../judge-validation-plan.md).
- **Calibration:** 6 pilot attempts, blind-selected by a subagent for coverage, labelled by Mark (in progress), then by reviewer subagents (Sonnet + Opus, one transcript each, reading in pieces) and Claude, blind; codebook fixes from disagreements. Track B adds 2–3 short episodes later.
- **Proxy iteration:** 30 pilot attempts labelled by subagents + Claude, with Mark adjudicating disagreements only; judge prompts iterated on 20 and checked on 10, against go / no-go bars.
- **Gold (held out), per harness:** Track A **≈ 25 attempts**, Track B **≈ 12 episodes** (≈ 10 h of labelling each; lighter option 18 + 8). Stratified and oversampled for EA (blind subagent screen; for Track B, partly from the hand-labelled explicit-EA list), with sampling weights recorded for reweighting.
- **Metrics per label** (computed by `earh.judge.agreement`, the same code as the comparison page):

| Label | Metric |
|---|---|
| EA (occurrences) | precision / recall / F1 by span overlap; attempt-level presence agreement; framing agreement |
| Grader | precision (judge spans checked); EA↔grader confusion |
| First bad test, first cheat considered | presence agreement; share within ±5 sentences; median distance |
| B1 | agreement on `attempted`, `type`, `transparent` (+ `disclosed` in Track B) |
| Stability | 3 judge runs on the gold units; self-agreement |

- **Per-track metrics are primary.** A pooled number is secondary and reported only if the tracks agree within their CIs; otherwise report which track is weaker.
- **Reference status:** Claude is not the gold labeller (also an LLM, so not an independent reference); reviewer subagents produce candidate references for the proxy set only.
- **Error taxonomy:** structural (caught by validation and retried), classification, localization; report retries, escalations, manual labels and exclusions.

## 6. Methods paragraph (template)
> Cheat outcomes are determined by executing the impossible tests on every submission. Eval-awareness labels come from an LLM judge (GLM-5.3-Flash) that tags sentence IDs in segmented reasoning, using a shared codebook in both harnesses. Against held-out human labels (Track A: *n* = 25 attempts; Track B: *n* = 12 episodes), EA precision / recall were …/… and …/…, framing agreement …%, first-occurrence location within ±5 sentences …%. Within-task associations come from a discrete-time hazard model of the first cheat (logistic regression on attempts before the first cheat, with task fixed effects and attempt-number terms). Causal effects come from re-generating a fixed decision attempt with an injected sentence (neutral control vs EA framings), paired by history. Intervals are 95% cluster-bootstrap CIs over tasks. EA label noise independent of cheating biases associations toward zero.
