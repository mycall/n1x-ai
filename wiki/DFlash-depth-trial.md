# DFlash2 draft-depth trial

**Retain K3 as the default.** On November 8, 2026, K1/K3/K5/K7 passed **160/160 first-attempt tasks** across five correctness runs, including an initial and later K3 run. Larger depths did not establish a consistent decode-speed improvement. The trial also found and fixed a QSA cache-ring startup failure at K5. [Numeric results, source hashes, and evidence receipt](data/dflash-depth-trial-20261108.json).

K counts speculative draft tokens per verification. All runs reused the installed W4 AutoRound target, DFlash2 checkpoint, and prepared PLE map. No models or base images were downloaded. The regular profile remains on its original image and K3 settings; its existing configuration fingerprint is preserved.

## Implementation

`DFlashTokens` now accepts integers 1-7 for the MyLLMBox profiles. It controls the actual command-line speculative configuration, graph coverage through `(K + 1) * MaxSequences`, and a separate LMCache namespace for each nondefault depth. K3 keeps its existing namespace. `list profiles` displays the effective DFlash2 depth. Other backends keep their fixed recipes. See [configuration](Configuration.md#experimental-draft-depth).

The original runtime failed before readiness at K5: its QSA ring formula returned 12 slots, which cannot divide the 4,096-token attention block. An original-image K7 attempt was deliberately stopped after source inspection confirmed the same incompatible ring size; no inference ran in either attempt.

[The guarded runtime patch](../runtime/myllmbox/patch_qsa_ring.py) rounds the number of compression groups to a power of two. The ring is 16 slots for K5-K7 and unchanged for K1-K4. CPU checks cover capacity, block divisibility, rejected-draft wraparound, and refusal to modify unreviewed source. Rebuilds apply the patch and label the image `n1x-ai.qsa-ring=power-of-two-v1`. Setup and new K5-K7 launches reject images without that marker before loading weights.

The tested local candidate is `n1x-ai:dflash-depth-qsa-v1`, image ID `sha256:e92aec21c8beb0e696729420729c7bbf4ef0b34dc5a22bf2143048db39414c3f`. It shares all 61 original filesystem layers and adds two patch layers. vLLM 0.32.0, Torch 2.13.0+cu130, and LMCache 0.5.6 are unchanged. K1 and the initial K3 run used the original image; K5, K7, and the later K3 run used this candidate.

## Workload

The RTX N1X used its existing 88 GiB GPU partition and driver 621.14. Serving retained 262,144 maximum context, eight slots, 8,192 prefill tokens per step, an 11 GiB FP8 KV pool, BF16 draft KV, standard FP32 SSM, RecoverSSM off, and a BF16 indexer. All depths used 4,096-token cache blocks/chunks and a dedicated trial cache volume.

Correctness used thinking/xhigh, temperature 0.6, top-p 0.95, top-k 20, seed 42, zero presence penalty, and an 8,192-token output allowance including reasoning. Each run scored four archive tasks at C1 and four at C2, then 24 tool-recovery tasks at C4. Archive tasks cover retrieval, arithmetic/JSON, structured extraction, and a supplied tool-result continuation. Actual archive inputs were 32,762-32,776 tokens with zero reported cache hits. Recovery covers tool selection, transient errors, and canonical SKU correction. Raw requests were audited for the effective 8K allowance; the wrapper overrides the recovery helper's smaller default.

| Run | 32K quality C1+C2 | Tool recovery C4 | Batch seconds: quality C1 / C2 / recovery |
| --- | ---: | ---: | --- |
| K3 initial, original image | 8/8 | 24/24 | 69.36 / 67.69 / 64.28 |
| K1, original image | 8/8 | 24/24 | 83.59 / 72.87 / 72.88 |
| K5, patched image | 8/8 | 24/24 | 67.84 / 69.22 / 63.52 |
| K7, patched image | 8/8 | 24/24 | 67.72 / 64.48 / 64.24 |
| K3 later, patched image | 8/8 | 24/24 | 85.15 / 74.71 / 68.59 |

These are completed-task timings with variable generated lengths. First-use JIT compilation occurred in some phases. They do not isolate the effect of draft depth. First scores were preserved; diagnostic retries do not replace them.

## Speed with warmed kernels

The maintained speed suite used identical rendered prompts at nominal 4K/32K depth, C1/C2, temperature zero, thinking/xhigh, seed 42, and exactly 512 generated tokens with EOS ignored. All 48 measured speed requests completed with zero reported cache hits. Each sweep contains one C1 request and two C2 requests per prompt depth.

Initial sweeps exposed inference-time JIT compilation. K5 and K7 therefore received a second speed sweep after their correctness tests; the later K3 run received the same follow-up. These three warmed sweeps had **zero logged inference-time JIT warnings**. Their prompts remained cold through fresh cache salts.

Each cell below is **(read, write) tokens/s**, using weighted per-request phase rates. C2 values are per-request rates, with overlapping request intervals; they are not aggregate serving throughput.

| Prompt / client concurrency | K3 later, warmed | K5 warmed | K7 warmed |
| --- | --- | --- | --- |
| 4K / C1 | (1,873, 45.26) | (2,242, 47.34) | (2,264, 43.73) |
| 32K / C1 | (2,095, 45.89) | (2,476, 44.75) | (2,202, 39.75) |
| 4K / C2 | (1,918, 32.10) | (2,014, 33.27) | (1,925, 29.86) |
| 32K / C2 | (1,640, 26.50) | (1,834, 26.19) | (1,735, 26.82) |

K5's warmed write rates differ from K3 by about -2.5% to +4.6%, with mixed winners. The initial-to-later K3 screen alone changed by approximately 5-13% in write speed at matched points, and GPU clocks varied. This sequential, single-sweep comparison does not establish a reliable K5 advantage. The read-rate differences also need a repeated, controlled comparison before being attributed to depth. K7 was slower at most warmed write points.

K1's initial write rates were 40.26/40.26 tokens/s at C1 and 30.82/25.54 at C2 for 4K/32K inputs. It was slower than the initial K3 screen but did not receive a separate warmed follow-up. All initial sweeps remain in the numeric receipt.

## Capacity and interpretation

| Draft depth | Reported GPU KV capacity, tokens |
| ---: | ---: |
| K1 | 576,716 |
| K3, later run | 533,997 |
| K5 | 497,169 |
| K7 | 465,094 |

The same 11 GiB pool holds fewer tokens at larger depths. Startup capacity is a planning estimate; it does not qualify simultaneous full-window histories. More accepted tokens per verification also did not guarantee faster requests: K5/K7's tool-recovery batches stayed near the initial K3 time despite greater acceptance lengths. Evaluate completed correct work and latency alongside acceptance.

K3 remains selected. K5/K7 are available for further experiments through the patched candidate. To try K5 locally, merge these keys into the existing `config.local.psd1`, then use `setup` and `recreate`:

```powershell
Image = 'n1x-ai:dflash-depth-qsa-v1'
ImageId = 'sha256:e92aec21c8beb0e696729420729c7bbf4ef0b34dc5a22bf2143048db39414c3f'
DFlashTokens = 5
```

The candidate is already present on this machine. A fresh build can produce a different image ID; follow [candidate selection](MyLLMBox.md#select-a-candidate). Remove all three overrides and recreate to return to the selected original K3 image. Benchmark entrypoints and timing definitions are in [Speed and capacity benchmarks](Speed-benchmarks.md).

## Evidence and limits

Raw requests/responses, counter snapshots, GPU telemetry, effective container arguments, failed-start logs, and experiment source remain under ignored `results/benchmarks/dflash-depth-20261108/`. The receipt retains their hashes, exact numbers, runtime identities, and request audits. Model configuration/index hashes were unchanged. Full weight files were not rehashed.

Local checks passed: 87 Python tests with five skips, plus the PowerShell suite. The trial container and its generated cache volume were removed; the candidate image, regular model assets, and regular cache volumes were retained. Serving ended stopped, matching the initial state.

C8, 128K/near-full quality, SSD restore/restart, vision, and GPU tests at K2/K4/K6 remain unmeasured. The fixture passes do not establish universal application reliability. The candidate was not promoted to the default image.
