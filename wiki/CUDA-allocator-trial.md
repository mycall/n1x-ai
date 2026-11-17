# CUDA expandable-segments trial

**Keep the allocator setting off for the selected LMCache runtime.** On November 15, 2026, adding only `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` caused vLLM to reject the configuration before model loading or API readiness. No candidate speed, answer-quality, or service restart/restore results exist. The unchanged control completed its speed and tool workloads. [Measurements and evidence hashes](data/allocator-trial-20261115.json).

## Compatibility finding

The pinned image's `VllmConfig._verify_kv_transfer_compat` rejects expandable segments whenever a KV connector is configured, unless `enable_cumem_allocator` is also enabled. Our connector is `LMCacheMPConnector`. The guard protects memory registrations from physical-page remapping; it conservatively covers all connectors. This rejection is not evidence that this project's custom allocator actually corrupted memory.

The supported upstream exception uses `CuMemAllocator`, which temporarily disables expandable segments inside its memory pools. This project instead patches KV allocation to use `n1x_vmm.zeros` and segmented FD-exportable storage. Enabling CuMem would require reviewing those allocation/IPC paths together and qualifying the resulting runtime. The guard was not bypassed, and CuMem was not enabled during this trial.

A preliminary standalone GPU cache test with expandable segments passed two byte-exact restores, including admission after the first restore released host space. That test used a 248.625 MiB GPU pool and a 64 MiB host pool; it did not construct vLLM's serving configuration and therefore did not catch the startup guard.

## Control configuration and workload

The control used the selected 96 GiB partition, W4A16 AutoRound target, DFlash2 K3, FP32 SSM, BF16 indexer, batch8K, FP8 KV15 GiB, eight slots, and LMCache RAM4/SSD160. Image ID: `sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc`.

Both sides used a separate trial container and initially empty SSD volumes with identical budgets. Container inspection confirmed identical image identities and semantically identical serving arguments; the only environment difference was the requested allocator variable. Existing model assets and runtime compilation caches were reused. The original configuration was restored, and serving ended stopped, matching the initial state.

The speed suite used `n1x-speed-v1`, thinking/xhigh, seed 42, cold prompts, exactly 512 generated tokens with EOS ignored, C1/C2, and two passes with reversed grid order. All **24/24 requests** were valid and reported zero cache hits. These are weighted per-request phase rates, not aggregate throughput or answer-quality scores.

| Input target | C1 (read, write), tokens/s | C2 (read, write), tokens/s |
| ---: | ---: | ---: |
| 4,096 | (2,573.68, 48.49) | (1,861.13, 36.03) |
| 32,768 | (2,980.30, 48.20) | (2,215.03, 28.50) |
| 131,072 | (2,913.87, 44.56) | (2,294.44, 11.92) |
| 253,944 | (2,857.69, 44.55) | (2,150.64, 7.32) |

Actual inputs were 4,090, 32,760, 131,080 and 253,945 tokens. Read uses summed input tokens divided by summed server prefill duration; write uses summed `(completion_tokens - 1)` divided by summed server decode duration. Concurrent decode intervals include stalls while other requests prefill.

The existing near-full tool probe used four independent 250,002-token histories, three inventory/price round trips per history, thinking/xhigh, and an 8,192-token output allowance. One C2/C4 pass produced **24/24 correct first-attempt tasks**. It validates tool names, arguments, IDs and exact final answers; this is bounded synthetic correctness, not general agent accuracy.

| Client concurrency | Correct / planned | Batch seconds | Correct tasks/s | Preemptions |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 12/12 | 504.85 | 0.02377 | 0 |
| 4 | 12/12 | 1,204.78 | 0.00996 | 3 |

C4 included full-history recomputation on some continuations. Correct answers do not establish successful restoration for every request. The receipt retains cache-counter deltas and per-phase coverage. Continuous tool-phase samples recorded 4.97–8.60 GiB free Windows memory and 90,860–91,565 MiB GPU usage. The tool harness's fixed default-container memory path was stale for the isolated container; the receipt uses the separate trial-container memory log instead. Speed-phase host-memory sampling started late and is not full-run coverage.

## Relationship to earlier evidence

The [96 GiB campaign](96GiB-comparison-campaign.md) recorded 24/24 tasks at each concurrency over two passes, versus 12/12 here over one pass. The new control's correct-task rate is about 3.6% higher at C2 and 3.1% higher at C4. Different dates, run order, cache behavior and operating conditions prevent treating those small differences as a controlled improvement. They provide a useful contemporary baseline; they say nothing about the rejected allocator candidate.

The 4K/32K fixed-512 speed points overlap the [DFlash depth trial](DFlash-depth-trial.md), but that trial used 88 GiB/KV11. The near-full point overlaps the context range of the [prefill comparison](Benchmarks.md#matched-prefill-comparison), whose variable-length completed tasks are a different workload. The historical `vllm bench serve` matrix also uses a different benchmark protocol. Do not pool these samples or infer missing cells.

## Retained artifacts

- Control: `results/benchmarks/allocator-comparison-v2-20261115/`.
- Rejected candidate and inspected vendor source: `results/benchmarks/allocator-candidate-20261115/`.
- Preliminary GPU test and receipt generator: `results/benchmarks/allocator-20261115/`.

The initial startup was cancelled before inference when the comparison set was expanded. A setup retry encountered an already-existing trial volume before inference. The completed control controller was deliberately stopped after both measured suites to switch to a fresh candidate volume; its generic `failed/STOP` status is an orchestration outcome, not a failed benchmark. Raw first attempts and these events remain retained. The candidate's startup rejection is the actual compatibility result. The trial container and both generated SSD cache volumes were removed afterward; the original container, model assets and cache volumes were retained.
