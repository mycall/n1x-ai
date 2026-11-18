# Benchmark results

Choose the result that matches your profile, GPU partition, and workload. **C4** means four clients submitted work concurrently. **KV15** means a 15 GiB GPU key/value cache. A **4K or 8K batch** is the scheduler’s token budget per step. It differs from both the prompt length and the output allowance.

## 96 GiB serving profiles

| Question | Result | Measurements |
| --- | --- | --- |
| Why does the default use KV15? | With an 8K batch, the default completed 48/48 near-full C2/C4 tool tasks. Its C4 correct-task throughput exceeded KV11 by about 31%. | [KV11 and KV15 controls](96GiB-comparison-campaign.md) |
| How does prefill batch affect K5? | On the near-full C4 workload, batch8K took 384.60 s versus 406.03 s for batch4K on average. Both passed every long task across three paired runs. | [Paired timings and first-attempt scores](FP4-Local-AZ-trial.md#three-run-kv20k5-averages) |
| Which profiles restored a full cacheable prefix? | The W4/KV19 and W4/KV20 profiles with a 4K batch recovered all 31 complete chunks per prompt in their two-prompt restart checks. An incomplete final chunk still needs computation. | [K3 restart checks](FP4-Local-AZ-trial.md#restart-restoration) · [K5 restart checks](FP4-Local-AZ-trial.md#three-run-kv20k5-averages) |
| What happens when a tool result is appended to a long history? | The KV11 C1/C2 trial passed 24/24 first attempts. All 40 warm requests reused 249,856 tokens through the native GPU prefix cache. | [Appended-history test](Near-full-tools-96GiB.md) |

Use [Serving profiles](Profile-review.md) to choose a configuration and [Test coverage](Test-plan.md) to check which conclusions transfer to your workload.

## Matched prefill comparison

On the **88 GiB W4/KV11 runtime**, batch8K completed near-full retrieval faster with one client, while batch4K was faster with eight cold clients. Each measured point scored 8/8. The fixed-length speed grid covers 32 concurrency/context combinations on that same generation of runtime. [Cold and warm prefill measurements](Historical-profile-comparison.md#matched-prefill-comparison) · [Fixed-length speed matrix and charts](Qwen38fn-speed-matrix.md)

## Agent and restore qualification

On the **original WSLC reference runtime**, DFlash2 and MTP each passed 72/72 inventory tasks with thinking enabled, a 1,024-token output allowance, and tool-call reasoning preserved on continuation. The DFlash2 recovery suite also passed 24/24 retry and argument-correction tasks. [Agent measurements](Reference-benchmarks.md#agent-and-restore-qualification) · [DFlash2 and MTP comparison](Reference-benchmarks.md#dflash2-comparison)

Separate restart tests verified SSD reads, external-cache hits and completed GPU transfers with empty GPU/RAM caches. A correct reply alone can come from recomputation. [Cache validation](Reference-benchmarks.md#feature-and-cache-validation) · [SSD sizing](Reference-benchmarks.md#ssd-budget-validation)

## Other comparisons

| Topic | Evidence |
| --- | --- |
| Weights and recurrent-state precision | [W4 and FP4-Local-AZ workloads](FP4-Local-AZ-trial.md) · [Spark recipe compatibility with the W4 checkpoint](Spark-recipe-review.md) |
| Speculative depth and reasoning settings | [DFlash2 depths on 88 GiB](DFlash-depth-trial.md) · [Reasoning effort and temperature](Parameter-trials.md) |
| GPU sharing | [20% and 50% background share across four C8 cohorts](GPU-priority-trial.md) |
| Runtime compatibility | [CUDA expandable-segments startup check](CUDA-allocator-trial.md) · [TensorFold feasibility](TensorFold-trial.md) |
| Alternative deployments | [Native Windows agent results](Native-vLLM.md) · [Historical component rankings](Historical-profile-comparison.md) |

## Run

For cold and reused prompt timing or near-full quality tests, use the [speed and capacity procedures](Speed-benchmarks.md). For inventory tools, mixed workloads, RULER, and restart checks, see the [reference suite commands](Reference-benchmarks.md#run).

## Retained evidence

Each comparison links to its workload and measurements. The repository includes [benchmark values and source hashes](data/benchmark-results.json), [historical profile summaries](data/profile-history.json), and the [model inventory](data/model-assets.json).

The [archive receipt](data/benchmark-archive.json) identifies the separately stored `n1x-ai-benchmark-archive-20261108.zip`. It contains earlier raw responses, scripts, and reports. Its `ARCHIVE-MANIFEST.json` records original paths and SHA-256 hashes. New runs write raw artifacts under the ignored `results/benchmarks/` directory. Export any local results you need before running cleanup.
