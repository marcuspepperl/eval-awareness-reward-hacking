# Option 2 (deferred): tool-call format so injected reasoning persists across attempts

**Status:** not doing this for the MVP. We use **option 1**: the primary outcome is hacking on attempt 1, and we log all attempts. Revisit if the pilot shows most hacks first appear at attempt ≥ 2.

## Problem
In ImpossibleBench's minimal scaffold, test feedback arrives as a new **user** message. Both models' default templates strip reasoning from assistant turns before the last user message, so an eval-awareness sentence injected into attempt-1 CoT is invisible from attempt 2 onward.

## Idea
Make "submit solution" a **tool call** and return test feedback as a **tool result**. Both templates keep reasoning across tool calls within one user turn, so this is on-distribution with no flags:
- **V4:** `encode_messages` auto-disables `drop_thinking` when tools are defined.
- **Qwen3:** the template keeps `reasoning_content` for assistant turns after the last *real* user query, and tool results don't count as one.

## What it would take (~2–4h with Claude)
1. **Tool definition.** A single `submit(code: str)` tool in OpenAI format, placed on the system message.
2. **Prompt builders:**
   - **V4:** pass `tools` into `encode_messages`, then parse DSML tool calls with the vendored `parse_message_from_completion_text` (it already handles DSML).
   - **Qwen3:** render the `# Tools` block + `<tool_call>{json}</tool_call>` / `<tool_response>` turns by hand. Copy the format from the official Jinja template, not from memory.
3. **Solver.** Loop: generate → parse `submit` call → run tests in sandbox → append a tool-result message → repeat up to `max_attempts`. Also handle "no tool call" (a plain answer or flag) as the end of the episode.
4. **Parity checks:**
   - Verify on 2–3 tasks that encoded prompts match each model's reference template byte-for-byte. Use the V4 test file; for Qwen, render via `transformers` `apply_chat_template` offline.
   - Confirm the injected sentence is present in the attempt-3 prompt.
5. **Scoring.** Unchanged: ImpossibleBench's scorer re-runs the tests on the final code.

## Risks
- Tool-call parse failures (malformed DSML/JSON), which need a retry or error path.
- Longer contexts: all prior reasoning is kept, which adds input tokens (~1.5–2× input cost).
- Diverges from ImpossibleBench's published minimal-scaffold numbers, so it is less comparable.
