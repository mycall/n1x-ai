# DFlash2 request parameter trial

On November 8, 2026, the existing `qwen38fn-best` weights and DFlash2 K3 were tested with **xhigh/medium reasoning and temperature 1.0/0.6**. No model files were downloaded. **Xhigh at 0.6 passed 72/72 scored tasks** and is the candidate for further application testing. Service defaults remain unchanged.

The later [50% background GPU repeat](GPU-priority-trial.md) reproduced xhigh/0.6 at 72/72 and adds measured C2/C8 scaling. It also records why the timing changes do not establish a uniform slider benefit or WSLC's foreground/background GPU classification.

The trial followed review of [Azampatti's model](https://huggingface.co/azampatti/Qwen3.8-Flash-Next-125B-A5B-INT4-AutoRound). Its reduced expert count, INT4 output head, and MTP recipe were not adopted. This experiment concerns request parameters on our existing target and drafter.

## Initial comparison

Each setting ran 16 inventory tasks at C1/C2 and 24 tool-recovery tasks at C4. Inventory used two sessions with two turns, sweeping concurrency forward and backward; initial conversation warmups are excluded from task timing. Recovery exercised tool selection, transient errors, and canonical SKU correction. All settings used thinking, an 8,192-token allowance including reasoning, seed 42, top-p 0.95, top-k 20, and zero presence penalty.

| Reasoning | Temperature | Inventory C1/C2 | Recovery C4 | Total first attempts | Inventory C1 / C2 batch seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| xhigh | 1.0 | 16/16 | 22/24 | 38/40 | 49.69 / 46.49 |
| medium | 1.0 | 15/16 | 24/24 | 39/40 | 67.75 / 48.03 |
| **xhigh** | **0.6** | **16/16** | **24/24** | **40/40** | **49.23 / 41.74** |
| medium | 0.6 | 16/16 | 23/24 | 39/40 | 46.92 / 40.87 |

Each inventory timing combines eight scored tasks at that concurrency across two sweeps. At xhigh, 0.6 increased measured C2 correct-task throughput by 11.37% versus 1.0; C1 was nearly unchanged. These are variable-length completed tasks, not fixed-output decode tests.

The failed medium/1.0 inventory answer returned stock but refused to repeat the synthetic session code. Other initial failures skipped mandatory lookups and invented a final value. None exhausted the output allowance.

## Follow-up

Xhigh/0.6 was tested first, followed by xhigh/1.0, reversing their initial order. Each ran four matched archive tasks at C1 and C2, then another 24 recovery tasks at C4. The archive tasks cover retrieval, arithmetic/JSON, structured extraction, and a supplied tool-result continuation. Actual rendered inputs were 32,762–32,776 tokens, with zero reported cache hits and room reserved for output.

| Temperature | Archive C1 | Archive C2 | Archive C1 / C2 batch seconds | Repeated recovery C4 |
| ---: | ---: | ---: | ---: | ---: |
| **0.6** | **4/4** | **4/4** | **79.98 / 71.26** | **24/24** |
| 1.0 | 3/4 | 4/4 | 75.91 / 105.60 | 24/24 |

The failed temperature-1.0 C1 continuation returned reasoning and an empty final answer with `finish_reason=stop`. A single same-history diagnostic retry also returned empty. Its first score remains failed. No trial request was truncated, and all measured groups reported zero preemptions.

Across both rounds, xhigh/0.6 scored **72/72** and xhigh/1.0 scored **69/72**. Medium settings each retain their initial **39/40**. Overall, **219/224** first attempts passed. These bounded tests do not establish perfect application reliability.

## Interpretation and use

Temperature 0.6 with xhigh is the useful candidate from this trial. Medium was slightly faster in some inventory groups but did not pass all tasks at either temperature. For a request-level trial:

```json
{
  "temperature": 0.6,
  "chat_template_kwargs": {
    "enable_thinking": true,
    "reasoning_effort": "xhigh"
  }
}
```

The final temperature-1.0 run slowed substantially in both prefill and decode: its repeated recovery took 134.43 seconds versus 66.65 seconds initially, while both 0.6 recovery runs took about 63 seconds. Continuous power/clock telemetry was not collected, so that larger late timing difference cannot confidently be attributed to temperature. Do not promote it as a general speedup. Fixed seed also does not guarantee identical concurrent generation.

Near-262K parameter comparisons, general coding tasks, and parameter-specific SSD restore/restart tests remain unmeasured. DFlash2 depth, runtime kernels, KV geometry, expert routing, quantization, and server defaults were held fixed. The setup recreated the previously removed LMCache volume, and the existing prepared PLE map was reused.

## Retained evidence

[Numeric groups and SHA-256 evidence receipt](data/parameter-trials-20261108.json) retain rates, timing sources, token counts, draft acceptance, scores, and local artifact hashes. Raw responses, request payloads, counter snapshots, host configuration, and the experiment scripts remain locally under `results/benchmarks/parameter-review-20261108/`; this ignored directory is not shipped in Git. The scripts reuse the maintained agent, recovery, capacity, streaming, and timing helpers. Request settings and helper source hashes were audited after completion.

The experiment wrapper set all API requests to 8,192 output tokens. Failed recovery summaries still carry the inherited probe's 1,024-token label; raw requests and the numeric receipt document the effective allowance. This metadata discrepancy does not change any first-attempt score. Empty-final diagnostics are separate from scored attempts.
