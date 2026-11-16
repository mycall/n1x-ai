# Qwen38 profile comparison

Measurements: November 16, 2026 · RTX Spark N1X · 96 GiB dedicated GPU memory.

## Recommended profiles

| Priority | Profile | Reason |
| --- | --- | --- |
| Long-context throughput | `qwen38fn-w4-kv19` | 7.71-minute C4 workload; more GPU headroom than AZ; partial SSD restoration |
| Complete cacheable-prefix restoration | `qwen38fn-w4-kv19-4k` | Strict restart check passes; 9.09-minute C4 workload |
| Evaluate FP4-Local-AZ weights | `qwen38fn-az-kv19` | 7.61-minute C4 workload; no established advantage over W4 from one run |

**8K prefill batches favor measured throughput; 4K batches favor restart coverage.** Neither is a universal optimum. No further parameter change is supported by the current measurements for `qwen38fn-w4-kv19-4k`. DFlash2 K3 remains the validated depth for these profiles. The selected default remains `qwen38fn-best`.

## Configuration

All profiles below use DFlash2 K3, 262,144 maximum context, eight server slots, FP8 target KV, BF16 draft KV, 4,096-token cache blocks/chunks, prefix-match unit 64, RecoverSSM off, and LMCache RAM4/SSD160. Sizes are GiB.

| Profile | Target | SSM precision | KV pool | Prefill batch | PLE table |
| --- | --- | --- | ---: | ---: | --- |
| `qwen38fn-best` | W4 AutoRound | FP32 | 15 | 8,192 | External FP8 |
| `qwen38fn-w4-kv19` | W4 AutoRound | BF16 | 19 | 8,192 | External FP8 |
| `qwen38fn-w4-kv19-4k` | W4 AutoRound | BF16 | 19 | 4,096 | External FP8 |
| `qwen38fn-az-kv19` | FP4-Local-AZ | BF16 | 19 | 8,192 | Native FP4 from NVMe |
| `qwen38fn-az-dflash` | FP4-Local-AZ | FP32 | 15 | 8,192 | Native FP4 from NVMe |

AZ uses five routed experts and shared-expert width 1,280; W4 uses ten and 640. Both have the same chat template. The larger KV pool reports 924,785 tokens of capacity versus 730,605 for KV15. BF16 SSM pages require padding; changing SSM precision alone does not establish a doubling of capacity.

## Correctness and long-context performance

The short screen consists of eight 32K archive cases and 24 concurrent tool-recovery tasks. The long workload consists of four conversations starting at 250,002 tokens, with three tool tasks per conversation. All scored results are first attempts. All completed long runs recorded zero preemptions.

| Profile | Short correct | Long correct | Long elapsed | Throughput vs original | Follow-ups with cache hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original W4 / KV15 | 32/32 | 12/12 | 1,642.45 s / 27.37 min | 1.00× | 12/20 |
| W4 / KV19 / batch8K | 32/32 | 12/12 | 462.53 s / 7.71 min | 3.55× | 20/20 |
| W4 / KV19 / batch4K | 32/32 | 12/12 | 545.43 s / 9.09 min | 3.01× | 20/20 |
| AZ / KV19 / batch8K | 32/32 | 12/12 | 456.62 s / 7.61 min | 3.60× | 20/20 |
| AZ / KV15 / batch8K | 32/32 | Not tested | — | — | — |

Each cache-hit follow-up reused 249,856 tokens. W4 batch4K took 17.9% longer than W4 batch8K. AZ's 1.3% elapsed-time advantage over W4 at batch8K is too small to establish a model advantage from this single sequential comparison. BF16 SSM and KV size changed together relative to the original profile, so their individual contributions are not isolated.

## Restart restoration

Two independent 130,877-token prompts are saved to SSD, the server is restarted, and both prompts are resubmitted concurrently. Passing requires correct answers, SSD retrieval evidence, zero GPU-prefix hits, and combined missing coverage of less than one 4K chunk per prompt on average. The criterion is unchanged across configurations.

| Profile | Correct | Restored tokens per prompt | Complete chunks | Total prompt coverage | Pair elapsed | Strict check |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| W4 / KV19 / batch8K | 2/2 | 122,880 | 30/31 | 93.89% | 8.13 s | Fail |
| W4 / KV19 / batch4K | 2/2 | 126,976 | **31/31** | **97.02%** | **5.71 s** | **Pass** |
| AZ / KV19 / batch8K | 2/2 | 122,880 | 30/31 | 93.89% | 8.42 s | Fail |
| Original W4 / KV15 | Not tested in this campaign | — | — | — | — | Unmeasured |

All three measured restores recorded zero GPU-prefix hits, two completed external retrieves, SSD reads, and zero preemptions. The batch4K run recorded 253,952 external prefix-hit tokens and 66 SSD-prefetched chunks; both batch8K runs recorded 245,760 tokens and 64 chunks.

**100% complete-chunk restoration is not 100% prompt-token restoration.** There are 31 complete chunks plus a 3,901-token partial tail. This connector stores complete chunks, so that tail is recomputed.

In SSM `align` mode, recurrent-state checkpoints are captured at scheduler-step boundaries; skipped intermediate blocks can be null. Restoring requires a compatible recurrent-state endpoint as well as the attention cache. Changing only the prefill batch from 8K to 4K recovered the predicted missing checkpoint. The installed implementation is documented in `validate_mamba_step_alignment`, `MambaManager.allocate_new_blocks`, and LMCache's `GetStoreMetadata`.

## Short-request speed

