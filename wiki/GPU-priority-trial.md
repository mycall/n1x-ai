# GPU priority repeat at 50% background

On November 8, 2026, the [request parameter trial](Parameter-trials.md) was repeated after the user changed NVIDIA App from **20% to 50% background GPU share**. The original 224 scored tasks, helper sources, prepared archive prompts, request settings, serving profile, target weights, and DFlash2 K3 were retained. No model files were downloaded. The percentages are user-reported settings, not independent driver readback.

**The four-run sequence does not establish a repeatable approximately 7% C8 benefit.** C8 totals in collection order were **59.72 s at 50%, 64.34 s at 20%, 65.91 s at 50%, and 65.22 s at 20%**, with 16/16 correct in every C8 cohort. The latest return to 20% was only 1.05% faster than the preceding 50% run. See the [fourth-cohort retest](#second-return-to-20-retest). WSLC's GPU foreground/background category remains unconfirmed. The earlier parameter finding remains bounded evidence: xhigh/0.6 passed 72/72 in each main trial.

## Repeated correctness

| Reasoning | Temperature | Original 20% | Repeat 50% |
| --- | ---: | ---: | ---: |
| **xhigh** | **0.6** | **72/72** | **72/72** |
| xhigh | 1.0 | 69/72 | 69/72 |
| medium | 1.0 | 39/40 | 39/40 |
| medium | 0.6 | 39/40 | 35/40 |

The core repeat scored **215/224**, versus 219/224 originally. Failure locations can vary even with seed 42 and identical settings because concurrent generation is not guaranteed to be deterministic. The temperature-1.0 32K C1 supplied-tool-result case returned an empty final answer again with `finish_reason=stop`; its one diagnostic retry recovered in this repeat. First-attempt scores were retained.

The result supports xhigh/0.6 as the candidate from these bounded tasks: **144/144 across the two main trials**. Medium did not achieve a clean pass. This is not general coding-agent qualification or evidence of perfect application reliability.

## Observed speed deltas

Each row below uses xhigh/0.6. Batch times include all scored first attempts and exclude conversation warmups and diagnostic retries. Generated lengths vary; these are completed-task timings, not fixed-output decode measurements.

| Workload | Client C | Tasks per setting | 20% seconds | 50% seconds | Time change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Inventory | 1 | 8 | 49.23 | 46.73 | −5.07% |
| Inventory | 2 | 8 | 41.74 | 42.55 | +1.94% |
| Initial recovery | 4 | 24 | 62.82 | 66.40 | +5.70% |
| 32K archive quality | 1 | 4 | 79.98 | 142.55 | +78.24% |
| 32K archive quality | 2 | 4 | 71.26 | 143.85 | +101.86% |
| Repeated recovery | 4 | 24 | 63.22 | 135.16 | +113.80% |

Other early groups were faster: for example, xhigh/1.0 inventory C2 went from 46.49 to 40.03 seconds. The slower late results therefore cannot be summarized as a uniform slider effect. The sequential before/after comparison does not isolate GPU scheduling policy from clock behavior, desktop contention, cache effects, or generated work. The original run lacked continuous GPU telemetry.

## C2 and C8 at 50%

This additional workload uses eight independent approximately 11K-token inventory sessions, one scored tool round trip each, at C2 and C8 in forward/reverse sweeps. Both points have 16 scored tasks. It differs from the original two-session/two-turn inventory cohort and is reported separately.

| Client C | Correct | Combined batch seconds | Correct tasks/s | Mean session seconds | Peak sampled scheduled |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 16/16 | 80.11 | 0.1997 | 9.85 | 2 |
| 8 | 16/16 | 59.72 | 0.2679 | 28.38 | 8 |

C8 delivered **34.14% higher correct-task throughput** at 50%, while each session took longer on average. The two C8 batches took 29.05 and 30.67 seconds; C2 took 40.19 and 39.92 seconds. There were no preemptions or truncations in this additional check. Sampled GPU utilization reached 96% at both points and did not exceed 98% during their timed windows.

This initial test answers scaling at 50%. It did not yet include a 20% counterpart; the subsequent matched return baseline below supplies that comparison. Short-session results do not establish near-full-context C8 behavior.

## Matched 20% return baseline

The user then returned NVIDIA App to **20% background share** and confirmed **MSI Performance Boost**. The unchanged eight-session probe was rerun at C2/C8 in forward/reverse order, with the same target, DFlash2 K3, xhigh, temperature 0.6, seed 42, and 8,192-token output allowance. Helper hashes matched, and all 32 warmup request payloads were identical to the 50% cohort after excluding fresh cache salts. The service was restarted and warmed before measurement; the order was 50% first, then the 20% return baseline.

| Client C | 20% correct | 50% correct | 20% batch seconds | 50% batch seconds | Batch time change, 20% → 50% |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 15/16 | 16/16 | 89.33 | 80.11 | −10.33% |
| 8 | 16/16 | 16/16 | 64.34 | 59.72 | **−7.18%** |

Each batch-time total combines two eight-task groups. The individual 20% C8 groups took 32.46 and 31.88 seconds, versus 29.05 and 30.67 at 50%. C8 correct-task throughput was **0.2487 versus 0.2679 tasks/s**, a **7.74% gain at 50%**. Mean C8 session latency was 31.44 versus 28.38 seconds. This is an observed completed-task improvement on the matched approximately 11K-token session workload, not a fixed-output decode speedup or proof of a universal slider benefit.

The 20% C2 failure retrieved the correct count but duplicated the exact required answer, `AGENT-0003:44`, so it failed the strict format check. No first score was replaced. This new failure also means the earlier clean xhigh/0.6 trial totals are not a claim of perfect reliability across all added workloads. There were no preemptions, truncations, or empty finals in the 20% cohort.

The scheduler sampled peaks of two and eight running requests at the respective points. Timed C8 GPU samples reached 96% utilization at both percentages, with none above 98%. Median sampled C8 clocks were 1,585.5 MHz at 20% and 1,443 MHz at 50%, illustrating why a clock reading alone does not determine completed-task throughput. Sequential runs, variable generated lengths, and uncontrolled desktop GPU contention still limit causal attribution. These results do not identify WSLC's foreground/background GPU category.

[Matched baseline measurements and artifact receipt](data/gpu-priority-c8-baseline-20261108.json) retain both conditions, strict failure details, timing/telemetry summaries, and source audits. Raw baseline artifacts are under `results/benchmarks/parameter-review-20261108/background20/`. The user-selected 20% setting and deployment defaults were left unchanged; the model service was stopped after the test.

## Return-to-50% verification

The user switched back to 50% and requested verification of the approximately 7% C8 deltas. The unchanged probe was run again, yielding a **50% → 20% → 50%** sequence. All three conditions used eight sessions, one scored turn each, forward/reverse C2/C8 sweeps, xhigh, temperature 0.6, seed 42, and an 8,192-token allowance. The serving profile and helper source hashes matched. All 32 warmup request payloads were identical across the three runs after excluding fresh cache salts. MSI Performance Boost was recorded from the user's confirmation.

| Condition in collection order | C2 correct | C2 batch seconds | C8 correct | C8 batch seconds | C8 correct tasks/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| First 50% | 16/16 | 80.11 | 16/16 | 59.72 | 0.2679 |
| 20% baseline | 15/16 | 89.33 | 16/16 | 64.34 | 0.2487 |
| **50% verification** | **16/16** | **87.36** | **16/16** | **65.91** | **0.2428** |

The C8 verification groups took **32.55 and 33.36 seconds**, compared with 32.46 and 31.88 at 20%. The repeated 50% total was **2.44% slower** than 20%, giving **2.38% lower correct-task throughput**. The previous 7.18% time reduction and 7.74% throughput increase therefore **did not replicate**. Retain all three observations; pooling the two 50% results would obscure the failed confirmation.

C2's repeated time reduction versus 20% was only 2.21%, versus 10.33% in the first comparison. Its correct-task throughput difference also includes the 20% baseline's duplicated-answer failure and must not be described as a pure speed gain. The verification itself passed **32/32**, with no preemptions, truncations, or empty finals.

C8 generated-token totals, including reasoning, were 2,390 at the first 50%, 2,350 at 20%, and 2,368 in the 50% verification. The timed GPU utilization samples reached 96% in each C8 condition, with none above 98%. Median sampled C8 clocks were 1,443, 1,585.5, and 1,566 MHz respectively. These observations do not establish the cause of the timing variation or WSLC's foreground/background GPU category. With only two batches per concurrency/condition and uncontrolled desktop contention, the runs do not validate a reliable approximately 7% slider benefit.

[Verification measurements and artifact receipt](data/gpu-priority-c8-verification-20261108.json) preserve the distinct runs, raw-source audits, and request-phase data. The earlier artifact hashes were verified unchanged. Raw verification files are under `results/benchmarks/parameter-review-20261108/background50-verify/`. The model service was stopped afterward; the user's 50% setting and deployment defaults were retained.

## Second return-to-20% retest

The user switched back to 20% and requested another retest. The same probe and forward/reverse C2/C8 sweeps were retained, extending the collection sequence to **50% → 20% → 50% → 20%**. All source hashes matched; all 32 warmup payloads matched the three prior cohorts after excluding fresh salts. The new cohort passed **32/32**, with no preemptions, truncations, or empty finals.

| Cohort in collection order | C2 correct | C2 batch seconds | C8 correct | C8 batch seconds |
| --- | ---: | ---: | ---: | ---: |
| First 50% | 16/16 | 80.11 | 16/16 | 59.72 |
| First 20% | 15/16 | 89.33 | 16/16 | 64.34 |
| Second 50% | 16/16 | 87.36 | 16/16 | 65.91 |
| **Second 20%** | **16/16** | **89.84** | **16/16** | **65.22** |

The second 20% C8 groups took **32.32 and 32.89 seconds**. Relative to the latest 50% cohort, C8 used **1.05% less time**, with **1.06% higher correct-task throughput**. C2 moved in the opposite direction: **2.83% more time**, with 2.76% lower correct-task throughput. The two 20% C8 totals differed by 1.36%; the three most recent C8 totals were 64.34, 65.91, and 65.22 seconds. These small, mixed changes do not reproduce the initial approximately 7% C8 gain.

That C8 direction is compatible with foreground treatment, but does not establish it. Similar timings can also occur without significant competing GPU work. The experiment did not control foreground GPU contention or directly measure the worker's scheduling category, so it neither classifies WSLC nor proves the feature has zero effect.

Runtime history is another limitation: the first 50% C8 cohort followed the longer parameter comparison, while later cohorts followed server restarts and the same session-priming procedure. Generated lengths, caches, clocks, and startup autotuning were not independently fixed. The result is limited to these approximately 11K-token tool sessions, not near-full-context C8 behavior.

[Four-run measurements and artifact receipt](data/gpu-priority-c8-four-runs-20261108.json) preserve every cohort and the latest independently audited workflow scores. Raw retest artifacts are under `results/benchmarks/parameter-review-20261108/background20-retest/`. The user-selected 20% setting and deployment defaults were retained, and the service was stopped after testing.

## Clock observations and GPU classification

GPU power, clocks, utilization, and the foreground executable were sampled approximately every five seconds during the repeat. The user confirmed that MSI Performance/Boost and Windows power mode were not changed, and later explicitly confirmed **MSI Performance Boost**. The Windows power-scheme query separately reported Balanced; that query does not read MSI's performance mode and does not establish that Boost is off. Windows reported AC power.

Sampled clock medians declined from 1,485 MHz during the initial xhigh/0.6 inventory phase to 754 MHz during its later 32K phase. A direct 780 MHz diagnostic probe reported 51% GPU utilization; another cited recovery sample reported 780 MHz at 94%. No sample below 1 GHz in the core trace was above 98% utilization. Sampled clocks alone do not establish a saturated-GPU bottleneck.

The driver's `Reliability` clock indicator was active when probed at 780/708 MHz, with the probed thermal and power-brake indicators inactive. The same reliability indicator was later active at **1,865 MHz and 87% utilization**. It therefore does not, by itself, explain the slowdown. This trial does not establish what caused the clock or timing changes, including whether scheduling policy influenced them.

**WSLC's foreground/background GPU classification remains unconfirmed.** A detached Linux process without a window does not prove its NVIDIA scheduling category. The Windows `nvidia-smi` query did not identify the Linux inference worker or expose that category. Foreground-window telemetry is also not GPU-context classification. Microsoft documents that Windows controls context prioritization under [hardware-accelerated GPU scheduling](https://devblogs.microsoft.com/directx/hardware-accelerated-gpu-scheduling/); NVIDIA describes the [foreground/background resource control](https://blogs.nvidia.com/blog/local-ai-rtx-spark-laptops-updates-models-agents-games/) without establishing WSLC's category here. The earlier background assumption should not be treated as a finding.

## Evidence and state

[Paired measurements, telemetry summaries, and artifact hashes](data/gpu-priority-trial-20261108.json) preserve the full comparison and additional scaling results. Raw requests, responses, diagnostic retries, counter snapshots, GPU samples, scheduler samples, and experiment source remain locally under `results/benchmarks/parameter-review-20261108/background50/` and its parent. These ignored local artifacts are not shipped in Git. The original evidence hashes remained unchanged, and the prepared 32K request objects matched exactly.

The request allowance was 8,192 tokens including reasoning; inherited failed recovery summaries can still display the original probe's 1,024-token label. Raw API settings were audited. No deployment defaults, weights, or GPU priority settings were changed by the experiment. The model service was stopped afterward, matching its initial state.
