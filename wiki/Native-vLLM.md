# Native Windows vLLM test profile

`qwen38fn-myllmbox` is the historical Windows ARM64 reference using the separately installed [devjeonghwan RTX Spark runtime](https://github.com/devjeonghwan/vllm-for-rtx-spark/tree/5d6ca18458673405663c25f2f6353dd55a176d5e). It is distinct from the selected [MyLLMBox Linux runtime](MyLLMBox.md), despite the similar profile name. This page preserves its installation requirements and comparison results. Locally retired assets must be restored before use; see the [retirement record](Model-assets.md#local-retirement-record).

The checked-in YAML copies upstream's 90 GB profile at that revision: NVFP4 local weights, 12,000,000,000 bytes of target FP8 KV, BF16 draft KV, FP8 drafter projections, HEAD2, dynamic MTP depth 3–7, NVMe PLE, decode graphs, 409,600-token context and 16 sequence slots. It does not use this project's LMCache adapter or WSLC volumes. Capacity is shared across requests; the context limit does not guarantee 16 simultaneous full contexts.

## Relationship to MyLLMBox and DFlash2

Devjeonghwan's Qwen3.8 integration derives from [MyLLMBox v5.3.1](https://github.com/myllmbox/qwen38-flash-next-recipe/tree/v5.3.1), pinned in its `sources.lock.json` to commit `8d36258ed111619ec40186c28bbb22f1c2c8c23f`. The native profile is the MyLLMBox-derived MTP contender in this comparison. The existing `qwen38fn-cache-dflash` profile uses a separate DFlash2 draft model and the AutoRound hybrid checkpoint under WSLC.

Stock MyLLMBox v5.3.1 disables FP8 drafter projections and makes HEAD2 opt-in; this Windows recipe enables both and uses a minimum draft depth of three. Results therefore describe devjeonghwan's configuration, not unmodified MyLLMBox defaults. Published DGX Spark token-throughput numbers also use different hardware/workloads from our local thinking-enabled agent test. Comparing these two local profiles measures the complete serving configurations; it does not isolate the speculative algorithm.

## Installation and configuration

Use the upstream release installer with native ARM64 Python **3.13** and its pinned dependencies. The tested wheel is `vllm 0.32.0+rtx_spark.0.1.2`, tagged `cp313-cp313-win_arm64`; it cannot be reused in Python 3.14. The checked installation has Python 3.13.17, PyTorch 2.14.0+cu134, Triton Windows 3.8.0.post29 and FlashAttention 2.8.4+cu13torch2.14. A future Python upgrade requires matching native wheels and fresh qualification.

Follow the upstream README for the CUDA 13.4-compatible driver, 96 GB dedicated GPU / 32 GB Windows allocation, paging file (98,304 MB initial / 131,072 MB maximum), and at least 32 GB free NVMe space for PLE. Obtain `nvidia/Qwen3.8-Flash-Next-FP4-Local` separately; the existing AutoRound model is not interchangeable with it.

The WSLC cache profiles have different [partition and memory requirements](LMCache.md#memory-budget). Their 88 GiB requirement belongs to those configurations; it is not an inherent DFlash2 limit. Record and manually set the appropriate partition when comparing runtimes.

The runtime defaults to `../../vllm-for-rtx-spark` relative to this checkout. Override `NativeRuntimeRoot` in ignored `config.local.psd1` for another location; the expected executable is `.venv/Scripts/python.exe` inside it. `ModelRoot` retains its usual meaning and must contain `Qwen3.8-Flash-Next-FP4-Local`. For example:

```powershell
@{
    DefaultProfile = 'qwen38fn-myllmbox'
    ModelRoot = 'D:\Models'
    NativeRuntimeRoot = 'D:\Source\vllm-for-rtx-spark'
}
```

`n1x.ps1 setup -Profile qwen38fn-myllmbox` validates this existing installation and model path. It does not download the FP4 weights, build a container, or reinstall dependencies. `doctor` runs the upstream installation checks and reports GPU state. Neither command changes Python or machine memory settings.

Optional native source-update and DFlash experiments are preserved in the local benchmark archive. They are not part of the selected Linux runtime or this reference installation.

## Lifecycle

```powershell
.\n1x.ps1 start -Profile qwen38fn-myllmbox -PrintOnly
.\n1x.ps1 start -Profile qwen38fn-myllmbox
.\n1x.ps1 wait -Profile qwen38fn-myllmbox -TimeoutSeconds 1800
.\n1x.ps1 stop -Profile qwen38fn-myllmbox
```

The shared [lifecycle and client commands](Configuration.md#lifecycle) also apply. The profile defaults to localhost and uses the shared HTTP model alias plus `Qwen/Qwen3.8-Flash-Next`. [Output allowance](Configuration.md#output-allowance) and per-request reasoning controls apply independently of historical benchmark settings.

Start records PID, creation time, executable and full command line in `.state/n1x-qwen38fn-myllmbox/native.json`. Stop verifies that identity before terminating the process tree. Logs are in the same directory. An occupied API port is rejected; the launcher never adopts an arbitrary existing server. Stop other project profiles first, including containers. `restart` requires matching settings; `recreate` applies configuration or YAML changes. External runtime updates require stopping and requalifying the service.

Cleanup refuses to remove local process state while a native server is running. Native `clean`/`uninstall` are intentionally unsupported: the runtime, installed dependencies and upstream PLE caches belong to the external installation. Stop the native profile and select a WSLC profile to use this repository's existing cleanup commands.

## Matched agent comparison

The default API serves `qwen38fn-best`; reference profiles use the same client-facing alias when explicitly launched. Use identical benchmark options for both profiles:

```powershell
# Run after starting and waiting for each profile, one at a time.
.\benchmark.ps1 -Profile qwen38fn-myllmbox -Suite agents -LocalClient -AgentConcurrency 1,2,4 -AgentOutputTokens 1024
# Stop native, then start and wait for qwen38fn-cache-dflash before running:
.\benchmark.ps1 -Profile qwen38fn-cache-dflash -Suite agents -LocalClient -AgentConcurrency 1,2,4 -AgentOutputTokens 1024
```

The Windows client is selected automatically for the native profile. It supports `agents`, `recovery`, `mixed`, `scheduler`, and `speculation` without `-Build` or `-Smoke`, preserves the existing prompts and scoring, and defaults to thinking enabled. An agent run measures 72 inventory-tool tasks (four conversations, three turns, concurrency 1/2/4 followed by 4/2/1). It saves raw evidence, vLLM metrics, profile settings and server identity under `results/benchmarks/<timestamp>-<profile>-<suite>`. LMCache metrics are explicitly omitted for this client on both profiles; these runs do not qualify external-cache restores. The vLLM serving, AIPerf and RULER suites still use the WSLC client.

`-Python` selects the local client interpreter (default `python`). The mixed workload requires Pillow and scheduling requires aiohttp; both are already included in the tested native runtime environment. Reuse that environment for those probes:

```powershell
$clientPython = 'C:\Users\michael\source\github\vllm-for-rtx-spark\.venv\Scripts\python.exe'
.\n1x.ps1 test -Profile qwen38fn-myllmbox -Suite features
.\benchmark.ps1 -Profile qwen38fn-myllmbox -Suite recovery -LocalClient -Python $clientPython
.\benchmark.ps1 -Profile qwen38fn-myllmbox -Suite scheduler -LocalClient -Python $clientPython
.\benchmark.ps1 -Profile qwen38fn-myllmbox -Suite speculation -LocalClient -Python $clientPython
.\test.ps1 -Profile qwen38fn-myllmbox -Suite context -ContextTokens 4096,16384,31744,65536,131072,262144,408000 -ResultName context-qwen38fn-myllmbox
.\benchmark.ps1 -Profile qwen38fn-myllmbox -Suite mixed -LocalClient -Python $clientPython
```

These commands retain each existing suite's output limits: 1,024 for recovery/mixed, 2,048 for thinking-enabled short-generation probes, 256 fixed generated tokens for scheduling, and 128 for thinking-disabled archive retrieval. Archive retrieval is a deterministic local check, not the RULER dataset. The mixed suite is a bounded 12-cycle workload, not an overnight endurance test.

Compare total correct tasks divided by total measured seconds for each concurrency, and inspect truncations and failures. These are whole-profile comparisons: weights, quantization, runtime, KV budget, context, sequence slots and speculation differ. Record the GPU partition explicitly: the supplied native profile uses 96 GiB, whereas the supplied LMCache baseline uses 88 GiB. Keep power mode and client workload consistent, and avoid unrelated model traffic. Testing both at one partition requires separately qualified memory settings.

## Integration results: November 1, 2026

The native profile passed the three API smoke checks and **72/72 thinking-enabled inventory-tool tasks**, with zero output-limit truncations across 168 requests and zero measured preemptions. GPU allocation was 96 GiB; `nvidia-smi` reported 89,174 MiB (87.08 GiB) used before the agent run. Windows power-scheme information is saved in `host.json`; MSI mode was not independently recorded.

Rates below aggregate both sweep directions as total correct tasks / total timed seconds, excluding conversation warmup:

| Concurrency | Native MTP, new run at 96 GiB | DFlash2 + LMCache, previously recorded at 88 GiB |
| ---: | ---: | ---: |
| 1 | 0.296 correct tasks/s | 0.453 correct tasks/s |
| 2 | 0.411 correct tasks/s | 0.622 correct tasks/s |
| 4 | 0.537 correct tasks/s | 0.811 correct tasks/s |

The DFlash2 column is the [existing benchmark](Benchmarks.md#warm-agent-throughput), which also passed 72/72; it is **not a fresh matched run**. A new baseline attempt at the current 96 GiB partition was stopped by the existing host-memory guard at 3.87 GiB available. An idle-WSLC reset and retry was cancelled after confirming the documented 88 GiB requirement. No partition changes or reductions to the 4 GiB guard were made. Both services were stopped afterward. The historical DFlash2 rates are roughly 1.5 times the new native rates on this workload, but different run dates, client placement, memory partitions and power conditions prevent treating this as a controlled speedup measurement.

The original case `20261101-125850-qwen38fn-devjeonghwan-agents` and later renamed-profile experiments are preserved in the [local benchmark archive](Benchmarks.md#retained-evidence). The original name is historical; launch with `qwen38fn-myllmbox`.
