# Spark recipe review using installed assets

Initially reviewed November 8, 2026 against [styles01/sparkrun-recipes at d7e6f33](https://github.com/styles01/sparkrun-recipes/tree/d7e6f33e3ed173263d9b9baaec37021add8e2191), this checkout, local checkpoint metadata, and source copied from the stopped serving container. **No models were downloaded, no inference ran, and no serving defaults changed during that review.** It was a feasibility review. [Evidence receipt](data/spark-recipe-review-20261108.json).

The subsequent [DFlash2 depth trial](DFlash-depth-trial.md) implements the setting, records K1/K3/K5/K7 measurements, and fixes the QSA ring constraint found during startup. The findings below describe the initial static review.

## Findings

### 1. The existing target already has an 8-bit output head

The installed AutoRound checkpoint's `config.json` sets `quantization_config.dynamic["+:.*lm_head$"].bits` to **8**. Its safetensors header contains `lm_head.qweight`, `lm_head.qzeros`, and `lm_head.scales`; the packed weight alone is 635,699,200 bytes. The embedding matrix is separate and BF16, with shape `[248320, 2560]`.

The installed MyLLMBox target passes its quantization configuration to `ParallelLMHead`. The existing DFlash2 checkpoint has no separate output-head or token-embedding tensors. This already supplies the main memory-saving idea in Spark's [INT8 head patch](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/docker/patch_int8_lmhead_v3.py), although the kernel implementations differ. Porting that patch is not an unclaimed BF16-to-INT8 saving for this target; any kernel comparison would need to account for the existing packed head.

### 2. DFlash2 depth is the most direct new runtime experiment

All 68 indexed target files are present, as is the existing 1,206,140,008-byte DFlash2 checkpoint. Its metadata specifies an eight-token draft block. The installed DFlash2 layer constructs its convolution block with `1 + num_speculative_tokens`, and the proposer similarly sizes query buffers from the configured depth. These source paths make **K1/K3/K5/K7** reasonable candidates for startup and correctness qualification with the same weights. They do not establish that every candidate runs correctly or faster.

There is a launcher constraint: [Get-N1xMyllmboxArguments](../scripts/myllmbox.ps1) hardcodes `num_speculative_tokens=3` and passes it on the command line, overriding the YAML. CUDA graph capture sizes and their endpoint also use `4 * MaxSequences`, matching K3 plus its bonus token. An offline argument-generation check confirmed K3 and capture endpoint 32 for eight slots.

A depth experiment therefore needs an isolated launch or an explicit launcher setting, suitable graph capture coverage, and validation of recurrent-state/cache geometry. Editing only `profiles/qwen38fn-best.yaml` would not perform the intended comparison. Keep K3 as the baseline and use separate cache namespaces for candidates.

### 3. BF16 recurrent state can be investigated without new weights

The selected profile and the checkpoint's `mamba_ssm_dtype` both specify FP32. The installed target's GDN state construction consumes the requested SSM dtype, and its dtype calculator resolves an explicit BF16 setting. Spark's [Flash-Next recipe](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/recipes/qwen38-flash-next-mtp3-draftvocab47k.yaml) uses BF16 recurrent state.

BF16 would halve the bytes for those recurrent-state elements; it would not halve total KV, model memory, or process memory. Kernel support, full-context correctness, and LMCache export/restore remain live-test requirements. Keep RecoverSSM off and hold draft depth, indexer precision, and prefill batch fixed for the first comparison. Use a distinct cache namespace and revalidate layout rather than reusing FP32 entries.

### 4. MTP weights are available, but HEAD2 is not ready for this checkpoint

The target index contains **1,565 `mtp.*` entries**, all in the existing model bundle. The historical MTP comparison therefore does not require another checkpoint. Both retained WSLC runtime images are present, but the selected MyLLMBox launcher currently rejects MTP; its supported path requires DFlash2. An MTP comparison through the older reference profile also changes runtime/configuration and must be described accordingly.

The installed `mbx_draft_head2.py` is explicitly an MTP implementation. Its source says the AutoRound head path is **not ported**; it supports a plain BF16/FP16 matrix or an NVFP4 checkpoint fallback. Our head is packed GPTQ/AutoRound INT8. Enabling `MBX_DRAFT_HEAD2` is consequently not a configuration-only optimization for this bundle. A reduced-vocabulary implementation could be developed from local weights, but requires packed-head support, calibration, token-ID mapping, and verification of its interaction with DFlash2's candidate selector if used there.

The separate native `Qwen3.8-Flash-Next-FP4-Local` checkpoint is absent, consistent with the [retirement record](Model-assets.md#local-retirement-record). The earlier suggestion to start with that native HEAD2 profile does not meet the current installed-assets constraint. EXL3 and alternate large checkpoints are also outside this review's experiment shortlist.

## Recommended experiment order

| Order | Work using existing weights | What it resolves |
| ---: | --- | --- |
| 1 | Matched best/4K-alternate speed and correctness comparison | Establishes a reliable local baseline before new runtime changes |
| 2 | DFlash2 K1/K3/K5/K7, after fixing the launch override for experiments | Tests whether additional accepted tokens repay drafting, verification, and state costs |
| 3 | FP32 versus BF16 SSM at the winning qualified depth | Measures state savings against correctness and restore behavior |
| 4 | Existing-weight MTP baseline, then separately scoped head work if justified | Determines whether an MTP engineering investment is worthwhile |

Use C1/C2 first, then C8; cover short, 32K, 128K, and near-full contexts. The [speed suite](Speed-benchmarks.md) already checks fixed output counts, rendered input lengths, cold-cache evidence, and attributable timing. Use 512-1,024 tokens for initial speed windows and separate 8,192-token allowances for completed quality tasks, always reserving output within the context window. The newer [C2/C8 results](GPU-priority-trial.md) cover approximately 11K inventory sessions; they do not fill the near-full comparison gap.

Retain per-position acceptance where available, actual scheduled concurrency, queue/response latency, memory headroom, and continuous clocks/power. Preserve first-attempt failures. The [xhigh/0.6 request candidate](Parameter-trials.md) is supported by bounded local correctness results; use consistent request parameters within each comparison and do not combine its variable-length task timing with fixed-output decode rates.

Storage profiling is a useful secondary check because prepared PLE and LMCache already use local storage. Spark's [NVMe coalescing investigation](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/runbooks/nvme-interrupt-coalescing.md) suggests measuring small-read and restore latency, but its Linux device/service commands do not establish an applicable Windows/WSLC fix.

## Evidence limits

The receipt records model metadata and inspected safetensors headers, indexed-file presence, runtime source hashes, and the generated K3 arguments. No complete weight-file hashing, GPU startup qualification, throughput measurement, or BF16 restore test was performed. The serving container was stopped before and after inspection. Runtime source inspection used local copies from that container; it did not pull an image.

Spark's throughput claims remain specific to its weights, runtime, workload, and memory budget. Its [122B runbook](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/runbooks/qwen-122b-v26-fp8-kv-dflash-int8.md) also has inconsistent memory arithmetic: the stated 35.55 GiB / 1,372,342-token pool implies about 27,815 bytes per token, rather than 26 bytes. Use local measurements and explicit allocations when assessing headroom.
