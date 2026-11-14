# Near-full tool histories on 96 GiB

On November 11, 2026, the locally configured `qwen38fn-best` passed **24/24 first-attempt tool tasks** at C1/C2 on a 96 GiB GPU partition. All 48 generation requests completed normally, with zero preemptions, truncations, or diagnostic retries. The API returned HTTP 200 after the run. This qualifies the bounded synthetic workload below, not arbitrary agent tasks.

## Configuration and method

The effective configuration retained DFlash2 K3, standard FP32 SSM, BF16 indexer, batch8K, KV11, eight slots, and LMCache RAM4/SSD160. The local partition requirement was changed to `RequiredPartitionMiB = 98304`; the extra VRAM was not assigned to a larger KV pool. The existing local image was `n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d`, immutable ID `sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc`. This differs from the image behind the November 8 profile comparison; no matched 88/96 GiB or cache-off comparison was performed. Windows reported Balanced; MSI boost mode was not independently verified.

The [maintained workload](Speed-benchmarks.md#appended-history-tool-workload) starts two independent histories at exactly 250,002 rendered input tokens. Each performs inventory lookup, price lookup, then another inventory lookup. Correctness requires the exact tool name and SKU, matching call/result IDs, and a final answer combining the simulated tool result with archive facts placed at 10% and 90% of the initial history. Reasoning is preserved in the submitted history. Actual inputs span **250,002–250,419 tokens**, with an unchanged **8,192-token output allowance**, thinking/xhigh, temperature 0 and seed 42.

Two repeats ran C1→C2 then C2→C1, using fresh salts per session and group and a stable salt within each session. Initial selections are cold; subsequent selections and tool-result continuations append to each history. A separate 2K pilot passed 3/3 and is excluded. Every generation's reported input count matched `/tokenize`. Token-count checks are included in batch and task wall time but excluded from individual generation-request latency.

## Results

| Measurement | C1 | C2 |
| --- | ---: | ---: |
| First-attempt correct tasks | 12/12 | 12/12 |
| Cold selection mean request seconds | 116.17 | 234.09 |
| Appended selection mean request seconds | 3.03 | 4.35 |
| Tool-result continuation mean request seconds | 2.26 | 3.21 |
| Warm appended task mean seconds, including token-count checks | 6.25 | 9.34 |
| Total batch seconds, both repeats including cold starts | 527.66 | 516.03 |
| Correct tasks/second, including cold starts | 0.02274 | 0.02325 |
| Preemptions | 0 | 0 |

C2 delivered only **1.023×** C1's total correct-work throughput for this short three-turn workload. The cold starts dominate elapsed time. Warm selection and continuation generate different work from the initial selection, so their latency ratios are not a matched cache-speedup measurement. Outputs ranged from 42 to 201 tokens including reasoning; the 8K allowance was not exhausted.

All **eight cold requests had zero cached tokens**. All **40 warm requests reused 249,856 tokens**, covering about **99.8%** of their input. The group counter deltas attribute 4,997,120 reused tokens at each concurrency to **native GPU prefix cache**, with **zero external-prefix hits**. Thus this proves effective reuse with the configured LMCache combination, but does not prove external restore or SSD restart.

LMCache still performed prefetch work: the retained log has 40 completed-prefetch messages, 179 allocation-warning lines and six admission-recovery messages. Warning lines are not 179 failed requests; all first attempts passed. These observations remain relevant to future displaced-replay/restore tests and potential prefetch overhead.

Sampled GPU allocation during the run was 86,125–87,081 MiB out of 98,304 MiB, with about 5.2–6.2 GiB of host physical RAM free. These are point observations, not a continuous minimum-memory guarantee. Startup experienced guest RAM pressure and swap use; weight loading alone took about 232 seconds. Startup is excluded from the benchmark timings.

## Evidence and remaining work

[Compact results, effective configuration, source hashes and raw-artifact SHA-256 hashes](data/near-full-tools-96g.json) retain the audit record. Local raw files are in `results/benchmarks/near-full-tools-96g-20261111`: request/response JSONL, task scores, calibration, group summaries, before/after metrics, memory observations and server logs. Recompute the summary with:

```powershell
python benchmarks/near_full_tools_report.py results/benchmarks/near-full-tools-96g-20261111
```

This measures the November 11 KV11 configuration on the 96 GiB runtime. The subsequent [campaign](96GiB-comparison-campaign.md) selected KV15 for today's best profile. The original 88 GiB runtime's matched C2 prefill comparison and tool transfer, C8 displaced replay/restart, and the matched 1K/2K/8K output-quality comparison remain open. This run held KV allocation fixed and does not establish a partition-speed benefit.
