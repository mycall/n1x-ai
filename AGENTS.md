# Model API guidance

These instructions are for applications and agent harnesses using the service.

- Use `http://127.0.0.1:8000/v1`, model `qwen`; check `/health` before sending work. The port is configurable.
- Thinking is on by default. Set `chat_template_kwargs.enable_thinking` explicitly when overriding it; reasoning consumes the generation budget and is returned separately from final content.
- For tool workflows, preserve returned tool-call reasoning for the continuation. The [inventory benchmark](wiki/Benchmarks.md#agent-and-restore-qualification) passes with MTP and DFlash2 using thinking and a 1,024-token output allowance; validate your own tasks.
- Preserve tool-call IDs, assistant tool calls, and matching tool results. Validate arguments and outputs before acting.
- Count rendered messages, tools, and image tokens; reserve room for output. The configured maximum includes both input and output. Concurrent sessions share capacity.
- Keep system prompts, tool definitions, reference order, and prior messages stable. Append new messages for prefix reuse. Keep `cache_salt` stable within the intended sharing scope.
- Allow time for cold prefill and restore queueing. A correct reply alone does not demonstrate a cache hit.
- Validate image/OCR responses and `finish_reason`; OCR can return HTML or truncate. Long-context vision needs application-specific validation.
- Keep this file minimal. Runtime settings and maintenance instructions belong in [the wiki](wiki/Home.md).
