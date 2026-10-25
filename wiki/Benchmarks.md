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

Thinking is enabled with a 1,024-token output allowance per request, including reasoning. The client preserves tool-call reasoning for the tool-result continuation. A separate client container shares the server network namespace without loading another model.

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

Total SSD cache usage remains 15.97 GiB after the restore. This establishes a near-262K DFlash2 SSD restore under the 16 GiB cap.

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
.\benchmark.ps1 -Build -Suite agents -Profile cache-dflash -AgentThinking
```

Supply `-PowerMode` with the actual MSI setting to record it; the option does not change system settings. Avoid other model requests during measurements. The fixed agent workload does not accept `-Smoke`.

Raw responses, commands, configuration, package versions, scores, and cache counters remain in ignored `results/benchmarks/`. Failed runs retain their artifacts. The benchmark client is removed automatically; the model service remains running.

## Coverage and limits

The vLLM, AIPerf, RULER, scheduling, speculation, restore, and soak suites remain available, but their current implementations explicitly disable thinking. Their results are not presented as measurements of this reference workload. `-AgentThinking` applies only to the inventory-agent suite; it does not change other suites.

The agent probe uses temperature 0, unique cache salts per conversation, native GPU prefix reuse, and LMCache. It runs two sweeps without resetting OS/PLE caches. No cache-disabled control isolates LMCache's speedup. Repeated points help assess consistency but do not establish tail latency, overnight stability, or behavior at concurrency above four. More diverse task suites are needed before claiming general agent quality.
