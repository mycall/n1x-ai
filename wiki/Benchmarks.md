# Benchmarks

These benchmarks exercise the running OpenAI-compatible API. A separate WSLC client container shares the server's network namespace; it does not load another model or publish ports.

## Test configuration

Reference system: MSI Prestige N16 Flip AI+ with NVIDIA RTX Spark N1X, 128 GiB system memory, and an 88 GiB GPU partition. Power settings: MSI **Performance mode + Boost**, Windows Balanced scheme, external power connected at the power-source check.

**Qwen3.8 Flash Next W4A16 AutoRound hybrid**, model revision `8b82f0b7abe3d1150a7827d298c75e86267636ae`. The `cache-mtp` profile used:

- 262,144-token maximum context, 16 sequence slots, **4,096 scheduled tokens per step**.
- One MTP draft token with Triton, FP8 KV, an 8 GiB GPU KV pool, native PLE.
- An 8 GiB LMCache L1 pool and SSD L2; 512 MiB physical VMM allocation segments.
- vLLM 0.32.0, LMCache 0.5.6, PyTorch 2.13.0+cu130.

The main benchmark tables use this configuration; the DFlash2 comparison specifies its separate profile. Results are single trials; small differences require repeated measurements.

## Serving throughput

Each row contains 16 measured requests with 128 output tokens each. Actual prompts were 4,108-4,110 or 16,396-16,398 tokens after chat wrapping. Output throughput includes prefill. Request latency excludes waiting in the client's concurrency queue.

| Input target | Concurrency | Output tokens/s | Mean first token (s) | Mean completion (s) |
| --- | ---: | ---: | ---: | ---: |
| 4K | 1 | 22.9 | 2.11 | 5.58 |
| 4K | 2 | 29.6 | 2.95 | 8.63 |
| 4K | 4 | 34.4 | 4.56 | 14.84 |
| 4K | 8 | 47.5 | 6.40 | 21.29 |
| 4K | 16 | 56.4 | 13.77 | 34.82 |
| 16K | 1 | 11.9 | 7.28 | 10.78 |
| 16K | 2 | 13.0 | 9.35 | 19.60 |
| 16K | 4 | 14.0 | 13.65 | 36.38 |
| 16K | 8 | 14.7 | 23.70 | 68.61 |
| 16K | 16 | 14.9 | 66.72 | 124.52 |

**160/160 requests completed.** Concurrency improves 4K throughput. At 16K, throughput levels off around concurrency 8 while latency continues rising.

## Multi-turn retrieval

Each row uses 16 independent sessions with four turns each, roughly 16K initial context, and a 32-token output cap with natural stopping. Correct-turn throughput includes all 16 initial turns and 48 follow-ups.

| Concurrency | Correct turns | Correct turns/s | Initial mean first token (s) | Follow-up mean first token (s) | LMCache restores |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 64/64 | 0.382 | 5.52 | 1.49 | 0 |
| 2 | 64/64 | 0.393 | 8.79 | 2.48 | 0 |
| 4 | 64/64 | 0.419 | 14.83 | 5.43 | 10 |
| 8 | 64/64 | 0.431 | 26.98 | 11.62 | 14 |
| 16 | 64/64 | 0.400 | 50.00 | 29.53 | 0 |

**320/320 answers correct.** Concurrency 8 offers the highest measured throughput, about 3% above concurrency 4 with over twice the follow-up latency. Use **1-2 for interactive latency**, **4 for a throughput/latency compromise**, or **8 for aggregate throughput**. Concurrency 16 offers no advantage for this workload.

Restore counts are completed CPU-to-GPU transfer counter deltas. Native GPU prefix reuse is enabled. A lookup hit or SSD prefetch does not prove a GPU restore: concurrency 16 records 84 SSD-prefetched chunks and 147,456 L2 lookup-hit tokens, but zero GPU restores.

## Long-context accuracy

RULER's reference-string metric, with two samples per task and context budget. Each variable-tracking sample contains five reference variables.

| Context budget | Needle input tokens | Needle score | Variable-tracking input tokens | Variable-tracking score |
| ---: | ---: | ---: | ---: | ---: |
| 16,384 | 15,980-15,984 | 100% | 15,682-15,684 | 100% |
| 65,536 | 64,530 | 100% | 64,833-64,837 | 100% |
| 131,072 | 130,680 | 100% | 130,353-130,357 | 100% |
| 262,144 | 261,755 | 100% | 261,432-261,435 | 100% |

