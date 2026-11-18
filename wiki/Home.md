# n1x-ai server guide

Run Qwen3.8 Flash Next on a Windows ARM64 machine with an NVIDIA RTX N1X. The default serving profile, `qwen38fn-best`, runs MyLLMBox Linux under WSLC and requires a 96 GiB GPU partition.

## First launch

1. Check the [installation requirements](Installation.md#requirements) and put the [W4 target and DFlash2 drafter](Model-assets.md#pinned-sources) under your model directory.
2. Follow [setup and verification](Installation.md#prepared-best-profile) in a non-administrator PowerShell. Setup prepares the runtime and storage. Start waits for API readiness.
3. Connect a client to `http://127.0.0.1:8000/v1` and select `qwen/qwen38fn-best`. See the [request example and client settings](Configuration.md#agent-clients).

## Use the server

| I want to… | Guide |
| --- | --- |
| Start, stop, inspect, or switch a running profile | [Service commands](Configuration.md#lifecycle) |
| Choose a profile for throughput, restart recovery, or another GPU partition | [Serving profiles](Profile-review.md) |
| Set the model path, port, context, or output allowance | [Configuration](Configuration.md) |
| Connect from another computer | [LAN access](Configuration.md#lan-access) |
| Integrate reasoning and tool calls into an application | [API guidance](../AGENTS.md) |
| Resolve a startup, memory, or connection failure | [Troubleshooting](Troubleshooting.md) |
| Reclaim disk space | [Cleanup and disk reclamation](Configuration.md#cleanup-and-disk-reclamation) |

## Maintain and evaluate

| I want to… | Guide |
| --- | --- |
| Identify required model files and volumes | [Model assets](Model-assets.md) |
| Size the prompt cache or verify reuse | [LMCache](LMCache.md) |
| Rebuild or upgrade the Linux runtime | [MyLLMBox](MyLLMBox.md) |
| Use the separate native Windows installation | [Native vLLM reference](Native-vLLM.md) |
| Change code and validate the service | [Development](Development.md) |
| Look up measured performance, correctness, or cache coverage | [Benchmark results](Benchmarks.md) |
| Run a speed or capacity comparison | [Benchmark procedures](Speed-benchmarks.md) |
