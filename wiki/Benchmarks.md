# Benchmarks

The current `qwen38fn-best` was promoted from the [96 GiB campaign](96GiB-comparison-campaign.md): batch8K/KV15 with LMCache RAM4/SSD160 completed 48/48 C2/C4 tool tasks. Its C4 correct-work throughput was about 31% higher than the completed KV11 C4 measurement. No matched 88 GiB control was run. The older speed matrix and prefill results below describe the previous KV11 profile and retain their original runtime identities.

The [November 11 near-full tool trial on 96 GiB](Near-full-tools-96GiB.md) passed 24/24 first-attempt C1/C2 tasks with the locally configured best profile. All 40 warm requests reused 249,856 tokens through native prefix cache; external hits were zero. Its runtime image and protocol differ from the historical comparisons below.

This page retains measured performance and correctness evidence. Near-full comparisons appear first, followed by historical reference results with their original workloads. See [Component review](Profile-review.md) for the selected profile and top ten, [Speed and capacity benchmarks](Speed-benchmarks.md) for reusable tools, [request parameter trials](Parameter-trials.md) for the DFlash2 reasoning/temperature comparison, and [Test coverage](Test-plan.md) for unmeasured cases.

The [completed best-profile speed matrix](Qwen38fn-speed-matrix.md) uses the common `vllm bench serve` benchmark at C1–C8 and 4K/8K/64K/262K, with three cold bursts per cell and fixed 512-token generation. It reports per-request read/write rates, queueing and whole-burst throughput separately. The correctness workloads below retain their original protocols.

## Matched prefill comparison

