# Test coverage and remaining work

This page distinguishes completed measurements from open questions. [Component review](Profile-review.md) explains the current selection; [Benchmarks](Benchmarks.md) holds the measured values and source evidence.

## Measured coverage

The prefill and cold speed-grid rows below describe the historical 88 GiB/KV11 profile. Current 96 GiB evidence is identified separately.

| Item | Status |
| --- | --- |
| Actual near-full inputs, thinking/xhigh, 8K output allowance | Measured: about 253,944 input tokens inside 262,144 total |
| LMCache 4K versus 8K batch, C1 cold / immediate repeat | Completed; each point 8/8 first correct; 8K faster completed batches |
| Same comparison, C8 cold | Completed; each 8/8; 4K faster |
| C2 correctness comparison with the 8K output allowance | Unmeasured; fixed-work 512-token speed is covered separately |
| 8K C8 displaced replay and SSD restart | Unmeasured in final round |
| Near-full tool selection / continuations | [96 GiB local runtime: 24/24 C1/C2 tasks](Near-full-tools-96GiB.md), 250,002–250,419 inputs, 8K allowance; original 88 GiB runtime transfer remains open |
| Current best settings on 96 GiB partition | [KV15 campaign: 48/48 C2/C4 tool tasks](96GiB-comparison-campaign.md); promoted November 13; no matched partition-speed comparison |
| 1,024 / 2,048 / 8,192 quality-budget experiment | No matched accuracy conclusion; 8,192 is the serving default/cap |
| Fixed-work cold speed grid | [Completed](Qwen38fn-speed-matrix.md): common vLLM benchmark, C1–C8 × 4K/8K/64K/262K, three bursts per cell |
| Coding-project-specific optimization | Out of scope by user choice |

## Deferred evaluation gaps

The [96 GiB campaign](96GiB-comparison-campaign.md) is closed with KV15/batch8K/LMCache selected as best. The gaps above remain open; no further campaign on this stack is scheduled. If revisited, use the [speed and capacity tools](Speed-benchmarks.md) to record actual prompts, runtime identity, first scores, cache evidence, and phase timings. Keep cold and reused work separate.

Dependency upgrades require a [candidate build and validation](MyLLMBox.md#upgrade-dependencies); deleting old LMCache data does not update libraries. Recheck correctness and performance against the pinned runtime before adopting an upgrade.

Apply the [selection criteria](Profile-review.md): diagnostic retries never replace first scores. Keep resource, restore, and scaling observations visible, including the historical failures retained in the archive.