Cells are **input / output tokens per second**, weighted per-request phase rates across two repetitions. C2 rates are per request, not aggregate throughput. Each configuration completed all 12 speed requests with a fixed 512-token output budget.

| Input / clients | Original W4 | W4 KV19 / batch8K | W4 KV19 / batch4K | AZ KV19 / batch8K |
| --- | ---: | ---: | ---: | ---: |
| 4K / C1 | 2,336.88 / 48.56 | 2,478.93 / 52.10 | 2,324.74 / 49.97 | 1,355.15 / 45.20 |
| 32K / C1 | 2,688.38 / 47.60 | 2,611.27 / 49.73 | 2,478.66 / 48.33 | 2,662.34 / 48.14 |
| 4K / C2 | 2,264.82 / 36.01 | 2,210.83 / 38.00 | 2,155.55 / 37.56 | 1,265.30 / 37.66 |
| 32K / C2 | 2,022.83 / 28.96 | 2,004.05 / 28.90 | 2,090.56 / 26.88 | 1,955.32 / 29.91 |

Warmup covers a short arithmetic request, not every prefill shape. First-use kernel compilation affected some AZ samples; its 4K figures do not establish an intrinsic steady-state penalty. The receipt retains all samples and consistently reports second-repetition rates separately. The baseline above is the quiet control, without download/hash overlap.

## Memory

Minimum sampled headroom through the speed, correctness, and long-context tests, before restart:

| Profile | Free dedicated GPU memory |
| --- | ---: |
| Original W4 / KV15 | Approximately 7.8 GiB |
| W4 / KV19 / batch8K | 4,050 MiB |
| W4 / KV19 / batch4K | 5,169 MiB |
| AZ / KV19 / batch8K | 2,823 MiB |

**Keep the 96 GiB dedicated allocation.** No tested recommendation requires more. Task Manager's shared-memory allowance is not additional dedicated GPU capacity. Resource figures use the active trial's telemetry; the near-full probe's embedded original-container host-memory field is stale for these isolated runs and is excluded.

## DFlash2 K5 and other settings

| Option | Evidence | Recommendation |
| --- | --- | --- |
| DFlash2 K3 | Current profiles pass short and near-full correctness; batch4K passes strict restart | Keep for these profiles |
| DFlash2 K5 | Historical November 8 test: 32/32 short tasks; warmed decode change vs K3 ranged from −2.5% to +4.6%; mixed winners | No established speed gain; untested on current KV19/BF16 profiles |
| DFlash2 K7 | Historical short correctness passed; slower at most warmed decode points | No measured reason to adopt |
| AZ with MTP, dynamic depth up to 12 | 32/32 short tasks; 43.53 s tool recovery; no near-full or restart qualification | Experimental alternative, not a qualified replacement |
| NVFP4 draft head | Active in the MTP trial; DFlash loader does not apply `MBX_DRAFT_HEAD` | Do not expect the flag to optimize DFlash2 |

The [historical depth comparison](DFlash-depth-trial.md) used 88 GiB, KV11, FP32 SSM, driver 621.14, and a patched candidate image. K5 required a QSA ring-size fix in that trial. The current pinned image already carries the `n1x-ai.qsa-ring=power-of-two-v1` marker, so that compatibility fix is present; K5 performance, capacity, and restoration still need qualification on the current profiles. K5 also reduced reported KV capacity from 533,997 to 497,169 tokens at the same 11 GiB pool. These historical results do not establish performance or restoration on the current profiles.

The AZ/MTP trial used BF16 KV15, RecoverSSM on, and LMCache off. Its 32K input/output rates were 2,619.58/48.26 at C1 and 2,378.32/27.34 at C2. The successful configuration disables expandable segments and uses an explicit KV budget with `gpu-memory-utilization: 0.01`. The upstream 0.88 availability check and expandable-segment configuration did not start successfully on this setup. Failed and interrupted attempts remain in the evidence receipt.

## Reproducibility and scope

| Item | Value |
| --- | --- |
| Runtime image | `sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc` |
| Driver | 621.24 |
| Recipe | [Pinned upstream revision](https://github.com/myllmbox/qwen38-flash-next-recipe/tree/1668358481edb7c07e06be39c7416920d687b467) |
| AZ weights | [Pinned model revision](https://huggingface.co/azampatti/Qwen3.8-Flash-Next-FP4-Local-AZ/tree/5d927eabd4e4766a69bf12f7a1387b01d936a78f) |
| AZ local directory | `~/Models/Qwen3.8-Flash-Next-FP4-Local-AZ` |
| AZ verification | 21 shards; 102,445,620,044 bytes; all SHA256 hashes match the pinned LFS manifest |
| Quality output allowance | 8,192 tokens including thinking |
| Compact evidence | [Settings, results, and hashes](data/recipe-mix-20261116.json) |
| Raw evidence | `results/benchmarks/recipe-mix-20261116/` |

These are bounded archive and tool workloads, not general coding or vision qualification. One sequential comparison does not establish a universal optimum. K5 on current profiles, AZ with batch4K, and a broader parameter sweep are unmeasured. Local checks passed; the trial server is stopped and the original default remains unchanged.

## Launch

Run only one inference container at a time. Each candidate has a separate LMCache namespace and volume. To use the restore-qualified profile:

```powershell
.\n1x.ps1 setup -Profile qwen38fn-w4-kv19-4k
.\n1x.ps1 start -Profile qwen38fn-w4-kv19-4k
.\n1x.ps1 wait -Profile qwen38fn-w4-kv19-4k
```

Use `qwen38fn-w4-kv19` for the tested 8K-batch throughput option. The API model name remains `qwen/qwen38fn-best`; the selected profile identifies the actual configuration.
