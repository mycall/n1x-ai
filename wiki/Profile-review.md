# Component review and top ten

**Selected default: `qwen38fn-best`.** The 8K prefill batch prioritizes measured C1 performance; `qwen38fn-lmcache-4k` remains the faster measured cold-C8 alternative. C1/C2 are the intended common workload and C8 the worst case, but **C2 is unmeasured**. See the [matched comparison](Benchmarks.md#matched-prefill-comparison) for speeds, context lengths, and cache evidence.

Selection requires measured speed and **100% first-attempt correctness**. Resource and restore coverage remain reported observations, not automatic promotion vetoes. The 24 new 8K first attempts were correct; this is bounded retrieval quality, not general coding-agent qualification. [Measured results](Benchmarks.md) · [runtime](MyLLMBox.md) · [exact model files](Model-assets.md).

## Top 10 component combinations

Final deployment preference, November 8, 2026. These are reviewed configurations, not ten selectable profile names or a matched universal speed leaderboard. All use the same W4 target. DFlash2 is K3; standard SSM means FP32 with RecoverSSM off. KV/RAM/SSD sizes are GiB. All partitions are 88 GiB except row 7. Missing near-full evidence stays missing.

| Rank | Combination | Actual input / output allowance | Client concurrency and evidence | Disposition | Exact model bundle |
| ---: | --- | --- | --- | --- | --- |
| 1 | **Best:** standard SSM, BF16 indexer; batch8K/KV11/slots8; LMCache RAM4/SSD160 | 253,936–253,946 / 8,192 | C1 cold + immediate warm, C8 cold: 8/8 each | Selected for frequent low concurrency; C2 unmeasured | [W4 + DFlash2 + PLE](Model-assets.md) |
| 2 | Same foundation; batch4K/KV11/slots8; LMCache RAM4/SSD160 | 253,936–253,946 / 8,192 | C1 matched pairs 16/16; separate C8 cold/replay 8/8 each | Measured faster C8 alternative; replay restores only 2/8 | [W4 + DFlash2 + PLE](Model-assets.md) |
| 3 | Former best: standard SSM, BF16 indexer; batch8K/KV12/slots8; cache off | Capacity 253,936–253,947 / 8,192; tools up to 254,202 / remaining window | Capacity C1/C6/C8: 24/24 each; tools C1/C6: 8/8 each; later C1 rematch 16/16 | Strong cache-off baseline and broader tool evidence; slower C1 than current best in retained measurements | [W4 + DFlash2 + PLE](Model-assets.md) |
| 4 | Standard SSM, BF16 indexer; batch4K/KV11/slots8; LMCache RAM4/SSD128 | 253,940–253,947 / 8,192 | Serial initial 15/15 + post-restart 6/6 | Proven serial restore specialist: 12.37× replay and 18.90× restart correct-work rate versus paired cache-off; not a C8 result | [W4 + DFlash2 + PLE](Model-assets.md) |
| 5 | Standard SSM, BF16 indexer; batch4K/KV12/slots8; cache off | 253,936–253,946 / 8,192 | Latest C1/C8 cold: 8/8 each; earlier bounded continuation pilot | Correct, slower C8 than former best; no reason to replace best | [W4 + DFlash2 + PLE](Model-assets.md) |
| 6 | Standard SSM, BF16 indexer; batch4K/KV15/slots4; cache off | 253,936–253,946 / 8,192 | Eight submitted clients: 8/8; serial: 8/8; scheduled peak 3 | More resident capacity did not beat former best's C8 time; sampled GPU reserve 1,249 MiB | [W4 + DFlash2 + PLE](Model-assets.md) |
| 7 | RecoverSSM, BF16 indexer; KV8/slots4; cache off; **96 GiB partition** | Recovery 442–1,401; conversations 11,196–11,529 / 1,024 | Historical C4 recovery and C8 conversations; full historical correctness pass | Historical fallback; no matched near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 8 | Standard SSM, BF16 indexer; KV8/slots8; cache off | Recovery 442–1,393; conversations 11,196–11,520 / 1,024 | Historical full correctness and 48/48 conversations | Correct historical control; poor reuse; no matched near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 9 | RecoverSSM, FP8 indexer; KV8/slots8; cache off | Recovery 442–1,399; conversations 11,196–11,536 / 1,024 | Historical conversation screen 48/48 | No consistent gain from reduced indexer precision; no near-full qualification | [W4 + DFlash2 + PLE](Model-assets.md) |
| 10 | MTP K3, RecoverSSM; KV6/slots4; cache off | Historical short recovery / conversations around 11K; allowance 1,024 | Eight clients, 48/48 conversation screen; batches 177.59 / 176.50 s | Historical algorithm comparison; 1,930 MiB sampled GPU margin; no near-full qualification | [W4 + indexed MTP + PLE](Model-assets.md) |

Rows 7–10 preserve useful historical alternatives; shorter-context results do not fill near-full gaps. Their model files are shared with best except that MTP does not need the separate DFlash2 checkpoint. [Exact filename inventory and rank mappings](data/model-assets.json).

## Retained history and rejected paths

The [historical top-ten data](data/profile-history.json) preserves the original screening ranks, case IDs, context/output settings, timing summaries and the earlier near-full top ten. Historical rank numbers are separate from the final table above. Their resource/strict-restore dispositions reflect the policy at collection time.

RecoverSSM/KV12 and RecoverSSM/KV8 later scored 71/72 first attempts (skipped mandatory lookup and empty final respectively, without exhausting output). Those failures remain failures. A batch8K/KV11/RAM4/SSD128 C6 trial was 24/24 correct but reused only 2/6 prompts and was slower on replay. Prefix unit4096 failed startup because a prefix-cacheable 1,024-token group made that layout invalid; no model requests ran. These outcomes do not qualify those combinations as replacements.

The original source, failed attempts, controller scripts, and raw responses are preserved in the [benchmark archive](Benchmarks.md#retained-evidence). The repository retains compact measurements and source hashes; [Test coverage](Test-plan.md) identifies remaining gaps.
