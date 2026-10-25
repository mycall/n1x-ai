# Benchmarks

The benchmark reference is **DFlash2 with thinking enabled**, using the `cache-dflash` profile. The primary measure is correct work per second in warm, multi-turn agent conversations. Token generation alone is not a correctness measure.

## Test configuration

MSI Prestige N16 Flip AI+, NVIDIA RTX Spark N1X, 128 GiB system memory, and an 88 GiB GPU partition. External power was connected and Windows reported Balanced. MSI Performance/Boost was not independently reconfirmed for these runs.

- Qwen3.8 Flash Next W4A16 AutoRound hybrid, revision `8b82f0b7abe3d1150a7827d298c75e86267636ae`.
- DFlash2 drafter, revision `a22a1744e85c17364dcc54a6a420af7135d4c7f6`, with three draft tokens.
- 262,144-token context limit, four sequence slots, and 4,096 scheduled tokens per step.
- 8 GiB GPU KV pool, FP8 KV/indexer, BF16 sliding-attention KV, and 1,664-token blocks/chunks.
- Native PLE, 8 GiB LMCache host pool, and a shared 16 GiB SSD cache budget.
- vLLM 0.32.0, LMCache 0.5.6, and PyTorch 2.13.0+cu130.

Thinking is enabled. Agent tests allow 1,024 output tokens per request, including reasoning, and preserve tool-call reasoning for the tool-result continuation. Other suites use the budgets described below. A separate client container shares the server network namespace without loading another model.

## Agent and restore qualification

### Warm-agent throughput

Each concurrency point warms four independent conversations, then measures three inventory-tool tasks per conversation. The sweep runs at concurrency 1, 2, and 4, then repeats in reverse order. Histories grow within each conversation.

A correct task requires the exact tool name and SKU, a matching tool-call/result ID, and the exact session-code/inventory answer with normal completion. Rates include time spent on every timed attempt and exclude initial conversation warmup.

| Concurrency | Correct tasks | Correct tasks/s |
| ---: | ---: | ---: |
| 1 | 24/24 | 0.453 |
| 2 | 24/24 | 0.622 |
| 4 | 24/24 | **0.811** |

**72/72 tasks pass, with no truncations or preemptions.** Concurrency 4 gives the highest measured throughput for this workload. The full run takes 234.9 seconds including warmups. The API remains healthy and SSD cache usage finishes at 15.98 GiB.

This qualifies the synthetic inventory workflow, not general coding-agent reliability, maximum-context agent work, or arbitrary tool schemas. Validate application-specific tasks before relying on the profile.

### Tool recovery

The thinking-enabled `recovery` suite runs four concurrent conversations with six tasks each, selecting between inventory and price tools. Temporary failures require one retry; canonical-SKU responses require correcting the next call's argument. The harness validates tool names, exact arguments, matching result IDs, and final values.

| Scenario | Correct tasks |
| --- | ---: |
| Normal tool selection | 8/8 |
| Retry after temporary tool error | 8/8 |
| Correct SKU from tool response | 8/8 |

All **24/24 tasks pass** in 31.54 seconds, including 40 valid tool calls, with no truncations or preemptions. Thinking uses a 1,024-token output allowance. This checks service-directed argument correction, not arbitrary malformed JSON repair or recovery from every tool failure. These short synthetic conversations are separate from the warm-agent throughput table.

### Concurrent mixed workload

The thinking-enabled `mixed` suite runs 12 cycles, each submitting four tasks together: an archive lookup, an image-shape question, arithmetic, and an inventory-tool round trip. Fresh archives alternate between 64,917 and 130,917 input tokens. Two additional requests revisit earlier archives. Every request allows 1,024 output tokens including reasoning.

**50/50 checks pass over 501.2 seconds (8.35 minutes)**, with no truncations or preemptions. Five-second Windows headroom samples range from 6.51 to 7.08 GiB; SSD cache usage finishes at 15.81 GiB and the API remains healthy. External-cache hit tokens and completed GPU restores are both zero, so this run does not duplicate the separate SSD-restore qualification.

This establishes a bounded mixed-workload check at concurrency four. It does not establish overnight stability, four simultaneous long archives, or combined near-262K vision/agent sessions. Client submission overlaps; individual task execution and transfers may serialize.

## Serving throughput

