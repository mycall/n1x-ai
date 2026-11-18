# W4 and FP4-Local-AZ performance on 96 GiB

Across three paired runs with W4, five draft tokens, and a 20 GiB KV pool, the 8K prefill batch finished the near-full C4 workload 5.3% sooner on average. The 4K batch restored all complete chunks after restart and had more GPU headroom. The short screens do not establish a quality ranking. [Choose a serving profile](Profile-review.md)

Measurements were collected November 16–17, 2026 on an RTX Spark N1X with a 96 GiB GPU partition.

## Three-run KV20/K5 averages

Each configuration ran three times on November 17. Pair order was 4K/8K, 8K/4K, then 4K/8K; short-screen seeds were 45, 46, and 47, matched within each pair. Every trial used a fresh cache namespace and included 12 speed requests, 32 short correctness tasks, four simultaneous 250,002-token conversations with 12 tool tasks, and a two-prompt SSD restore after restart. All settings except batch size were held fixed. Startup time is excluded.

These are arithmetic means of the three paired runs; earlier exploratory runs are excluded from the primary averages. Failed first-attempt scores remain recorded, and completed performance measurements are included even when another check fails. The ± values are sample standard deviations, not confidence intervals.

| Measurement | KV20 / batch4K | KV20 / batch8K |
| --- | --- | --- |
| Long workload, mean ± SD | 406.03 ± 1.45 s | 384.60 ± 0.74 s |
| Long workload, median | 406.60 s | 384.55 s |
| Long workload, range | 404.39–407.11 s | 383.90–385.37 s |
| Short correctness | 95/96 | 96/96 |
| Long correctness | 36/36 | 36/36 |
| Follow-up cache hits | 60/60 | 60/60 |
| Restore pair, mean ± SD | 5.37 ± 0.04 s | 7.57 ± 0.03 s |
| Restore answers correct | 6/6 | 6/6 |
| Strict restore checks passed | 3/3 | 0/3 |
| Restored complete chunks per prompt | 31/31 (100%) | 30/31 (96.77%) |
| Total prompt-token coverage | 97.02% | 93.89% |
| Minimum sampled GPU headroom | 3,482 MiB | 1,986 MiB |

| Pair / order | 4K elapsed | 8K elapsed | 8K elapsed reduction |
| --- | --- | --- | --- |
| 1 / 4K → 8K | 404.39 s | 384.55 s | 4.91% |
| 2 / 8K → 4K | 407.11 s | 383.90 s | 5.70% |
| 3 / 4K → 8K | 406.60 s | 385.37 s | 5.22% |

All six long runs recorded zero preemptions. Every hit reused 249,856 tokens. The 4K seed-46 short failure was a premature final answer before a required canonical-SKU tool retry; it was neither a transport failure nor output-budget exhaustion. It remains in the score. Including the earlier seed-42/43/44 screens gives 191/192 for 4K and 190/192 for 8K, illustrating why isolated failures should not determine the parameter choice.

### Mean short-request speed

Cells are mean input/output tokens per second across the three paired runs. Each run first aggregates its two repetitions by phase time; C2 rates remain per request. Both configurations completed all 36 speed requests. The receipt includes per-run rates, ranges, standard deviations, and second-repetition evidence.

| Input / clients | KV20 / batch4K | KV20 / batch8K |
| --- | --- | --- |
| 4K / C1 | 2,761.32 / 47.63 | 2,772.72 / 49.79 |
| 32K / C1 | 2,896.21 / 47.36 | 3,035.75 / 48.05 |
| 4K / C2 | 2,405.36 / 35.56 | 2,572.80 / 36.18 |
| 32K / C2 | 2,523.79 / 27.26 | 2,283.29 / 28.50 |

8K had higher mean decode rates at all four measured points. Its C2/32K prefill rate was lower, so the long-workload advantage is not a universal win at every phase. Three paired runs support this bounded throughput choice; they do not establish broad model-quality superiority.

[Paired-run settings, scores, statistics, and hashes](data/k5-batch-repeats-20261117.json). Reproduce with `python benchmarks/recipe_repeats.py --directory results/benchmarks/recipe-mix-20261116 --out wiki/data/k5-batch-repeats-20261117.json`; an existing completed campaign is summarized without rerunning it. Use a new `--tag` and output path for an independent campaign. Disposable caches are removed after each stopped trial; raw evidence is retained.

## Configuration

All profiles below use DFlash2 (K3 unless the profile name specifies K5), 262,144 maximum context, eight server slots, FP8 target KV, BF16 draft KV, 4,096-token cache blocks/chunks, prefix-match unit 64, RecoverSSM off, and LMCache RAM4/SSD160. Sizes are GiB.

