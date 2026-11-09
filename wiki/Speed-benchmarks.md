# Speed and capacity benchmarks

The reusable `speed` suite renders configurations by context depth in one table segmented by client concurrency, with separate **(read, write) tk/s** values and visible gaps. Cold/incremental, thinking effort, output plans and timing sources remain separate comparison groups. [Existing measured results](Benchmarks.md) were collected by other protocols and are not silently converted into speed-grid cells.

Use explicit depths for nearly full 262K comparisons; the default grid also supports shorter-context applications. [Test coverage](Test-plan.md) distinguishes completed work from open questions.

## Preview the matrix without serving


```powershell
.\benchmark.ps1 -Suite speed -Profile qwen38fn-best -SpeedPlanOnly

# A larger planned matrix, still entirely offline:
.\benchmark.ps1 -Suite speed -Profile qwen38fn-best -SpeedPlanOnly `
    -SpeedConcurrency 1,8 -SpeedMode both
```

Planning reads local configuration and writes a fresh `results/benchmarks/speed-plan-*/plan.json`. It does not check hardware, prompt for a partition change, access WSLC or contact an API. The plan gives each depth/concurrency cell, measured-request and prime-request counts, and points that cannot fit the configured context. It makes no claims about the current server or model availability.

Default settings:

| Control | Default | Definition |
| --- | --- | --- |
| `-SpeedDepths` | `0,4096,16384,32768,65536,131072` | Primed history depth in incremental mode; full rendered input target in cold mode |
| `-SpeedConcurrency` | `1` | Independent simultaneous client streams, distinct from the server's sequence-slot limit |
| `-SpeedRepeats` | `3` | Fresh independent trials per point; grid order reverses on alternate repeats |
| `-SpeedExtensionTokens` | `2048` | New rendered tokens appended after the primed history |
| `-SpeedOutputTokens` | `256` | Fixed generated tokens, including reasoning; EOS ignored |
| `-SpeedMode` | `incremental` | `incremental`, `cold` or `both`; separate rate definitions |
| Thinking | On | Explicitly sent to the API; `-NoThinking` creates a separate comparison group |
| `-SpeedReasoningEffort` | `xhigh` | Explicit `chat_template_kwargs.reasoning_effort`; also accepts `medium` and `low`; requires thinking on |

The default plan has 18 measured requests and 15 one-token prefix primes. Token-calibration API calls are additional when a live run is eventually requested. Higher concurrency requires proportionately more live histories and KV capacity; an advertised maximum context does not guarantee that every concurrent depth will fit.

The installed model template explicitly defaults to **xhigh**, as recorded in the [local template audit](data/thinking-template-evidence.json). New speed requests send both `enable_thinking=true` and `reasoning_effort=xhigh`; token calibration, prefix primes and measured requests use the same effort. `medium` and `low` produce separate report groups. Thinking-off runs omit effort and remain diagnostics. An older run with no recorded effort stays **unspecified**; the current template audit does not retroactively prove its historical serving configuration.

## Run a speed comparison

Start and verify the chosen profile through the [service lifecycle](Configuration.md#lifecycle). The benchmark uses that running service; it does not load a model, change profile settings, restart the service, or download weights.

```powershell
# Nearly full input with a fixed 8K generation window:
.\benchmark.ps1 -Suite speed -Profile qwen38fn-best `
    -SpeedDepths 253944 -SpeedMode cold -SpeedConcurrency 1,8 -SpeedOutputTokens 8192

# Explicit effort comparison, saved as a separate workload:
.\benchmark.ps1 -Suite speed -Profile qwen38fn-best -SpeedReasoningEffort medium

# Separate cold and incremental tables from the same requested depth grid:
.\benchmark.ps1 -Suite speed -Profile qwen38fn-best `
    -SpeedMode both -SpeedConcurrency 1,8 -NoThinking
