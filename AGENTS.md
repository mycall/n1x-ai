# Using the n1x-ai model API

For applications and agent harnesses calling this model. Current qualification
details and operational constraints live in `README.md` and `OPTIMIZATION_PLAN.md`.

- OpenAI-compatible endpoint: `http://127.0.0.1:8000/v1`; model name: `qwen`. Check `/health` before use. The endpoint exists only while a serving/test container is running; coordinate calls with active benchmarks.
- Text, streaming, JSON output, tool calls/results, separate reasoning, OCR, and image description have passed focused checks. These checks do not establish general task accuracy.
- Validate vision responses and `finish_reason`: focused OCR tests have intermittently returned HTML instead of transcription.
- Use standard `tools` definitions and preserve assistant `tool_calls`, call IDs, and matching tool-result messages in history. Validate tool arguments and application outputs.
- Set `chat_template_kwargs.enable_thinking` explicitly. Reasoning, when enabled, is separate from final content and consumes the generation budget.
- The tested maximum context is 262,144 tokens, shared between prompt and generated output. Count the rendered messages, tools, and image tokens; reserve output space.
- Capacity checks passed two near-262K sessions and four near-131K sessions with short replies. Four near-131K agents also passed growing tool-call histories and resume. KV memory is pooled; arbitrary concurrency, simultaneous prefills, and long-context vision remain unqualified.
- For cache reuse, keep system instructions, tool definitions, reference ordering, and prior messages stable. Append new user/tool messages; put changing timestamps and turn identifiers after reusable content.
- Keep `cache_salt` stable across turns and resumes within the intended cache-sharing scope. A new salt or changed early prefix prevents the corresponding reuse.
- Allow client timeouts to cover multi-minute cold prefills and queueing. LMCache can fall back to recomputation; a correct answer alone does not prove a cache hit.
- Keep these instructions minimal and update capability/usage guidance from verified findings. Model-runtime tuning and test procedures belong in the optimization plan.
