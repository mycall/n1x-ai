# Historical component comparison

Deployment comparison from November 8, 2026. For the current default and selectable alternatives, see [Serving profiles](Profile-review.md). These are reviewed configurations, not ten selectable profile names or a matched universal speed leaderboard. All use the same W4 target. DFlash2 is K3; standard SSM means FP32 with RecoverSSM off. KV/RAM/SSD sizes are GiB. All partitions are 88 GiB except row 7. Missing near-full evidence stays missing.

| Rank | Combination | Actual input / output allowance | Client concurrency and evidence | Disposition | Exact model bundle |
| ---: | --- | --- | --- | --- | --- |
| 1 | Then-selected configuration: standard SSM, BF16 indexer; batch8K/KV11/slots8; LMCache RAM4/SSD160 | 253,936–253,946 / 8,192 | C1 cold + immediate warm, C8 cold: 8/8 each | Selected for frequent low concurrency; C2 unmeasured | [W4 + DFlash2 + PLE](Model-assets.md) |
| 2 | Same foundation; batch4K/KV11/slots8; LMCache RAM4/SSD160 | 253,936–253,946 / 8,192 | C1 matched pairs 16/16; separate C8 cold/replay 8/8 each | Measured faster C8 alternative; replay restores only 2/8 | [W4 + DFlash2 + PLE](Model-assets.md) |
| 3 | Former best: standard SSM, BF16 indexer; batch8K/KV12/slots8; cache off | Capacity 253,936–253,947 / 8,192; tools up to 254,202 / remaining window | Capacity C1/C6/C8: 24/24 each; tools C1/C6: 8/8 each; later C1 rematch 16/16 | Strong cache-off baseline and broader tool evidence; slower C1 than the KV11/batch8K configuration in retained measurements | [W4 + DFlash2 + PLE](Model-assets.md) |
| 4 | Standard SSM, BF16 indexer; batch4K/KV11/slots8; LMCache RAM4/SSD128 | 253,940–253,947 / 8,192 | Serial initial 15/15 + post-restart 6/6 | Proven serial restore specialist: 12.37× replay and 18.90× restart correct-work rate versus paired cache-off; not a C8 result | [W4 + DFlash2 + PLE](Model-assets.md) |
| 5 | Standard SSM, BF16 indexer; batch4K/KV12/slots8; cache off | 253,936–253,946 / 8,192 | Latest C1/C8 cold: 8/8 each; earlier bounded continuation pilot | Correct, slower C8 than the batch8K/KV12 control | [W4 + DFlash2 + PLE](Model-assets.md) |
| 6 | Standard SSM, BF16 indexer; batch4K/KV15/slots4; cache off | 253,936–253,946 / 8,192 | Eight submitted clients: 8/8; serial: 8/8; scheduled peak 3 | More resident capacity did not beat former best's C8 time; sampled GPU reserve 1,249 MiB | [W4 + DFlash2 + PLE](Model-assets.md) |
| 7 | RecoverSSM, BF16 indexer; KV8/slots4; cache off; **96 GiB partition** | Recovery 442–1,401; conversations 11,196–11,529 / 1,024 | Historical C4 recovery and C8 conversations; full historical correctness pass | Historical fallback; no matched near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 8 | Standard SSM, BF16 indexer; KV8/slots8; cache off | Recovery 442–1,393; conversations 11,196–11,520 / 1,024 | Historical full correctness and 48/48 conversations | Correct historical control; poor reuse; no matched near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 9 | RecoverSSM, FP8 indexer; KV8/slots8; cache off | Recovery 442–1,399; conversations 11,196–11,536 / 1,024 | Historical conversation screen 48/48 | No consistent gain from reduced indexer precision; no near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 10 | MTP K3, RecoverSSM; KV6/slots4; cache off | Historical short recovery / conversations around 11K; allowance 1,024 | Eight clients, 48/48 conversation screen; batches 177.59 / 176.50 s | Historical algorithm comparison; 1,930 MiB sampled GPU margin; no near-full qualification | [W4 + indexed MTP + PLE](Model-assets.md) |

Rows 7–10 preserve useful historical alternatives; shorter-context results do not fill near-full gaps. Their model files are shared with the W4 default except that MTP does not need the separate DFlash2 checkpoint. [Exact filename inventory and rank mappings](data/model-assets.json).

## Retained history and rejected paths

The [historical top-ten data](data/profile-history.json) preserves the original screening ranks, case IDs, context/output settings, timing summaries and the earlier near-full top ten. Historical rank numbers are separate from the table above. Their resource/strict-restore dispositions reflect the policy at collection time.

RecoverSSM/KV12 and RecoverSSM/KV8 later scored 71/72 first attempts (skipped mandatory lookup and empty final respectively, without exhausting output). Those failures remain failures. A batch8K/KV11/RAM4/SSD128 C6 trial was 24/24 correct but reused only 2/6 prompts and was slower on replay. Prefix unit4096 failed startup because a prefix-cacheable 1,024-token group made that layout invalid; no model requests ran. These outcomes do not qualify those combinations as replacements.

The original source, failed attempts, controller scripts, and raw responses are preserved in the [benchmark archive](Benchmarks.md#retained-evidence). The repository retains compact measurements and source hashes; [Test coverage](Test-plan.md) identifies remaining gaps.

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

Eight clients do not mean eight resident full contexts: the latest 8K run peaked at two scheduled and seven waiting, with no preemptions. Its C8/C1 cold correct-work ratio was 0.681×, below the 6.4× near-linear diagnostic. An earlier former-best cohort scored 24/24 at each C1/C6/C8, with phase rates (1,746.19, 53.09), (1,472.42, 1.57) and (1,479.51, 1.57) tk/s. Neither higher concurrency improved that cohort's cold throughput. Separate former-best near-full tool workflows passed 8/8 at C1 and C6; these are not tool-workflow qualification of the KV11 LMCache configuration.

Sequential timings include observed clock/power variation and variable generated lengths. See [Test coverage](Test-plan.md) for the limits of these measurements and remaining comparisons.