```

The speed client uses Python's standard library on Windows for every backend. `-Build` and `-Smoke` are rejected; use explicit matrix controls. Existing LMCache partition confirmation still applies to **live** LMCache profile tests. Planning and offline reporting bypass that confirmation because they do not touch the service.

Each live run records the effective profile, server/container identity, model listing, GPU partition, power setting when available, Git revision/dirty state and source hashes through the existing launcher. Run one selected profile at a time with no unrelated API requests. Server sequence slots are recorded alongside client concurrency. A deliberate four-slot versus eight-slot comparison is a complete-configuration comparison unless other differences are controlled.

## Workload and measurement

The server's `/tokenize` endpoint calibrates deterministic reference prose using the actual chat template and explicit thinking setting. Target lengths allow ±8 tokens; every response must report the **exact calibrated rendered input count**. Actual history, full input, newly added tokens, completion counts and cache coverage are retained. Reserve output space within the configured context; an oversized point is marked skipped rather than silently shortened. Cold depth zero is not applicable.

The 256-token speed sample is a fixed-work generation window with EOS ignored. It measures throughput under xhigh prompting but **does not measure completion of an xhigh reasoning task**. The service's normal 8,192-token output cap and existing quality suites remain separate; the planned 1K/2K/8K accuracy-budget comparison has not been performed.

**Incremental:** each positive-depth stream first primes its independent history using a one-token generation. All streams finish priming before the measured wave starts. The measured prompt preserves that prefix and adds approximately the configured extension. Read speed is **actual added rendered tokens / PP seconds**. Depth zero measures the extension without a prime. Cache hits are measured rather than assumed: eviction or recomputation remains a cost in the phase duration. The one-token prime output is not appended to the measured prompt and is excluded from speed scores.

**Cold:** each stream uses a fresh cache salt and a full prompt near the requested depth. Read speed is **full rendered prompt tokens / PP seconds**. A cold point with nonzero cache hits, or without attributable cache coverage, is invalid. Cold and incremental read numerators differ and are never combined into one speed curve.

**Write:** `(completion_tokens - 1) / decode_seconds`, including reasoning. Each measured request must produce exactly the configured output count and complete its stream. EOS is ignored to hold generated work constant; reaching the cap is intentional here. This does not score answer quality. The existing agent, recovery, mixed, retrieval and restore suites remain the correctness checks.

Per-request server PP/decode intervals are preferred. Only absent PP is derived as **PP duration = e2e duration − decode duration**. Streaming fallback begins at the first visible reasoning/content packet and includes transport/completion overhead; both sources are labelled, and direct and derived results are separated. Client TTFT and first-to-last packet intervals are also retained. SSE packets are not assumed to be individual tokens.

Cells aggregate rates as **sum of workload tokens / sum of phase durations** over all planned repeats and streams. These are weighted per-request phase rates, not whole-run throughput. All planned samples must be valid, have unique repeat/stream identities and share timing sources; otherwise the comparison cell shows incomplete. Faster individual requests at C1 do not establish greater aggregate serving throughput than C8.

## Compare saved runs offline

```powershell
.\benchmark.ps1 -Suite speed -SpeedRuns `
    'results/benchmarks/<first-run>/speed', `
    'results/benchmarks/<second-run>/speed' `
    -ReportOut 'results/benchmarks/speed-comparison-reviewed'
```

This route returns before configuration loading, partition checks, WSLC and API access. It recomputes cells from saved first attempts. Choose a new output directory; existing runs and comparison folders are not overwritten.

Artifacts are `plan.json`, `run.json`, `requests.jsonl`, `summary.json`, `comparison.md` and `comparison.json`. Raw requests preserve salts, prompt hashes, usage counts, timings, failures and prime versus measured phases. Failed first attempts are not retried or replaced. A partial run can still show its completed cells; missing cells stay visible. The output Markdown contains the segmented depth tables, followed by measurement details and metadata. JSON retains the full numbers.

Measured requests are logged as each worker completes, so a slow earlier stream cannot hide a later completed first attempt. Report output directories are created exclusively to prevent concurrent reports from overwriting each other. Before serving benchmarks, `n1x.ps1 wait` verifies the selected container's configuration fingerprint for cache profiles as well as MyLLMBox profiles; native readiness retains its process/recipe identity checks. Changed settings require `recreate` before measurement.

Old recovery, scheduler, archive, and agent logs are not interchangeable with `n1x-speed-v1` measurements: their work, cache states, output lengths, and concurrency differ. Keep them as [historical evidence](Benchmarks.md#retained-evidence).


## Nearly full 262K quality workload

```powershell
.\benchmark.ps1 -Suite capacity -Profile qwen38fn-best -CapacityConcurrency 1,8
```

This opt-in suite is separate from `all`. It calibrates actual rendered input near 253,944 tokens (±8), reserving 8,192 output tokens inside 262,144. Thinking/xhigh is explicit. The launcher retains its historical C1/C6 default; specify the desired concurrency explicitly. Three repeats of eight matched tasks per point cover retrieval, arithmetic/JSON, structured answers and supplied tool-result continuations. These are bounded quality checks, not general coding evaluations.

First-score correctness, actual input/output counts, cache hits, PP/decode sources, batch throughput, scheduling and preemptions are retained. Empty-final diagnostic retries never replace first scores. Cold scaling needs zero-hit evidence. The historical 6.4× C8/C1 target is a diagnostic; it is not a current promotion veto. For C1/C2-focused use, C2 remains an unmeasured gap.

The maintained entrypoints are `benchmark.ps1 -Suite speed` and `-Suite capacity`, alongside the original [reference suites](Benchmarks.md#run). Restore matching source from the [verified archive](Benchmarks.md#retained-evidence) when auditing old trial probes. See [Development](Development.md#local-checks) for offline checks and GPU validation.