| Profile | Target | SSM precision | KV pool | Prefill batch | PLE table |
| --- | --- | --- | ---: | ---: | --- |
| `qwen38fn-best` | W4 AutoRound | FP32 | 15 | 8,192 | External FP8 |
| `qwen38fn-w4-kv19` | W4 AutoRound | BF16 | 19 | 8,192 | External FP8 |
| `qwen38fn-w4-kv19-4k` | W4 AutoRound | BF16 | 19 | 4,096 | External FP8 |
| `qwen38fn-w4-kv20-4k-k5` | W4 AutoRound | BF16 | 20 | 4,096 | External FP8 |
| `qwen38fn-w4-kv20-8k-k5` | W4 AutoRound | BF16 | 20 | 8,192 | External FP8 |
| `qwen38fn-az-kv19` | FP4-Local-AZ | BF16 | 19 | 8,192 | Native FP4 from NVMe |
| `qwen38fn-az-dflash` | FP4-Local-AZ | FP32 | 15 | 8,192 | Native FP4 from NVMe |

AZ uses five routed experts and shared-expert width 1,280; W4 uses ten and 640. Both have the same chat template. KV19 reports 924,785 tokens of capacity and KV20 reports 973,330, versus 730,605 for KV15. BF16 SSM pages require padding; changing SSM precision alone does not establish a doubling of capacity.

## K3 and AZ tool correctness

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

The three K3/AZ restores above recorded zero GPU-prefix hits, two completed external retrieves, SSD reads, and zero preemptions. The batch4K run recorded 253,952 external prefix-hit tokens and 66 SSD-prefetched chunks; both batch8K runs recorded 245,760 tokens and 64 chunks.

**100% complete-chunk restoration is not 100% prompt-token restoration.** There are 31 complete chunks plus a 3,901-token partial tail. This connector stores complete chunks, so that tail is recomputed.

In SSM `align` mode, recurrent-state checkpoints are captured at scheduler-step boundaries; skipped intermediate blocks can be null. Restoring requires a compatible recurrent-state endpoint as well as the attention cache. Changing only the prefill batch from 8K to 4K recovered the predicted missing checkpoint. The installed implementation is documented in `validate_mamba_step_alignment`, `MambaManager.allocate_new_blocks`, and LMCache's `GetStoreMetadata`.

## K3 and AZ short-request speed

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

## Exploratory depth and KV comparisons

These are sequential exploratory runs, separate from the new paired averages. K3 and K5 below both use W4, BF16 SSM, KV19, and batch4K with fresh cache namespaces. Each completed 12/12 speed requests and 44/44 short-plus-long tasks.

| Measurement | K3 rematch | K5 |
| --- | --- | --- |
| Near-full C4 elapsed | 507.33 s | 592.68 s |
| Follow-ups with cache hits | 20/20 | 19/20 |
| Preemptions | 0 | 0 |
| Reported KV capacity | 924,785 tokens | 924,785 tokens |
| Minimum GPU headroom, complete run | 4,917 MiB | 5,232 MiB |
| Strict restart | Pass in earlier run; not repeated in rematch | Pass |
| Restart pair | 5.71 s in earlier run | 5.84 s |

K5 took 16.8% longer than the K3 rematch at KV19/batch4K despite higher measured prefill rates and mixed decode results. Both measured restart tests recovered all 31 complete chunks. K5 did not reduce reported KV capacity in this BF16 layout, unlike the historical FP32/KV11 trial. Retain K3 for the existing `qwen38fn-w4-kv19-4k` profile; the measured K5 improvement uses KV20.

| Input / clients | K3 rematch input/output tok/s | K5 input/output tok/s |
| --- | --- | --- |
| 4K / C1 | 2,370.02 / 49.03 | 2,726.94 / 50.23 |
| 32K / C1 | 2,348.92 / 51.17 | 2,913.91 / 47.30 |
| 4K / C2 | 2,187.18 / 35.63 | 2,246.35 / 35.44 |
| 32K / C2 | 2,023.46 / 27.00 | 2,510.46 / 27.86 |

| K5 setting | Short correct | Near-full C4 | Follow-up hits | Strict restart | Minimum GPU headroom |
| --- | --- | --- | --- | --- | --- |
| KV19 / batch4K | 32/32 | 592.68 s; 12/12 correct | 19/20 | Pass, 5.84 s | 5,232 MiB |
| KV20 / batch4K | 96/96 across seeds 42–44 | 406.57 s; 12/12 correct | 20/20 | Pass, 5.41 s | 3,538 MiB |
| KV19 / batch8K | 32/32 on separate retry | 632.63 s; 12/12 correct | 17/20 | Fail, 7.66 s; 30/31 chunks | 3,200 MiB |
| KV20 / batch8K | 94/96 across seeds 42–44 | 383.26 s; 12/12 correct | 20/20 | Fail, 7.48 s; 30/31 chunks | 1,909 MiB |

KV20 gives 3.71 times the 262,144-token context limit in reported KV capacity, versus 3.53 times for KV19. The exploratory KV20/batch4K run finished 31.4% sooner than K5 KV19/batch4K and 19.9% sooner than the K3 rematch. These sequential observations do not isolate capacity from clock, thermal, or scheduling effects.

