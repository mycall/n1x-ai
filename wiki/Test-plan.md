# Test coverage and remaining work

This page distinguishes completed measurements from open questions. [Component review](Profile-review.md) explains the current selection; [Benchmarks](Benchmarks.md) holds the measured values and source evidence.

## Current near-full comparison

| Item | Status |
| --- | --- |
| Actual near-full inputs, thinking/xhigh, 8K output allowance | Measured: about 253,944 input tokens inside 262,144 total |
| LMCache 4K versus 8K batch, C1 cold / immediate repeat | Completed; each point 8/8 first correct; 8K faster completed batches |
| Same comparison, C8 cold | Completed; each 8/8; 4K faster |
| C2 for selected 8K combination | Unmeasured |
| 8K C8 displaced replay and SSD restart | Unmeasured in final round |
| Full-window tool selection / continuations | Earlier cache-off best passed; not transferred to the new LMCache combination |
| Current best on 96 GiB partition | Unmeasured; not ruled out |
| 1,024 / 2,048 / 8,192 quality-budget experiment | No matched accuracy conclusion; 8,192 is the serving default/cap |
| Broad depth-grid speed suite | Implemented with offline tests; no complete matched live grid |
| Coding-project-specific optimization | Out of scope by user choice |

## Next evaluation round

Prioritize a matched C2 comparison and representative appended-history tool workloads at nearly full context, then 8K C8 replay/restart. Use the [speed and capacity tools](Speed-benchmarks.md) to record actual prompts, runtime identity, first scores, cache evidence, and phase timings. Keep cold and reused work separate.

Dependency upgrades require a [candidate build and validation](MyLLMBox.md#upgrade-dependencies); deleting old LMCache data does not update libraries. Recheck correctness and performance against the pinned runtime before adopting an upgrade.

Apply the [selection criteria](Profile-review.md): diagnostic retries never replace first scores. Keep resource, restore, and scaling observations visible, including the historical failures retained in the archive.