vLLM's serving benchmark uses 16 requests per point, thinking enabled, and 128 generated tokens with EOS ignored. Rates include prefill and reasoning output; these fixed-length requests do not measure answer correctness. Mean request latency excludes waiting in the client's concurrency queue.

| Input target | Concurrency | Generated tokens/s | Mean first token (s) | Mean completion (s) |
| --- | ---: | ---: | ---: | ---: |
| 4K | 1 | 19.3 | 2.29 | 6.62 |
| 4K | 2 | 24.8 | 2.88 | 10.34 |
| 4K | 4 | 29.2 | 3.55 | 17.19 |
| 16K | 1 | 11.1 | 7.43 | 11.58 |
| 16K | 2 | 12.8 | 9.75 | 19.92 |
| 16K | 4 | 13.8 | 10.02 | 36.65 |

All **96/96 requests complete**. Concurrency improves aggregate throughput while increasing per-request latency. The warm-agent table measures a different workload and should guide correct-work throughput decisions.

## Multi-turn retrieval accuracy

AIPerf runs 16 independent sessions with four key-retrieval turns each, roughly 16K initial context, thinking enabled, and a 1,024-token output allowance. Rates include initial loading and follow-up turns. Answer TTFT measures the first final-content token, after any reasoning; empty answers are excluded from that latency average but counted as failures.

| Concurrency | Correct turns | Correct turns/s | Initial answer TTFT (s) | Follow-up answer TTFT (s) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 63/64 | 0.344 | 7.28 | 1.28 |
| 2 | 63/64 | 0.422 | 11.58 | 2.17 |
| 4 | 64/64 | 0.482 | 17.26 | 4.77 |

**190/192 turns are correct.** Two responses finish with `stop` but contain no final answer. They are not timeouts or output-limit truncations. The tool-task passes therefore do not establish perfect multi-turn retrieval reliability; harnesses must validate final content.

After a service restart, isolated streaming replays of both captured requests succeed with their original cache salts and with fresh salts: 4/4 correct answers. These diagnostics do not change the 190/192 score, isolate the cause, or guarantee retry success under the original workload. Preserve completed tool results when retrying generation and surface persistent failures.

## Long-context accuracy

The thinking-enabled RULER subset uses two samples per task and context budget. Scores use the upstream reference-string metric; variable-tracking samples each contain five reference variables.

| Context budget | Needle input tokens | Needle score | Variable-tracking input tokens | Variable-tracking score |
| ---: | ---: | ---: | ---: | ---: |
| 16,384 | 14,520-14,524 | 100% | 14,171-14,172 | 100% |
| 65,536 | 64,270 | 100% | 63,098-63,347 | 100% |
| 131,072 | 129,820 | 100% | 128,868-128,872 | 100% |
| 262,144 | 260,895 | 100% | 259,947-259,950 | 100% |

All **16/16 samples complete without truncation**. Input leaves room for reasoning and final output; the context budget is not the input-token count. This sequential two-task subset does not establish full RULER performance or general long-document agent quality.

## Generation overlap and decode rates

The scheduling probe submits four independent requests together, with 256 generated tokens each and EOS ignored. It observes four running requests and four overlapping generation intervals, with zero preemptions: **55.2 aggregate generated tokens/s**, 5.42 s mean first-token latency, and 18.13 s mean completion time. Intervals begin at the first reasoning or content token; this is not a correctness score.

The short-generation probe runs each prompt twice at concurrency one with a shared per-task cache salt. The mean streamed decode-rate estimate excludes initial prefill and includes reasoning tokens, using `(completion_tokens - 1) / (completion time - first generated-token time)`.

| Task | Mean generated tokens/s | Outcome |
| --- | ---: | --- |
| JSON | 78.1 | Both answers exact; normal completion |
| Python LRU-cache example | 61.1 | Both hit the 2,048-token cap; no code-quality score |
| B-tree explanation | 63.4 | Both hit the 2,048-token cap; no quality score |

Reasoning consumes the shared output budget. These capped code and explanation samples do not establish complete-answer throughput; application prompts may need larger budgets.

## DFlash2 comparison

Both profiles below use thinking, the same inventory tasks and scoring, a 1,024-token output allowance, and the bounded 16 GiB SSD adapter.