**16/16 samples completed without truncation.** See [methodology and limits](#methodology-and-limits) for the scope of this RULER subset.

## Overlapping requests

The dedicated scheduling probe submits independent 4,190-4,191-token prompts together and generates 256 tokens per reply. It samples the scheduler every 100 ms and measures overlap from first content token to completion.

| Requests | Peak running | Peak overlapping replies | Output tokens/s | Mean first token (s) |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 4 | 4 | 56.0 | 4.30 |
| 8 | 8 | 8 | 74.3 | 7.51 |
| 16 | 16 | 16 | 88.5 | 13.72 |

All probes complete with zero observed preemptions. Overlap measures response intervals, not individual GPU kernels or answer correctness. Client concurrency limits outstanding requests; it does not guarantee that every request runs in each scheduler step. See [scheduling configuration](Configuration.md#scheduling) for the token budget.

## Feature and cache validation

| Check | Result |
| --- | --- |
| Smoke, streaming, JSON, tool round trips, reasoning, shapes, OCR | Pass |
| 260,877-token retrieval, cold and native GPU prefix reuse | Pass; native reuse accepts 12/12 MTP draft tokens |
| 260,877-token retrieval with SSD-backed restore | Pass; 258,048 external-cache hit tokens, one GPU restore, 127 SSD-prefetched chunks, zero native prefix-hit tokens, 12/12 MTP draft tokens accepted |

Vision and maximum context are separate checks. See [service validation](Development.md#service-validation) for commands.

## DFlash2 comparison

The optional `speculation` suite compares identical short prompts at concurrency 1, temperature 0, thinking disabled, and a 512-token output cap. Each task runs twice with a shared per-task cache salt. Values are the mean streamed decode-rate estimate, `(completion_tokens - 1) / (completion time - first content time)`, excluding initial prefill.

| Task | MTP, one draft token (tokens/s) | DFlash2, three draft tokens (tokens/s) |
| --- | ---: | ---: |
| JSON | 50.1 | 81.4 |
| Python code | 46.6 | 78.9 |
| Explanation | 41.6 | 49.9 |

MTP uses the reference `cache-mtp` profile. DFlash2 uses the [experimental 262K profile](Configuration.md#dflash2), with four sequence slots, an 8 GiB KV pool, 1,664-token blocks/chunks, and the compressed indexer in FP8. This compares complete profiles in separate runs, not the speculative algorithm in isolation. Both JSON answers per profile are exact. Code responses reach the output cap; their rates are not a code-correctness score. Explanation outputs have no automatic quality score. The prompts and timing implementation are in [speculation_probe.py](../benchmarks/speculation_probe.py).

The four-request scheduling probe reaches four running requests and four overlapping reply intervals, with 54.5 aggregate output tokens/s and 5.53 s mean first-token latency. This is not faster than the reference MTP four-request result of 56.0 tokens/s; single-request decode gains do not establish a concurrency-throughput advantage.

The [current DFlash2 layout](Configuration.md#dflash2) passes streaming, JSON, tool, reasoning, shapes, OCR, and a 260,877-token retrieval check. Vision and maximum context are separate checks. The GPU partition stays at 88 GiB and the KV pool at 8 GiB. Its reported capacity is 520,451 tokens at the 262,144 context setting; this estimate includes context-dependent hybrid-cache overhead and does not guarantee simultaneous maximum-length sessions.

| DFlash2 cache qualification | Result |
| --- | --- |
| Two independent 130,877-token requests submitted together | Both correct; peak two running requests, zero preemptions |
| Windows headroom during those concurrent requests | 7.58–7.89 GiB in five-second samples |
| 260,877-token retrieval after GPU-prefix eviction | Correct, normal completion; 259,584 external-cache hit tokens, one completed GPU restore, 159 SSD-prefetched chunks, zero native prefix-hit tokens |

These retrieval checks do not establish general long-document quality, simultaneous maximum-context vision, or four concurrent maximum-length sessions.

With the desired profile running:

```powershell
.\benchmark.ps1 -Build -Suite speculation -Profile cache-dflash
# Run separately, after switching the service back to MTP:
.\benchmark.ps1 -Suite speculation -Profile cache-mtp
```

## Run

Start the `cache-mtp` profile and wait for readiness. Then:

```powershell
# Build the client image and check all three tools with a small workload.
.\benchmark.ps1 -Build -Smoke -PowerMode 'Performance mode + Boost'

# Run all three suites against the existing service.
.\benchmark.ps1 -PowerMode 'Performance mode + Boost'

# Or run one suite.
.\benchmark.ps1 -Suite vllm
.\benchmark.ps1 -Suite aiperf
.\benchmark.ps1 -Suite ruler

# Verify overlapping generation separately.
foreach ($c in 4, 8, 16) {
    .\benchmark.ps1 -Suite scheduler -SchedulerConcurrency $c
}
```

Use `-Profile cache-mtp` if it is not your configured default. `-PowerMode` records a label; it does not change system settings. Avoid other model requests during measurements. The default RULER sweep requires the 262,144-token profile.

Raw output stays in ignored `results/benchmarks/`: commands, package versions, server configuration, responses, reports, and cache counters. Failed runs preserve their artifacts. The client is removed automatically; the model service remains running.

## Methodology and limits

All suites use seed 42 and disable thinking. AIPerf and RULER use temperature 0. Each serving or multi-turn point has a unique cache salt; caching within a point is enabled. Each RULER request has its own salt. Concurrency points run in ascending order without flushing OS/PLE page caches.

- [vLLM bench serve](https://docs.vllm.ai/en/latest/cli/bench/serve.html) uses random input, ignores EOS for fixed output lengths, and performs one warmup per point. It measures serving performance rather than answer quality.
- [AIPerf](https://github.com/ai-dynamo/aiperf) uses reference filler and session-specific lookup keys, appending turns to conversation history. Correctness requires an exact key and `finish_reason=stop`. Throughput spans the first request to the final response, including initial context ingestion but excluding client startup. This is a retrieval workload, not a coding-agent evaluation.
- [RULER](https://github.com/NVIDIA/RULER) uses the upstream `niah_single_1` and `vt` generators and unchanged `string_match_all` scoring. Output limits are 128 and 512 tokens respectively; variable tracking permits explanatory answers rather than upstream's 30-token allowance. Generation reserves the output limit plus 128 tokens for chat overhead, and rendered lengths are checked before submission. This sequential, repetitive-noise subset is **not the full 13-task RULER score** and does not establish general long-document quality or concurrent maximum-context capacity.

There is no cache-disabled control, so these results do not isolate LMCache's speedup over native prefix caching. Repeat measurements in varied order before relying on small differences or tail latency.

## Tool versions

The client uses vLLM from the project's pinned base, AIPerf 0.13.0 in a separate environment, and RULER revision `c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a`. The AIPerf local-directory tokenizer fix derives from upstream revision `15585512a97840d8bb38966121aaa96326b48711`; request generation and metrics are unchanged. Model/tokenizer files are mounted read-only. Each run captures installed dependency versions and server settings.