Same W4 target, DFlash2 K3, standard FP32 SSM, BF16 indexer, KV11, RAM4/SSD160 and eight server slots. Only prefill batch changed 4,096 → 8,192, apart from required run identities. All points use **253,936–253,946 actual input tokens**, a **262,144 total context**, thinking/**xhigh**, and an **8,192-token output allowance including reasoning**. Each cell contains eight first attempts, all correct. Generated lengths vary; these are completed retrieval tasks, not fixed 8K output streams.

| Client concurrency | Phase | 4K batch (read, write) tk/s | 8K batch (read, write) tk/s | 4K / 8K batch seconds | 8K correct-work throughput change |
| ---: | --- | --- | --- | --- | ---: |
| **C1** | Cold | (1,282.28, 38.54) | (2,194.60, 57.54) | 1636.44 / 961.68 | +70.16% |
| C1 | Immediate same-prompt repeat | (68,303.77, 38.77) | (57,550.76, 58.94) | 87.43 / 77.27 | +13.15% |
| **C2** | Not measured | — | — | — | — |
| **C8** | Cold | (1,804.31, 3.13) | (1,441.86, 1.38) | 1107.03 / 1412.31 | −21.62% |

Correct-work throughput is correct tasks / batch wall seconds. Phase tuples use summed prompt tokens / summed PP durations and summed `(completion_tokens − 1)` / summed decode durations. These request-phase rates are not aggregate serving throughput. Prefer direct PP; **only when unavailable derive PP duration = e2e duration − decode duration**, then compute the rate. Never subtract token rates. Concurrent decode intervals include scheduling/prefill stalls.

At 4K, immediate repeats each reused 249,856 tokens through native prefix cache (1,998,848 total native hits, zero external hits). At 8K, each reused 245,760 through LMCache (1,966,080 total external hits, zero native hits). Effective read includes reused tokens and is not an uncached GPU-compute rate. External hits do not establish whether all bytes came from SSD rather than RAM. The 8K batch's larger recomputed tail still produced a faster completed warm batch.

Generated ranges were 85–381 / 77–420 for 4K/8K cold C1; 92–459 / 83–393 for warm C1; and 91–459 / 82–349 for cold C8. All include reasoning. [Exact numbers, input ranges and source audit hashes](data/benchmark-results.json).

## Earlier C1 and C8 comparisons

Same near-full input range and 8K allowance as above. These are separately collected groups; do not pool them with the matched prefill comparison. All displayed points scored 8/8 first attempts. Durations cover eight completed tasks.

| Client C | Combination | Phase | (Read, write) tk/s | Seconds | Reuse / interpretation |
| ---: | --- | --- | --- | ---: | --- |
| **1** | Former best: batch8K/KV12/cache off | Cold rematch | (1,724.26, 50.19) | 1221.37 | Zero hits |
| 1 | Former best: batch8K/KV12/cache off | Immediate repeat | (1,566.39, 41.59) | 1348.22 | Zero hits |
| 1 | LMCache batch4K/KV11/RAM4/SSD160 | Displaced replay, earlier group | (57,239.63, 37.31) | 93.89 | 8/8 restored |
| **8** | Former best: batch8K/KV12/cache off | Cold | (1,500.81, 1.77) | 1333.63 | Scheduled peak 2 |
| 8 | Batch4K/KV12/cache off | Cold | (1,314.20, 1.90) | 1519.20 | Scheduled peak 2 |
| 8 | Batch4K/KV15/slots4/cache off | Cold | (1,412.69, 1.39) | 1398.73 | Scheduled peak 3; reserve fell to 1,249 MiB |
| 8 | LMCache batch4K/KV11/RAM4/SSD160 | Displaced replay | (1,855.91, 2.93) | 1089.38 | 2/8 restored; six fully recomputed |

The C8 replay recorded six L1 reservation failures; the serial replay recorded none. Eager prefetch was already disabled. Correct answers alone do not prove cache restoration. The final speed/accuracy policy allows partial restores; the original strict-restore failures remain recorded.

Eight clients do not mean eight resident full contexts: the latest 8K run peaked at two scheduled and seven waiting, with no preemptions. Its C8/C1 cold correct-work ratio was 0.681×, below the 6.4× near-linear diagnostic. An earlier former-best cohort scored 24/24 at each C1/C6/C8, with phase rates (1,746.19, 53.09), (1,472.42, 1.57) and (1,479.51, 1.57) tk/s. Neither higher concurrency improved that cohort's cold throughput. Separate former-best near-full tool workflows passed 8/8 at C1 and C6; these are not tool-workflow qualification of the new LMCache setting.

Sequential timings include observed clock/power variation and variable generated lengths. See [Test coverage](Test-plan.md) for the limits of these measurements and remaining comparisons.

## Retained evidence

The repository retains [numeric results and audit hashes](data/benchmark-results.json), [historical top-ten summaries](data/profile-history.json), [model inventory](data/model-assets.json), and an [archive receipt](data/benchmark-archive.json).

Raw results, prior reports, and temporary trial source were archived in `n1x-ai-benchmark-archive-20261108.zip` beside this checkout. Every archived file was read back and SHA-256 verified. Its `ARCHIVE-MANIFEST.json` records original relative paths and hashes; extract into a separate directory to inspect or reproduce old audits. The ZIP is local evidence and is not included in Git. At archiving, original retired files also remained in the sibling `n1x-ai-retired-20261108` folder; that move alone did not reclaim disk space. Later model/runtime cleanup is recorded in [Model assets](Model-assets.md#local-retirement-record).

## Historical reference benchmark

The following retained results concern the original `qwen38fn-cache-dflash` reference, not today's selected best. They use different actual prompt lengths, output budgets and runtime settings. They remain useful historical evidence and documentation for the reusable suites.

### Test configuration

MSI Prestige N16 Flip AI+, NVIDIA RTX Spark N1X, 128 GiB system memory, and an 88 GiB GPU partition. External power was connected and Windows reported Balanced. MSI Performance/Boost was not independently reconfirmed for these runs.

- Qwen3.8 Flash Next W4A16 AutoRound hybrid, revision `8b82f0b7abe3d1150a7827d298c75e86267636ae`.
- DFlash2 drafter, revision `a22a1744e85c17364dcc54a6a420af7135d4c7f6`, with three draft tokens.
- 262,144-token context limit, four sequence slots, and 4,096 scheduled tokens per step.
- 8 GiB GPU KV pool, FP8 KV/indexer, BF16 sliding-attention KV, and 1,664-token blocks/chunks.
- Native PLE, 8 GiB LMCache host pool, and a shared 16 GiB SSD cache budget.
- vLLM 0.32.0, LMCache 0.5.6, and PyTorch 2.13.0+cu130.

Thinking is enabled. Agent tests allow 1,024 output tokens per request, including reasoning, and preserve tool-call reasoning for the tool-result continuation. Other suites use the budgets described below. A separate client container shares the server network namespace without loading another model.

### Agent and restore qualification

#### Warm-agent throughput

Each concurrency point warms four independent conversations, then measures three inventory-tool tasks per conversation. The sweep runs at concurrency 1, 2, and 4, then repeats in reverse order. Histories grow within each conversation.

A correct task requires the exact tool name and SKU, a matching tool-call/result ID, and the exact session-code/inventory answer with normal completion. Rates include time spent on every timed attempt and exclude initial conversation warmup.

| Concurrency | Correct tasks | Correct tasks/s |
| ---: | ---: | ---: |
| 1 | 24/24 | 0.453 |
| 2 | 24/24 | 0.622 |
| 4 | 24/24 | **0.811** |

**72/72 tasks pass, with no truncations or preemptions.** Concurrency 4 gives the highest measured throughput for this workload. The full run takes 234.9 seconds including warmups. The API remains healthy and SSD cache usage finishes at 15.98 GiB.

This qualifies the synthetic inventory workflow, not general coding-agent reliability, maximum-context agent work, or arbitrary tool schemas. Validate application-specific tasks before relying on the profile.

#### Tool recovery

The thinking-enabled `recovery` suite runs four concurrent conversations with six tasks each, selecting between inventory and price tools. Temporary failures require one retry; canonical-SKU responses require correcting the next call's argument. The harness validates tool names, exact arguments, matching result IDs, and final values.

| Scenario | Correct tasks |
| --- | ---: |
| Normal tool selection | 8/8 |
| Retry after temporary tool error | 8/8 |
| Correct SKU from tool response | 8/8 |

All **24/24 tasks pass** in 31.54 seconds, including 40 valid tool calls, with no truncations or preemptions. Thinking uses a 1,024-token output allowance. This checks service-directed argument correction, not arbitrary malformed JSON repair or recovery from every tool failure. These short synthetic conversations are separate from the warm-agent throughput table.

#### Concurrent mixed workload

The thinking-enabled `mixed` suite runs 12 cycles, each submitting four tasks together: an archive lookup, an image-shape question, arithmetic, and an inventory-tool round trip. Fresh archives alternate between 64,917 and 130,917 input tokens. Two additional requests revisit earlier archives. Every request allows 1,024 output tokens including reasoning.

**50/50 checks pass over 501.2 seconds (8.35 minutes)**, with no truncations or preemptions. Five-second Windows headroom samples range from 6.51 to 7.08 GiB; SSD cache usage finishes at 15.81 GiB and the API remains healthy. External-cache hit tokens and completed GPU restores are both zero, so this run does not duplicate the separate SSD-restore qualification.

This establishes a bounded mixed-workload check at concurrency four. It does not establish overnight stability, four simultaneous long archives, or combined near-262K vision/agent sessions. Client submission overlaps; individual task execution and transfers may serialize.

### Serving throughput

vLLM's serving benchmark uses 16 requests per point, thinking enabled, and 128 generated tokens with EOS ignored. Rates include prefill and reasoning output; these fixed-length requests do not measure answer correctness. Mean request latency excludes waiting in the client's concurrency queue.

| Input target | Concurrency | Whole-run (input, output), tk/s | Mean first token (s) | Mean completion (s) |
| --- | ---: | ---: | ---: | ---: |
| 4K | 1 | (—, 19.3) | 2.29 | 6.62 |
| 4K | 2 | (—, 24.8) | 2.88 | 10.34 |
| 4K | 4 | (—, 29.2) | 3.55 | 17.19 |
| 16K | 1 | (—, 11.1) | 7.43 | 11.58 |
| 16K | 2 | (—, 12.8) | 9.75 | 19.92 |
| 16K | 4 | (—, 13.8) | 10.02 | 36.65 |

These retained output rates include prompt processing and queueing; they are not pure decode-phase speed. Input throughput and directly measured PP were not retained in this curated table, so they are not inferred from target input lengths. The [speed suite](Speed-benchmarks.md#workload-and-measurement) records separate phase rates for new measurements.

All **96/96 requests complete**. Concurrency improves aggregate throughput while increasing per-request latency. The warm-agent table measures a different workload and should guide correct-work throughput decisions.

### Multi-turn retrieval accuracy

AIPerf runs 16 independent sessions with four key-retrieval turns each, roughly 16K initial context, thinking enabled, and a 1,024-token output allowance. Rates include initial loading and follow-up turns. Answer TTFT measures the first final-content token, after any reasoning; empty answers are excluded from that latency average but counted as failures.

| Concurrency | Correct turns | Correct turns/s | Initial answer TTFT (s) | Follow-up answer TTFT (s) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 63/64 | 0.344 | 7.28 | 1.28 |
| 2 | 63/64 | 0.422 | 11.58 | 2.17 |
| 4 | 64/64 | 0.482 | 17.26 | 4.77 |

**190/192 turns are correct.** Two responses finish with `stop` but contain no final answer. They are not timeouts or output-limit truncations. The tool-task passes therefore do not establish perfect multi-turn retrieval reliability; harnesses must validate final content.

After a service restart, isolated streaming replays of both captured requests succeed with their original cache salts and with fresh salts: 4/4 correct answers. These diagnostics do not change the 190/192 score, isolate the cause, or guarantee retry success under the original workload. Preserve completed tool results when retrying generation and surface persistent failures.

### Long-context accuracy

The thinking-enabled RULER subset uses two samples per task and context budget. Scores use the upstream reference-string metric; variable-tracking samples each contain five reference variables.

| Context budget | Needle input tokens | Needle score | Variable-tracking input tokens | Variable-tracking score |
| ---: | ---: | ---: | ---: | ---: |
| 16,384 | 14,520-14,524 | 100% | 14,171-14,172 | 100% |
| 65,536 | 64,270 | 100% | 63,098-63,347 | 100% |
| 131,072 | 129,820 | 100% | 128,868-128,872 | 100% |
| 262,144 | 260,895 | 100% | 259,947-259,950 | 100% |

All **16/16 samples complete without truncation**. Input leaves room for reasoning and final output; the context budget is not the input-token count. This sequential two-task subset does not establish full RULER performance or general long-document agent quality.

### Generation overlap and decode rates

The scheduling probe submits four independent requests together, with 256 generated tokens each and EOS ignored. It observes four running requests and four overlapping generation intervals, with zero preemptions: whole-run **(input unrecorded, output 55.2) tk/s**, 5.42 s mean first-token latency, and 18.13 s mean completion time. This retained aggregate is not a per-request decode-phase rate. Intervals begin at the first reasoning or content token; this is not a correctness score.

The short-generation probe runs each prompt twice at concurrency one with a shared per-task cache salt. The mean streamed decode-rate estimate excludes initial prefill and includes reasoning tokens, using `(completion_tokens - 1) / (completion time - first generated-token time)`.

| Task | Mean phase rates (read, write), tk/s | Outcome |
| --- | ---: | --- |
| JSON | (—, 78.1) | Both answers exact; normal completion |
| Python LRU-cache example | (—, 61.1) | Both hit the 2,048-token cap; no code-quality score |
| B-tree explanation | (—, 63.4) | Both hit the 2,048-token cap; no quality score |

Read rates were not retained in this historical summary. The write column uses the streamed decode estimate described above.

Reasoning consumes the shared output budget. These capped code and explanation samples do not establish complete-answer throughput; application prompts may need larger budgets.

### DFlash2 comparison

Both profiles below use thinking, the same inventory tasks and scoring, a 1,024-token output allowance, and the bounded 16 GiB SSD adapter.

| Concurrency | DFlash2 correct tasks/s | MTP correct tasks/s | DFlash2 / MTP |
| ---: | ---: | ---: | ---: |
| 1 | 0.453 | 0.219 | 2.07x |
| 2 | 0.622 | 0.266 | 2.34x |
| 4 | 0.811 | 0.300 | 2.70x |

Both pass 72/72 tasks. MTP uses one draft token, 16 sequence slots, and 2,048-token cache blocks/chunks; both profiles have an 8 GiB KV pool. These are complete-profile measurements, not an isolated comparison of speculative algorithms. Power settings were not independently controlled between runs. MTP's full run takes 400.5 seconds including warmups.

Thinking-disabled checks reproduce skipped tool calls with DFlash2, MTP, and target-only decoding. Thinking, output allowance, and reasoning-history handling change together in the successful agent configuration; the evidence does not establish quantization as the cause of those failures.

### Feature and cache validation

Cache qualification is separate from the thinking-enabled agent benchmark. The deterministic archive-retrieval checks explicitly disable thinking and use a 128-token output allowance. They establish cache behavior, not throughput for the default agent workload.

| DFlash2 check | Result |
| --- | --- |
| Streaming, JSON, basic tool round trip, reasoning, shapes, OCR | Pass as separate feature checks |
| 260,877-token archive retrieval with bounded SSD cache | Correct; seeded entry occupies about 11.97 GiB |
| Same request after engine restart, with GPU/RAM caches empty | Correct; 259,584 external-cache hit tokens, one completed GPU restore, 159 SSD-prefetched chunks, zero native prefix hits, and zero preemptions |
| Two independent 130,877-token requests submitted together after a same-container restart | Both correct in 4.58 seconds total; 256,256 external-cache hit tokens, two GPU restores, 160 SSD-prefetched chunks, zero native prefix hits, and zero preemptions |

Total SSD cache usage remains 15.97 GiB after the restore. This establishes a near-262K DFlash2 SSD restore under the 16 GiB cap.

The concurrent pair occupies about 11.92 GiB on SSD, with total cache usage at 15.98 GiB before restoration. Both requests overlap at the client; internal transfers may serialize. These results establish two 131K restores under the cap, not two simultaneous 262K restores.

Vision, maximum context, and agent correctness are separate checks. They do not establish simultaneous maximum-context vision or four concurrent maximum-length sessions. The profile's four sequence slots are a scheduling limit, not a guarantee that four 262K contexts fit.

### SSD budget validation

The 16 GiB cap applies across project namespaces. Entries compete for space and eviction can force recomputation; stored file sizes depend on the profile and coverage.

The bounded MTP adapter verifies a 130,877-token SSD restore after engine restart: 126,976 external-cache hit tokens, one completed GPU restore, 63 SSD-prefetched chunks, zero native prefix hits, and zero preemptions. A partially evicted 260,877-token MTP request recomputes correctly without a restore.

For the measured MTP working set, the 262K and 131K entries occupy 6.97 and 3.44 GiB. Replaying file sizes and access order through the eviction policy retains both at 16 GiB; at 8 GiB it retains 124/190 files from the longer entry and all 94 files from the shorter entry. This is a storage-policy replay, not a GPU restore benchmark at both budgets, and does not guarantee retention under additional traffic. DFlash2's measured 262K entry is larger; do not apply MTP sizing to it.

## Run

Start the reference profile, then run its thinking-enabled agent benchmark:

```powershell
# Stop any other model profile using the API port first.
.\n1x.ps1 start -Profile qwen38fn-cache-dflash -TimeoutSeconds 1800
.\benchmark.ps1 -Build -Suite agents

# vLLM serving, AIPerf multi-turn retrieval, and the RULER subset.
.\benchmark.ps1 -Suite all

# Thinking-enabled tool selection, retries, and argument repair.
.\benchmark.ps1 -Suite recovery -Profile qwen38fn-cache-dflash

# Thinking-enabled long retrieval, vision, arithmetic, and tools together.
.\benchmark.ps1 -Suite mixed -Profile qwen38fn-cache-dflash

# Seeds two 131K entries, restarts the service, then verifies SSD restores.
.\test-restores.ps1 -Profile qwen38fn-cache-dflash
```

Supply `-PowerMode` with the actual MSI setting to record it; the option does not change system settings. Avoid other model requests during measurements. The agent suite does not accept `-Smoke`; use its explicit workload controls instead.

### Agent workload controls

`-Suite agents` retains the original default workload: four conversations, three inventory tasks per conversation, concurrency points 1/2/4 followed by 4/2/1, and a 1,024-token output allowance with thinking enabled. That is 72 scored tasks across both sweeps. `-NoThinking` retains the 128-token default allowance. Each point warms the conversations before timing their tool tasks.

| Option | Default | Purpose |
| --- | --- | --- |
| `-AgentConcurrency` | `1,2,4` | Client concurrency points, each from 1 to 16; the second sweep reverses their order |
| `-AgentOutputTokens` | Automatic | Total generated tokens per request, including reasoning; zero uses the thinking/non-thinking default |
| `-AgentSessions` | `4` | Independent conversations per point, from 1 to 16 |
| `-AgentTurns` | `3` | Inventory tasks per conversation, from 1 to 100 |

```powershell
# Rebuild the benchmark client once to pick up the new options.
.\benchmark.ps1 -Build -Suite agents -Profile qwen38fn-cache-dflash -AgentConcurrency 1,2,4 -AgentOutputTokens 8192

# One continuous conversation, twelve tasks, repeated in two sweeps.
.\benchmark.ps1 -Suite agents -Profile qwen38fn-cache-dflash -AgentConcurrency 1 -AgentSessions 1 -AgentTurns 12 -AgentOutputTokens 8192
```

These controls change the client workload, not the serving profile's scheduling or context limits. Client concurrency cannot exceed the number of conversations actually submitted. Keep settings identical when comparing profiles; changed output allowances or conversation lengths are separate measurements from the historical results above. The configured context must hold both the rendered prompt and output allowance.

The agent probe records each request and response with a start timestamp and elapsed time. Failed requests retain their request, error and available HTTP response body in `errors.jsonl`. Each completed point includes per-conversation scores and durations in `session_results`; those durations begin when a worker starts the conversation and exclude time waiting for a client worker. Aggregate point timing includes that queueing. Both `reasoning` and `reasoning_content` are preserved on assistant tool calls for continuation.

New runs write raw responses, commands, configuration, package versions, scores and cache counters to ignored `results/benchmarks/`. Failed runs retain their artifacts. Pre-closeout runs were moved to the local archive described above. The benchmark client is removed automatically; the model service remains running.

## Coverage and limits

The serving, AIPerf, RULER, scheduling, speculation, and agent suites enable thinking by default. `-NoThinking` selects an explicit comparison mode for those suites. The `recovery` and `mixed` suites always enable thinking; deterministic cache-only `restores` and `soak` checks retain their fixed non-thinking settings. Thinking is therefore not inferred merely from the server default.

The third-party suites use seed 42. vLLM uses fixed-length random prompts with 128 generated tokens and EOS ignored; generated output can consist entirely of reasoning. AIPerf uses 16 independent sessions with four key-retrieval turns each and a 1,024-token allowance; correctness scores final content, and its reported answer latency starts at the first final-content token. RULER uses the upstream `niah_single_1` and `vt` generators and unchanged `string_match_all` scoring, two samples per task and context budget, with 1,024 and 2,048 output tokens respectively. This is a small RULER subset, not its full 13-task score. The scheduler and short-generation probes measure first reasoning or content output, with total generation rates including both.

The agent probe uses temperature 0, unique cache salts per conversation, native GPU prefix reuse, and LMCache. It runs two sweeps without resetting OS/PLE caches. No cache-disabled control isolates LMCache's speedup. Repeated points help assess consistency but do not establish tail latency, overnight stability, or behavior at concurrency above four. More diverse task suites are needed before claiming general agent quality.
