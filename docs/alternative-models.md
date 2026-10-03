# Alternative models

Cost is DeepInfra's USD per million tokens (input / output / cached input); "—" means no cached-input discount on DeepInfra.

**Pre-fill test:** raw prompt with the model's template and thinking on, reasoning pre-filled mid-sentence; the model must continue the thought, close the reasoning block, and answer. It was run once per model on a toy task (Sep 27, 2026).

## Active

| Model | Released | Size (total / active) | Cost | Notes |
|---|---|---|---|---|
| DeepSeek-V4-Flash-0731 | Jul 2026 | 284B / 13B MoE | $0.06 / $0.18 / $0.015 | Main model. Pre-fill verified. Official encoder vendored (`earh/vendor/encoding_dsv4.py`). Not the April preview `DeepSeek-V4-Flash`, which costs $0.09 / $0.18 / $0.018. |

## Possible

| Model | Released | Size (total / active) | Cost | Notes |
|---|---|---|---|---|
| DeepSeek-V4.1-Flash | Sep 2026 | 552B MoE | $0.20 / $0.60 / $0.006 (catalog price; currently 30% off: $0.14 / $0.42 / $0.004) | Pre-fill passes. New official encoder (`encoding/encoding.py`): numeric effort 1–100, default "high". Most relevant near-frontier swap. |
| GLM-5.3-Flash | Aug 2026 | 320B / 18B MoE | $0.15 / $0.50 / $0.03 (catalog price; currently 50% off) | Pre-fill passes with the official template. Didn't stop after answering, so add stop tokens `<\|user\|>`, `<\|observation\|>`. |
| Ling-3.0-flash | Aug 2026 | 124B / 5.1B MoE | $0.06 / $0.18 / $0.012 | Pre-fill passes with the official template. Same price as V4; open weights (inclusionAI). Only 5.1B active, so possibly weaker. |
| MiMo-V2.6-Flash | Sep 2026 | 309B / 15B MoE | $0.14 / $0.28 / $0.0027 | **Integrated (Oct 2026).** The MiMo-V2.6-Flash repo is still gated (401), but the public -MOPD and -RL repos ship the official template (identical apart from one blank line). Token counts of our renders match DeepInfra's chat endpoint exactly on 7 conversations, incl. tools, tool round-trips and reasoning in history. No reasoning-effort setting. Streams about 2–3× faster than GLM-5.3-Flash. |
| Nemotron-3.5-Lightning | Aug 2026 | ? | $0.08 / $0.20 / $0.04 | Pre-fill passes, but only with a **guessed** template (ChatML + `<think>`). HF repo returns 401, so get the official template before use. |
| Qwen3.5-9B | Mar 2026 | 9B dense (hybrid attention: 3 Gated DeltaNet linear layers per full-attention layer) | $0.10 / $0.15 / — | Pre-fill passes. Official template opens `<think>` itself. Low priority: a small dense contrast model, probably too weak for interesting cheating. DeepInfra's "sparse MoE" description is wrong. |

## Rejected

| Model | Released | Size (total / active) | Cost | Notes |
|---|---|---|---|---|
| Qwen3-32B | Apr 2025 | 32B dense | $0.08 / $0.28 / — | Formerly the second candidate. ~25 tok/s on DeepInfra, so attempts take 10–13 min; 0/2 cheats in parity; older than the 9-month window. |
| Hy3 | Jul 2026 | 295B / 21B MoE | $0.13 / $0.53 / $0.033 | Unreliable pre-fill: one run abandoned reasoning and answered without closing the reasoning block. Custom `</think:opensource>` tag. |
| Qwen3.6-35B-A3B | Apr 2026 | 35B / 3B MoE | $0.10 / $0.95 / — | Output is ~5× V4's price. Not tested. |
| Seed-2.0-mini | Feb 2026 | closed | $0.10 / $0.40 / $0.02 | DeepInfra wraps even the raw endpoint in a chat template (a 5-token prompt came back billed as 53), so pre-fill is impossible. Closed weights. |
| Qwen3.8-Flash | Sep 2026 | closed | $0.113 / $0.382 / $0.014 | Non-reasoning, closed API. |
| Gemini 3.1 Flash-Lite | May 2026 | closed | $0.25 / $1.50 / — | Closed API; no raw pre-fill. |