The first KV19/batch8K attempt stopped after 4/4 C1 archive cases with Windows connection timeouts. The server remained running and a later health request succeeded; the transport root cause is unresolved. The separate retry passed all short and long tasks. Both attempts remain in the evidence.

### Exploratory correctness and variability

| KV20 / K5 batch | Seed 42 | Seed 43 | Seed 44 | Total first-attempt correct |
| --- | --- | --- | --- | --- |
| 4K | 32/32 | 32/32 | 32/32 | 96/96 |
| 8K | 31/32 | 32/32 | 31/32 | 94/96 |

The earlier screens used temperature 0.6, xhigh thinking, an 8,192-token allowance, and fresh request salts. Seed 42 was the initial screen; seeds 43 and 44 were exploratory follow-ups after observing a failure. Fixed seeds do not eliminate concurrent scheduling or numerical variability. The repeated tasks are correlated, and these samples do not establish a statistically reliable answer-quality difference. Even zero failures in 96 independent trials leaves an approximately 3.1% one-sided 95% upper failure-probability bound; shared task structure limits that simple model here.

The two earlier 8K failures were premature stops: seed 42 returned an empty final after a successful inventory-tool retry (20 completion tokens, 19 reasoning tokens); seed 44 returned only `CASE-` instead of `CASE-6:106:BIRCH-1754` (65 completion tokens, 60 reasoning tokens). Both had `finish_reason=stop`, far below the output allowance. The empty-final diagnostic retry answered correctly and remains excluded from first-attempt scores. The runner supports explicit quality seeds and continuing later measurements while retaining failed scores and an unsuccessful overall status.

### Exploratory short-request speed

Input/output tokens per second from the second independent KV20 run, with the same two-repetition per-request aggregation. Each completed 12/12 speed requests; all earlier samples remain in the receipt.

| Input / clients | KV20 / batch4K | KV20 / batch8K |
| --- | --- | --- |
| 4K / C1 | 2,407.95 / 48.40 | 2,766.74 / 45.60 |
| 32K / C1 | 2,890.47 / 48.72 | 3,116.89 / 49.60 |
| 4K / C2 | 2,476.47 / 36.79 | 1,938.19 / 38.51 |
| 32K / C2 | 2,560.19 / 27.31 | 2,317.22 / 29.26 |

## Other settings and historical evidence

| Option | Evidence | Recommendation |
| --- | --- | --- |
| DFlash2 K3 | KV19 profiles pass short and long correctness; batch4K passes strict restart | Qualified alternative with more GPU headroom |
| DFlash2 K5 | KV20 repeated means: 406.03 s at batch4K; 384.60 s at batch8K | Batch8K for measured throughput; batch4K for complete restore and headroom |
| DFlash2 K7 | Historical short correctness passed; slower at most warmed decode points | No measured reason to adopt |
| AZ with MTP, dynamic depth up to 12 | 32/32 short tasks; 43.53 s tool recovery; no near-full or restart qualification | Experimental alternative, not a qualified replacement |
| NVFP4 draft head | Active in the MTP trial; DFlash loader does not apply `MBX_DRAFT_HEAD` | Do not expect the flag to optimize DFlash2 |

The [historical depth comparison](DFlash-depth-trial.md) used 88 GiB, KV11, FP32 SSM, driver 621.14, and a patched candidate image. K5 required a QSA ring-size fix in that trial. The current pinned image already carries the `n1x-ai.qsa-ring=power-of-two-v1` marker, so the compatibility fix is present in the current trials. Historical warmed decode changes versus K3 ranged from −2.5% to +4.6%, with mixed winners. K5 also reduced reported KV capacity from 533,997 to 497,169 tokens at the same 11 GiB pool. These historical results do not establish performance or restoration on the current profiles.

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
| Paired averages | [Three-run comparison](data/k5-batch-repeats-20261117.json) |
| Compact evidence | [Settings, results, and hashes](data/recipe-mix-20261116.json) |
| Raw evidence | `results/benchmarks/recipe-mix-20261116/` |

These are bounded archive and tool workloads, not general coding or vision qualification. Three paired trials support the measured throughput choice, not a universal optimum. K5 with AZ, AZ with batch4K, and a broader parameter sweep are unmeasured. The retained evidence includes a K5 launch that stopped before inference because of a stale host-memory snapshot; the launcher now seeds a fresh operating-system sample before startup without weakening the memory guard.

## Launch

Run only one inference container at a time. Each candidate has its own LMCache namespace and volume. For the measured throughput winner:

```powershell
.\n1x.ps1 setup -Profile qwen38fn-w4-kv20-8k-k5
.\n1x.ps1 start -Profile qwen38fn-w4-kv20-8k-k5
.\n1x.ps1 wait -Profile qwen38fn-w4-kv20-8k-k5
```

Use `qwen38fn-w4-kv20-4k-k5` for complete cacheable-chunk restoration and more GPU headroom. The API model name remains `qwen/qwen38fn-best`; the selected profile identifies the actual configuration.
