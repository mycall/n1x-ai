# Test coverage

Use this table to tell which results apply to the profile and workload you intend to run. C1, C2, C4, and C8 count submitted clients. The scheduler can queue requests when their histories exceed resident capacity.

| Profile and workload | Demonstrated | Limit |
| --- | --- | --- |
| Default 96 GiB W4/KV15, near-full tool histories | 48/48 first-attempt tasks at C2/C4 with an 8,192-token output allowance. [KV comparison](96GiB-comparison-campaign.md) | Partial cache-off and displaced-replay controls. Restart restoration was unmeasured in this campaign. |
| 96 GiB W4/KV20 with five draft tokens, 4K versus 8K batches | Three matched pairs. Both completed 36/36 near-full tasks at C4. Only batch4K restored every complete chunk in all three restart checks. [Paired results](FP4-Local-AZ-trial.md#three-run-kv20k5-averages) | Short-screen failures occurred across the wider set of seeds. General coding and vision quality remain unqualified. |
| 96 GiB W4 and AZ/KV19 with three draft tokens | Near-full C4 tool tasks and two-prompt restart checks. [Results by profile](FP4-Local-AZ-trial.md#restart-restoration) | The single W4/AZ comparison cannot establish a weight-only speed advantage. |
| 96 GiB W4/KV11, appended tool histories | 24/24 at C1/C2 with 250,002–250,419 input tokens. All warm hits were in the native prefix cache. [Tool results](Near-full-tools-96GiB.md) | Separate runtime and protocol from the 88 GiB measurements. |
| 88 GiB W4/KV11, near-full retrieval | At C1, batch8K completed cold and immediate-repeat tasks faster. At C8, batch4K completed cold tasks faster. All measured points scored 8/8. [Prefill comparison](Benchmarks.md#matched-prefill-comparison) | C2 retrieval with the 8K allowance and batch8K C8 displaced/restart results are unmeasured in this comparison. |
| 88 GiB W4/KV11, fixed-length generation | Cold speed at C1–C8 across four context sizes, three bursts per cell. [Speed matrix](Qwen38fn-speed-matrix.md) | Each request generated 512 tokens. This measures speed only. |
| Original WSLC reference profiles | Short tool workflows, retrieval, feature checks, and verified SSD restores under the tested budgets. [Reference benchmarks](Reference-benchmarks.md) | Separate feature checks do not qualify simultaneous maximum-context vision and tools. |

There is no matched 88 versus 96 GiB partition-speed result, or matched quality comparison across 1,024-, 2,048-, and 8,192-token output allowances. The configured serving cap is 8,192. For a new comparison, record the effective profile, rendered input, output allowance, first-attempt scores, cache counters, and phase timings. [Benchmark procedures](Speed-benchmarks.md)
