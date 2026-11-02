# Native Windows vLLM test profile

`qwen38fn-myllmbox` runs the separately installed [devjeonghwan RTX Spark runtime](https://github.com/devjeonghwan/vllm-for-rtx-spark/tree/5d6ca18458673405663c25f2f6353dd55a176d5e) directly on Windows ARM64. It is an experimental alternative to the default `qwen38fn-cache-dflash` WSLC profile on branch `qwen38fn-myllmbox`.

Following the budget experiments below, the user selected `MaxOutputTokens = 8192` as the shared serving output default/cap. This applies on the next launch; explicit smaller benchmark/request allowances remain effective. Earlier results retain their recorded settings. See [output allowance](Configuration.md#output-allowance) for override and context behavior.

The checked-in YAML copies upstream's 90 GB profile at that revision: NVFP4 local weights, 12,000,000,000 bytes of target FP8 KV, BF16 draft KV, FP8 drafter projections, HEAD2, dynamic MTP depth 3–7, NVMe PLE, decode graphs, 409,600-token context and 16 sequence slots. It does not use this project's LMCache adapter or WSLC volumes. Capacity is shared across requests; the context limit does not guarantee 16 simultaneous full contexts.

## Relationship to MyLLMBox and DFlash2

Devjeonghwan's Qwen3.8 integration derives from [MyLLMBox v5.3.1](https://github.com/myllmbox/qwen38-flash-next-recipe/tree/v5.3.1), pinned in its `sources.lock.json` to commit `8d36258ed111619ec40186c28bbb22f1c2c8c23f`. The native profile is the MyLLMBox-derived MTP contender in this comparison. The existing `qwen38fn-cache-dflash` profile uses a separate DFlash2 draft model and the AutoRound hybrid checkpoint under WSLC.

Stock MyLLMBox v5.3.1 disables FP8 drafter projections and makes HEAD2 opt-in; this Windows recipe enables both and uses a minimum draft depth of three. Results therefore describe devjeonghwan's configuration, not unmodified MyLLMBox defaults. Published DGX Spark token-throughput numbers also use different hardware/workloads from our local thinking-enabled agent test. Comparing these two local profiles measures the complete serving configurations; it does not isolate the speculative algorithm.

## Installation and configuration

Use the upstream release installer with native ARM64 Python **3.13** and its pinned dependencies. The tested wheel is `vllm 0.32.0+rtx_spark.0.1.2`, tagged `cp313-cp313-win_arm64`; it cannot be reused in Python 3.14. The checked installation has Python 3.13.17, PyTorch 2.14.0+cu134, Triton Windows 3.8.0.post29 and FlashAttention 2.8.4+cu13torch2.14. A future Python upgrade requires matching native wheels and fresh qualification.

Follow the upstream README for the CUDA 13.4-compatible driver, 96 GB dedicated GPU / 32 GB Windows allocation, paging file (98,304 MB initial / 131,072 MB maximum), and at least 32 GB free NVMe space for PLE. Obtain `nvidia/Qwen3.8-Flash-Next-FP4-Local` separately; the existing AutoRound model is not interchangeable with it.

The existing LMCache profiles are qualified with an **88 GiB GPU partition**, as documented in [Installation](Installation.md#requirements) and [Benchmarks](Benchmarks.md#test-configuration). That leaves more host RAM for LMCache's 8 GiB L1 pool, cache structures and runtime allocations. The [VMM adaptations and memory guard](LMCache.md#compatibility) are part of that integration. This is a requirement of the current cache configuration, not an inherent 88 GiB limit of DFlash2. Restore the documented partition before rerunning the unchanged cache baseline. This launcher does not change the GPU partition.

The runtime defaults to `../../vllm-for-rtx-spark` relative to this checkout. Override `NativeRuntimeRoot` in ignored `config.local.psd1` for another location; the expected executable is `.venv/Scripts/python.exe` inside it. `ModelRoot` retains its usual meaning and must contain `Qwen3.8-Flash-Next-FP4-Local`. For example:

```powershell
@{
    DefaultProfile = 'qwen38fn-cache-dflash'
    ModelRoot = 'C:\Users\michael\models'
    NativeRuntimeRoot = 'C:\Users\michael\source\github\vllm-for-rtx-spark'
}
```

`n1x.ps1 setup -Profile qwen38fn-myllmbox` validates this existing installation and model path. It does not download the FP4 weights, build a container, or reinstall dependencies. `doctor` runs the upstream installation checks and reports GPU state. Neither command changes Python or machine memory settings.

## Lifecycle

```powershell
.\n1x.ps1 start -Profile qwen38fn-myllmbox -PrintOnly
.\n1x.ps1 setup -Profile qwen38fn-myllmbox
.\n1x.ps1 start -Profile qwen38fn-myllmbox
.\n1x.ps1 wait -Profile qwen38fn-myllmbox -TimeoutSeconds 1800
.\n1x.ps1 status -Profile qwen38fn-myllmbox
.\n1x.ps1 test -Profile qwen38fn-myllmbox
.\n1x.ps1 logs -Profile qwen38fn-myllmbox
.\n1x.ps1 stop -Profile qwen38fn-myllmbox
```

The API is `http://127.0.0.1:8000/v1` (or `-Port`), with both `qwen` and `Qwen/Qwen3.8-Flash-Next` aliases. `qwen` keeps the existing client registrations and checks compatible. The profile defaults to localhost; an explicit `LanAccess = $true` local override enables the normal LAN/firewall behavior. Thinking follows the model template and may be controlled per request.

Start records PID, creation time, executable and full command line in `.state/n1x-qwen38fn-myllmbox/native.json`. Stop verifies that identity before terminating the process tree. Logs are in the same directory. An occupied API port is rejected; the launcher never adopts an arbitrary existing server. Stop other project profiles first, including containers. `restart` requires matching settings; `recreate` applies configuration or YAML changes. External runtime updates require stopping and requalifying the service.

Cleanup refuses to remove local process state while a native server is running. Native `clean`/`uninstall` are intentionally unsupported: the runtime, installed dependencies and upstream PLE caches belong to the external installation. Stop the native profile and select a WSLC profile to use this repository's existing cleanup commands.

## Matched agent comparison

The existing `qwen` API normally serves `qwen38fn-cache-dflash`; `qwen` itself is a model alias, not a profile. Use identical benchmark options for both profiles:

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

Local raw evidence (ignored by Git; the initial run retains the former `qwen38fn-devjeonghwan` profile name):

- `results/benchmarks/20261101-125850-qwen38fn-devjeonghwan-agents/host.json`
- `results/benchmarks/20261101-125850-qwen38fn-devjeonghwan-agents/agents/summary.json`
- `results/benchmarks/20261101-125850-qwen38fn-devjeonghwan-agents/agents/responses.jsonl`
- `.state/checks/smoke-qwen38fn-devjeonghwan.json`
- `results/benchmarks/20261101-cache-dflash-startup/` (startup logs and last low-headroom sample)

Local validation also passed `check.ps1`: 32 Python tests (three platform skips), PowerShell parsing and lifecycle/configuration suites, including native process identity, port conflicts, repeated start, configuration/recipe mismatch and stop handling.

## Extended qualification after the rename

The same native recipe is now named `qwen38fn-myllmbox`; the old profile name is no longer accepted. The follow-up qualification retains the existing suite budgets rather than starting the proposed 8K-budget experiment.

| Check | Native result | Recorded DFlash2 reference |
| --- | --- | --- |
| API features | 6/6: streaming, JSON, tools, reasoning, shapes, OCR | Same feature checks recorded as passing |
| Tool recovery | 24/24, 35.67 s; 64 requests, no truncations or preemptions | 24/24, 31.54 s |
| Archive retrieval | 7/7, from 3,977 through 407,877 actual input tokens; all normal completion | Separate archive/restore checks through 260,877 tokens; not the same sweep |
| Scheduling | Four running requests and four overlapping generation intervals; zero preemptions | Four running requests and four overlapping intervals; zero preemptions |
| Bounded concurrent workload | 49/50 across 12 cycles, 1,034.79 s; zero preemptions | 50/50, 501.2 s |

The archive checks are not RULER and do not establish general reasoning quality at the context limit. The final near-limit check used 407,877 input tokens plus a 128-token output allowance and returned all three exact codes. A spot sample during that request recorded about 10 GiB Windows memory available and 92,402 MiB GPU use; this is not a whole-run min/max measurement.

The mixed workload failed its first-attempt correctness gate: the final 130,917-token archive request consumed all 1,024 completion tokens as reasoning, ended with `finish_reason=length`, and returned no final content. The server remained healthy. A single retry of the unchanged request returned all three codes normally in 4.98 seconds (245 completion tokens, including 220 reasoning tokens; 130,816 cached prompt tokens). This warm-prefix retry is recorded separately in `mixed/empty-answer-retry.json`; it does not change the original **49/50** score or establish that a larger output budget resolves the failure. The native server was stopped after qualification and the retry.

### Read/write rates

These saved streaming runs did not retain directly attributable PP duration per request. Read values below therefore use the fallback **PP = e2e - decode**, where decode starts at the first generated reasoning/content token. Read = prompt tokens / PP; write = `(completion_tokens - 1) / decode`. Read includes effective cache lookup and frontend/queueing overhead, and counts the full prompt even on a warm-prefix request. Values are arithmetic means of per-request rates. The next matrix prefers direct PP telemetry.

| Workload | Native mean phase rates (read, write), tk/s | Historical DFlash2 mean phase rates (read, write), tk/s | Completion |
| --- | --- | --- | --- |
| JSON | (414.1, 83.6) | (—, 78.1) | Native 2/2 exact, normal completion |
| Python LRU cache | (308.1, 58.2) | (—, 61.1) | Both native samples hit 2,048 tokens; no complete-code score |
| B-tree explanation | (303.1, 55.2) | (—, 63.4) | One native sample hit 2,048 tokens; one completed; no quality score |
| Scheduling, C4 | (959.8, 23.5) | (—, —) | Fixed 256 generated tokens/request; phase rates per request, not aggregate throughput |

Historical read rates and scheduling phase rates were not retained in the curated reference; `—` is not zero. Separately, scheduling whole-run `(input, output)` throughput was **(948.5, 57.4) tk/s** for native versus recorded **(—, 55.2) tk/s** for DFlash2. This whole-run metric includes prompt processing and overlapping requests and must not be read as isolated decode speed.

Raw evidence is in `results/benchmarks/20261101-native-qualification/`, plus:

- `20261101-132218-qwen38fn-myllmbox-recovery/`
- `20261101-132254-qwen38fn-myllmbox-scheduler/`
- `20261101-132313-qwen38fn-myllmbox-speculation/`
- `20261101-133502-qwen38fn-myllmbox-mixed/`

All these directories are under `results/benchmarks/` and ignored by Git. `read-write-summary.json` preserves the derived tuple calculations separately from the original artifacts. These historical comparisons have different runtime configurations, memory partitions and client placement; they are not controlled speedup measurements. See [remaining work and the test matrix](Test-plan.md) for the deferred rerun and hybrid work.

## Qualification review and mixed-workload diagnosis

Reviewed November 1, 2026, from saved requests, responses, benchmark code, metrics and server logs. This review sent no new inference requests. **The native profile is usable for further experiments, but has not passed the full first-attempt mixed-workload correctness gate.** Keep the existing default and retain the native profile as an experimental reference.

### Confirmed failure mechanism

The mixed suite made 62 API requests for 50 task checks (each tool check has two requests). Exactly one required final answer was empty, and exactly one response reached its output limit: the cycle-12 archive request. It had 130,917 input tokens, thinking enabled, `temperature=0` and `max_tokens=1024`. All 1,024 generated tokens were reported as reasoning; final content was null and `finish_reason` was `length`. The request took 88.35 seconds.

The saved reasoning identified all three correct access codes, then repeatedly reconsidered whether to separate them with commas or newlines. The observed failure is therefore **reasoning-budget exhaustion before final-answer emission**. It is not an observed failure to locate the codes. The scorer accepts any separator between the three ordered codes, so a comma/newline mismatch did not cause the failure. Reasoning containing the answer does not satisfy the final-answer requirement.

Five earlier requests had identical long-archive messages and request settings apart from their cache salts. All five passed, using 200–322 completion tokens. The failed request's input plus reserved output was 131,941 tokens, well below the configured 409,600-token context limit. The benchmark explicitly overrides its helper's 128-token default with 1,024; the saved request confirms that override reached the API. No client-side truncation or incorrect budget forwarding is evident.

| Evidence | Original failure | Previously recorded single retry |
| --- | ---: | ---: |
| Input tokens | 130,917 | 130,917 |
| Output allowance | 1,024 | 1,024 |
| Completion / reasoning tokens | 1,024 / 1,024 | 245 / 220 |
| Cached input tokens | 0 | 130,816 |
| Request elapsed time | 88.35 s | 4.98 s |
| Required final answer | Empty; length limit | Correct; normal completion |

The retry's parsed request is identical to the original, including history, cache salt and budget; canonical request hashes match. However, the original overlapped vision, arithmetic and tool work, while the retry ran after the suite with a warm prefix. Its success does not isolate cache state, concurrency, speculative execution or numerical variation as the cause of the different generation. Temperature zero did not produce identical observed responses in these differing execution conditions. A larger allowance might help, but neither its effectiveness nor the deeper source of the generation variation is established.

### Runtime and cache findings

The mixed-run metrics recorded 62 completed requests and zero preemptions; completion counters do not imply task correctness. Health checks returned HTTP 200 after the suite and before the retry. The saved logs show no runtime OOM or engine failure associated with the failed request. A startup DeepGEMM import warning reports a missing Linux-style extension; startup continued into kernel warmup and successful requests. There is no evidence tying that warning to this individual failure. Tokenizer length warnings occurred during the earlier context sweep; the failed mixed request was below even the original 262,144-token context size.

All 14 archive requests, including both revisit checks, reported zero cached prompt tokens. Thus the two successful revisits establish correctness only, not prefix reuse. The separate retry does demonstrate reported prefix reuse. Suite-wide cache counters cannot identify the failed request's behavior more precisely than its own usage record. A dedicated cold/warm reuse test remains necessary. The 1,034.79-second run also does not establish a memory leak or progressive slowdown: request latencies vary, and continuous memory/clock telemetry was not collected.

The feature, agent, tool-recovery and standalone archive results remain valid within their tested scope. Short-generation code and explanation samples that hit 2,048 tokens remain throughput observations, not complete-answer quality passes. Historical DFlash2 comparisons favor the existing reference on agent throughput and mixed completion/time, but are not fresh controlled comparisons of the draft algorithms.

### Follow-up after this review

Keep the original score at **49/50**, with retry recovery separate. During the later diagnostic runs, replay this exact prompt with repeated cold/warm cache and isolated/concurrent conditions at the unchanged 1,024-token budget first. Then vary only the output allowance to 2,048 and approximately 8K. If variability remains important, add separately labelled MTP-off and explicit-output-format controls after validating their runtime support; do not change the reference workload silently. Capture per-request PP/decode timing, finish reasons, reasoning/final token counts and memory/clock samples. The current evidence supports these experiments, not an immediate default-budget or runtime change.

The reproducible offline analysis and source hashes are saved in `results/benchmarks/20261101-native-qualification/failure-review.json` and `review-native-qualification.py`. Server logs are preserved alongside them as `server-stdout.log` and `server-stderr.log`, so a subsequent launch will not overwrite this evidence. The server remains stopped.

## Focused output-budget replay: November 1, 2026

After the offline review, the saved failing archive prompt was replayed with **1,024, 2,048 and 8,192 output tokens**, twice each, in the order 1,024 / 2,048 / 8,192 / 8,192 / 2,048 / 1,024. These were isolated requests with 130,917 input tokens, thinking enabled and temperature zero. All original request fields except output allowance and cache salt were preserved. Each measured request used a unique salt and reported zero cached prompt tokens. Runtime, recipe and 96 GiB GPU partition were unchanged.

**All six passed on the first attempt, with no preemptions or retries.** Every response completed below 1,024 tokens. This establishes that the 8K allowance works for this prompt, but does not demonstrate an accuracy improvement or reproduce the original concurrent failure.

| Output allowance | Correct | Actual completion tokens, including reasoning | Mean e2e (s) | Mean PP / decode (s) | Mean (read, write), tk/s |
| ---: | ---: | --- | ---: | --- | --- |
| 1,024 | 2/2 | 462, 308 | 68.05 | 61.15 / 6.73 | (2,150.6, 57.2) |
| 2,048 | 2/2 | 319, 217 | 67.63 | 62.82 / 4.63 | (2,084.6, 57.3) |
| 8,192 | 2/2 | 184, 222 | 69.14 | 65.43 / 3.55 | (2,001.0, 57.1) |

PP and decode are **direct server measurements**, obtained from before/after metric deltas with exactly one completed request in each interval. The runtime defines PP from first scheduling to first generated token and decode from first to last generated token. Read = prompt tokens / PP; write = `(completion_tokens - 1) / decode`. Table values are arithmetic means of per-request measurements. No e2e-minus-decode fallback was needed. E2e also includes client/frontend overhead.

The first 1,024-token request triggered long-context kernel JIT compilation, so its latency includes startup overhead. Prompt processing dominates these cold requests, and two observations per budget are too few to attribute the different generated lengths or latency to budget alone. In particular, the shorter 8K responses do not show that a higher allowance makes the model more concise. The test changed concurrency from the original four-workflow mixed workload to one isolated request; it is a diagnostic pilot, not a replacement for the mixed qualification or the full comparison matrix.

Retain 8,192 as a candidate allowance. The next controlled diagnostic should repeat the budget comparison with the original concurrent workloads and enough repetitions to observe first-attempt failures, followed by the planned harder scored tasks. Keep the original mixed score at 49/50 and the serving default unchanged. The full-suite rerun remains deferred.

Raw requests/responses, per-request metric snapshots, profile/server identity, recipe, GPU partition, power scheme, 15-second memory/clock samples, scripts and summaries are saved under `results/benchmarks/20261101-135901-qwen38fn-myllmbox-output-budget/`. `summary.json` verifies unchanged request fields, zero cache hits and attributable direct timings. `completion.json` records the successful final health check; `final-status.json` records shutdown. The server was stopped after the six replays.

## Concurrent output-budget replay: November 1, 2026

The next diagnostic replayed the original failing cycle's four workflows together: the exact 130,917-token archive, the image question, `20 times 7`, and the `MIX-11` inventory tool round trip. Only the archive allowance changed; competing requests retained their original 1,024-token allowance. Tool continuations used the newly returned call ID and reasoning with the same inventory result. Each task received a fresh cache salt, shared within its tool round trip. All nine archive requests reported zero cached prompt tokens.

Three batches per allowance ran in balanced order: 1,024 / 2,048 / 8,192, then 2,048 / 8,192 / 1,024, then 8,192 / 1,024 / 2,048. **All 36 task checks passed across 45 API requests**, with no retries, output-limit truncations or preemptions. Saved request intervals overlap four ways in every batch; sampled server metrics independently observed four running requests. The first batch included kernel compilation after startup.

| Archive allowance | Archive correct | All task checks | Archive completion tokens, including reasoning | Mean archive e2e (s) | Mean batch phase (read, write), tk/s |
| ---: | ---: | ---: | --- | ---: | --- |
| 1,024 | 3/3 | 12/12 | 215, 286, 574 | 69.06 | (1,841.5, 3.59) |
| 2,048 | 3/3 | 12/12 | 261, 222, 483 | 70.36 | (1,745.0, 3.26) |
| 8,192 | 3/3 | 12/12 | 184, 220, 283 | 67.62 | (1,647.0, 2.87) |

These token rates use **direct server measurements for all five requests in each batch**: read = summed input tokens / summed PP durations; write = summed `(completion_tokens - 1)` / summed decode durations. The table averages those batch ratios across the three repetitions. Counter deltas matched exactly five completions in every interval. Shared counters cannot assign PP or decode to the archive alone, so no archive-specific token rate is claimed. Concurrent phase intervals overlap, and short requests' decode intervals include scheduling delays while the archive is processed. These rates are neither wall-clock aggregate throughput nor comparable to the isolated request's decode rate above. Variation in response lengths and scheduling also prevents reading the lower 8K batch write rate as an isolated budget-induced slowdown.

**The original empty-answer failure was not reproduced, including at 1,024 tokens.** Every archive response completed within 574 tokens. The test validates these sampled concurrent requests at all three allowances, but does not demonstrate an accuracy benefit from 8K or prove that the original failure is fixed. It replayed the final cycle's tasks without the preceding eleven cycles and archive revisits; prior execution history, cache state and generation variation remain possible differences. Three samples per allowance are insufficient to characterize a rare failure rate.

Keep the original mixed result at 49/50. The remaining budget study should prioritize the previously capped code/explanation cases and harder objectively scored tasks that can actually require more than 1,024 tokens. Reproduction of the full mixed sequence belongs in the deferred rerun, with both original and larger allowances clearly labelled. Retain 8,192 as an experimental allowance; no default or hybrid setting changed.

Evidence is saved under `results/benchmarks/20261101-141746-qwen38fn-myllmbox-concurrent-budget/`: exact requests/responses, protocol, direct metric snapshots, memory/clock samples, server logs and identity, recipe, reproducible scripts, source hashes and `summary.json`. The offline summary verifies the allowed request changes and four-way overlap. The final health check passed and the server was stopped; `final-status.json` records shutdown verification.

## Code and explanation budget comparison: November 1, 2026

The next diagnostic reused the exact LRU-cache and B-tree explanation prompts from `speculation_probe.py`. Each prompt ran three times at 1,024, 2,048 and 8,192 output tokens, with thinking enabled, temperature zero, streaming, one request at a time and a unique cache salt. Budget order was balanced across three rounds and prompt order alternated. All measured prompts reported zero cache hits. Empty required final answers received one unchanged-request retry, recorded separately.

**The larger allowance made a practical difference on these prompts:** first-attempt normal, nonempty completion was **0/6 at 1,024, 2/6 at 2,048 and 6/6 at 8,192**. These are completion counts, not a claim that every completed answer is fully correct. All four completed LRU implementations passed the executable checks; one 8K answer contained an incorrect expected-output comment in its example.

| Task | Allowance | Normal, nonempty completion | Executable implementation checks | Mean e2e (s) | Mean phase (read, write), tk/s |
| --- | ---: | ---: | --- | ---: | --- |
| LRU code | 1,024 | 0/3 | No complete implementation | 19.09 | (528.7, 54.2) |
| LRU code | 2,048 | 1/3 | 1 passed; 2 incomplete | 32.09 | (466.5, 57.4) |
| LRU code | 8,192 | 3/3 | 3 passed; example-comment caveat below | 41.83 | (508.8, 59.9) |
| B-tree explanation | 1,024 | 0/3 | Manual prose review | 17.59 | (547.9, 58.8) |
| B-tree explanation | 2,048 | 1/3 | Manual prose review | 25.01 | (381.5, 59.0) |
| B-tree explanation | 8,192 | 3/3 | Manual prose review | 18.95 | (551.1, 56.8) |

Timings and rates are arithmetic means of **first attempts, including failures and truncations**. PP and decode come from directly attributable server metric deltas, checked against one completed request per interval. Read = prompt tokens / PP; write = `(completion_tokens - 1)` / decode. Streaming first-token boundaries and full chunks are also retained. A fast truncated answer is not useful throughput, and these small samples do not establish a budget-induced decode speedup.

The 8K code responses used **2,110, 1,918 and 3,460 tokens**, including reasoning; their explanations used **429, 430 and 2,722 tokens**. Thus the allowance did not force 8K-token responses, and three of these six samples actually exceeded 2,048 tokens. Code mean latency rose to 41.83 seconds, while the shorter-budget attempts often failed. Generation still varied under the same temperature setting, so this is evidence from repeated trials rather than a deterministic replay of one token sequence with its cutoff moved.

### Code correctness and explanation quality

Generated source was inspected before execution in a restricted `python -I -S` subprocess with a five-second timeout, limited imports/builtins and AST checks. This is not an operating-system sandbox. The evaluator was validated against a correct reference and an intentionally incorrect MRU-eviction implementation. Each completed answer passed nine checks covering value retrieval, recency on access and update, LRU eviction, capacity-one behavior, type hints, and 600 deterministic mixed operations across capacities 1, 2 and 5. Unspecified missing-key and nonpositive-capacity policies were recorded rather than invented as requirements.

The third 8K implementation is correct, but its example's final comment predicts order `c, a, d` after another `get(a)`; running it correctly prints `c, d, a`. The other three completed code examples agree with execution. Thus 8K scored 3/3 on implementation behavior, with 2/3 also free of this identified example-comment error. No truncated code was repaired and then counted as a pass.

All completed explanations cover the requested tree lookup, equality, range, composite-index and write-cost topics, but completion is not a blanket factual-accuracy pass. Some overstate the restriction on non-leading composite columns: PostgreSQL can use non-leading conditions, including skip scans, although leading constraints are generally more efficient. [PostgreSQL 18 multicolumn indexes](https://www.postgresql.org/docs/18/indexes-multicolumn.html). Several also say every update must update each index; eligible PostgreSQL HOT updates can avoid new index entries. [PostgreSQL 18 HOT](https://www.postgresql.org/docs/18/storage-hot.html). Per-answer notes are in `quality-review.json`.

The 8K explanations contain 238, 242 and 312 whitespace-delimited words. The first is just below the predeclared 240–360-word review flag for the approximate 300-word request; this is reported rather than treated as an exact-length violation. The second covers write costs without explicitly discussing page splits. Six retries were required across the lower allowances: three explanation retries completed, while all three code retries remained truncated. Original first-attempt scores are unchanged. No request was preempted.

### Decision from this diagnostic

**Use 8,192 as the candidate allowance for subsequent thinking-enabled code and longer explanation tests.** It produced more complete, executable answers here than 1,024 or 2,048, at a higher average code latency. It does not establish eight times the accuracy, guarantee correct prose/examples, or resolve the earlier mixed-workload failure. Three samples per prompt are too few to choose a universal default. Keep the existing fixed-budget agent reference and serving default unchanged; next evaluate harder scored multi-turn/tool tasks and compare profiles under the same selected budget.

Evidence is saved under `results/benchmarks/20261101-163024-qwen38fn-myllmbox-generation-budget/`: original requests, complete streaming chunks, reasoning/final responses, direct metrics, memory/clock samples, protocol/rubric, evaluator validation and results, manual review, source hashes and summaries. The final health check passed; the server was stopped. This was a focused native diagnostic, not the deferred full profile-matrix rerun.

## Candidate hybrid experiment

The initial qualification review, isolated/concurrent archive pilots and code/explanation budget comparison are complete. Broader scored workload comparisons and hybrid implementation remain pending as described in the [test plan](Test-plan.md).

The installed Windows vLLM wheel already dispatches `method: dflash` with `DFlash2DraftModel` to `DFlash2Speculator`. That makes **native FP4-Local + DFlash2, initially without LMCache**, a plausible next experiment at the current partition. Presence of the code does not establish working Windows kernels, compatible target/draft state, or adequate memory.

Such a profile must replace the MTP drafter configuration and disable or adapt the MyLLMBox MTP-specific dynamic-depth/HEAD2 hooks, then qualify loading, graphs, tool correctness, acceptance and throughput. Keep the tested MTP profile intact for comparison. Adding LMCache afterward is a separate integration: the existing adapter depends on the WSLC VMM/IPC path and needs its cache-layout and host-memory budget validated. A smaller LMCache L1 pool is already configurable, but changes the established baseline and is not automatically sufficient at 96 GiB. No hybrid profile is presented as working by this change.

## Prior upstream smoke evidence

Before integration, the user reported 151 CPU tests with four skips, CUDA/installation checks, and successful arithmetic, structured JSON and streaming requests. The local upstream `.build/smoke-results.json` records 36 prompt tokens and 280 completion tokens in 5.745 seconds, first content at 0.158 seconds, and normal completion. With thinking disabled, the first-content boundary supplies the fallback PP duration: derived phase rates are **(228.0 read, 49.9 write) tk/s**, excluding the first generated token from the decode interval count. Direct PP was not recorded. Reported GPU use was approximately 87.4 GiB. This single response is separate from the thinking-enabled agent comparison and is not a direct speed comparison with the existing profile.