| Concurrency | DFlash2 correct tasks/s | MTP correct tasks/s | DFlash2 / MTP |
| ---: | ---: | ---: | ---: |
| 1 | 0.453 | 0.219 | 2.07x |
| 2 | 0.622 | 0.266 | 2.34x |
| 4 | 0.811 | 0.300 | 2.70x |

Both pass 72/72 tasks. MTP uses one draft token, 16 sequence slots, and 2,048-token cache blocks/chunks; both profiles have an 8 GiB KV pool. These are complete-profile measurements, not an isolated comparison of speculative algorithms. Power settings were not independently controlled between runs. MTP's full run takes 400.5 seconds including warmups.

Thinking-disabled checks reproduce skipped tool calls with DFlash2, MTP, and target-only decoding. Thinking, output allowance, and reasoning-history handling change together in the successful agent configuration; the evidence does not establish quantization as the cause of those failures.

## Feature and cache validation

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

## SSD budget validation

The 16 GiB cap applies across project namespaces. Entries compete for space and eviction can force recomputation; stored file sizes depend on the profile and coverage.

The bounded MTP adapter verifies a 130,877-token SSD restore after engine restart: 126,976 external-cache hit tokens, one completed GPU restore, 63 SSD-prefetched chunks, zero native prefix hits, and zero preemptions. A partially evicted 260,877-token MTP request recomputes correctly without a restore.

For the measured MTP working set, the 262K and 131K entries occupy 6.97 and 3.44 GiB. Replaying file sizes and access order through the eviction policy retains both at 16 GiB; at 8 GiB it retains 124/190 files from the longer entry and all 94 files from the shorter entry. This is a storage-policy replay, not a GPU restore benchmark at both budgets, and does not guarantee retention under additional traffic. DFlash2's measured 262K entry is larger; do not apply MTP sizing to it.

## Run

Start the reference profile, then run its thinking-enabled agent benchmark:

```powershell
# Stop any other model profile using the API port first.
.\n1x.ps1 start -Profile cache-dflash
.\n1x.ps1 wait -Profile cache-dflash -TimeoutSeconds 1800
.\benchmark.ps1 -Build -Suite agents

# vLLM serving, AIPerf multi-turn retrieval, and the RULER subset.
.\benchmark.ps1 -Suite all

# Thinking-enabled tool selection, retries, and argument repair.
.\benchmark.ps1 -Suite recovery -Profile cache-dflash

# Thinking-enabled long retrieval, vision, arithmetic, and tools together.
.\benchmark.ps1 -Suite mixed -Profile cache-dflash

# Seeds two 131K entries, restarts the service, then verifies SSD restores.
.\test-restores.ps1 -Profile cache-dflash
```

Supply `-PowerMode` with the actual MSI setting to record it; the option does not change system settings. Avoid other model requests during measurements. The fixed agent workload does not accept `-Smoke`.

Raw responses, commands, configuration, package versions, scores, and cache counters remain in ignored `results/benchmarks/`. Failed runs retain their artifacts. The benchmark client is removed automatically; the model service remains running.

## Coverage and limits

The serving, AIPerf, RULER, scheduling, speculation, and agent suites enable thinking by default. `-NoThinking` selects an explicit comparison mode for those suites. The `recovery` and `mixed` suites always enable thinking; deterministic cache-only `restores` and `soak` checks retain their fixed non-thinking settings. Thinking is therefore not inferred merely from the server default.

The third-party suites use seed 42. vLLM uses fixed-length random prompts with 128 generated tokens and EOS ignored; generated output can consist entirely of reasoning. AIPerf uses 16 independent sessions with four key-retrieval turns each and a 1,024-token allowance; correctness scores final content, and its reported answer latency starts at the first final-content token. RULER uses the upstream `niah_single_1` and `vt` generators and unchanged `string_match_all` scoring, two samples per task and context budget, with 1,024 and 2,048 output tokens respectively. This is a small RULER subset, not its full 13-task score. The scheduler and short-generation probes measure first reasoning or content output, with total generation rates including both.

The agent probe uses temperature 0, unique cache salts per conversation, native GPU prefix reuse, and LMCache. It runs two sweeps without resetting OS/PLE caches. No cache-disabled control isolates LMCache's speedup. Repeated points help assess consistency but do not establish tail latency, overnight stability, or behavior at concurrency above four. More diverse task suites are needed before claiming general agent quality.
