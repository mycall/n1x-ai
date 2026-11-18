# GPU background share and tool throughput

On the 88 GiB W4/DFlash2 K3 configuration, changing NVIDIA App background GPU share between 20% and 50% produced no repeatable C8 speed advantage. All four C8 cohorts scored 16/16. The measurements apply to approximately 11K-token inventory sessions. The foreground/background scheduling category of the WSLC worker is unknown.

## Concurrency and background share

Eight independent sessions each performed one tool round trip. Two sweeps reversed the order of C2 and C8, giving 16 timed tasks per concurrency. All cohorts used xhigh reasoning, temperature 0.6, seed 42, and an 8,192-token allowance. Warmup payloads matched apart from cache salts.

| Cohort in collection order | C2 correct | C2 batch seconds | C8 correct | C8 batch seconds |
| --- | ---: | ---: | ---: | ---: |
| First 50% | 16/16 | 80.11 | 16/16 | 59.72 |
| First 20% | 15/16 | 89.33 | 16/16 | 64.34 |
| Second 50% | 16/16 | 87.36 | 16/16 | 65.91 |
| **Second 20%** | **16/16** | **89.84** | **16/16** | **65.22** |

At the first 50% setting, C8 processed 0.2679 correct tasks/s versus 0.1997 at C2. Mean session time grew from 9.85 s to 28.38 s. The first 20% C2 cohort lost one point for duplicating the required final answer. That failure is included in its score.

The first C8 comparison favored 50% by 7.18% elapsed time. Repeating the same setting yielded 65.91 s, slower than both 20% runs. The first cohort followed a longer parameter trial, while later cohorts followed server restarts. Generated lengths, kernel warmup, and desktop GPU contention can affect these timings. [All four cohorts](data/gpu-priority-c8-four-runs-20261108.json) · [Matched baseline](data/gpu-priority-c8-baseline-20261108.json) · [Verification data](data/gpu-priority-c8-verification-20261108.json)

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

## Clock observations and GPU classification

Telemetry sampled clocks, power, utilization, and the foreground executable about every five seconds. Background share and MSI Performance Boost were user-reported. Windows separately reported Balanced and AC power.

Sampled clock medians declined from 1,485 MHz during the initial xhigh/0.6 inventory phase to 754 MHz during its later 32K phase. A direct 780 MHz diagnostic probe reported 51% GPU utilization; another cited recovery sample reported 780 MHz at 94%. No sample below 1 GHz in the core trace was above 98% utilization. Sampled clocks alone do not establish a saturated-GPU bottleneck.

The driver's `Reliability` clock indicator was active when probed at 780/708 MHz, with the probed thermal and power-brake indicators inactive. The same reliability indicator was later active at **1,865 MHz and 87% utilization**. It therefore does not, by itself, explain the slowdown. This trial does not establish what caused the clock or timing changes, including whether scheduling policy influenced them.

**WSLC's foreground/background GPU classification remains unconfirmed.** A detached Linux process without a window does not prove its NVIDIA scheduling category. The Windows `nvidia-smi` query did not identify the Linux inference worker or expose that category. Foreground-window telemetry is also not GPU-context classification. Microsoft documents that Windows controls context prioritization under [hardware-accelerated GPU scheduling](https://devblogs.microsoft.com/directx/hardware-accelerated-gpu-scheduling/); NVIDIA describes the [foreground/background resource control](https://blogs.nvidia.com/blog/local-ai-rtx-spark-laptops-updates-models-agents-games/) without establishing WSLC's category here.

## Evidence

The [parameter trial](Parameter-trials.md) describes the request fixtures. The [measurements and hashes](data/gpu-priority-trial-20261108.json) cover the November 8, 2026 comparison, with raw files under `results/benchmarks/parameter-review-20261108/`. The raw API settings confirm an 8,192-token allowance even where inherited recovery summaries display 1,024.
