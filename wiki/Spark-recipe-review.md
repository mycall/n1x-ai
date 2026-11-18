# Spark recipe compatibility with the W4 checkpoint

The installed W4 checkpoint already has an 8-bit output head, supports the separate DFlash2 drafter, and contains MTP tensors. The Spark recipe uses different checkpoint and runtime assumptions. This reference records which ideas apply to the local weights. [Reviewed recipe revision](https://github.com/styles01/sparkrun-recipes/tree/d7e6f33e3ed173263d9b9baaec37021add8e2191) · [Inspection results and source hashes](data/spark-recipe-review-20261108.json)

## The existing target already has an 8-bit output head

The installed AutoRound checkpoint's `config.json` sets `quantization_config.dynamic["+:.*lm_head$"].bits` to **8**. Its safetensors header contains `lm_head.qweight`, `lm_head.qzeros`, and `lm_head.scales`; the packed weight alone is 635,699,200 bytes. The embedding matrix is separate and BF16, with shape `[248320, 2560]`.

The installed MyLLMBox target passes its quantization configuration to `ParallelLMHead`. The existing DFlash2 checkpoint has no separate output-head or token-embedding tensors. This already supplies the main memory-saving idea in Spark's [INT8 head patch](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/docker/patch_int8_lmhead_v3.py), although the kernel implementations differ. Porting that patch is not an unclaimed BF16-to-INT8 saving for this target; any kernel comparison would need to account for the existing packed head.

## DFlash2 depth

The DFlash2 checkpoint has an eight-token draft block. The proposer needs room for the selected depth plus one bonus token. The MyLLMBox launcher sets the depth on the command line through `DFlashTokens` and adjusts CUDA graph coverage for it. K5 and above also require the QSA ring fix. [Configuration](Configuration.md#experimental-draft-depth) · [Depth and capacity measurements](DFlash-depth-trial.md)

## BF16 recurrent state can be investigated without new weights

The selected profile and the checkpoint's `mamba_ssm_dtype` both specify FP32. The installed target's GDN state construction consumes the requested SSM dtype, and its dtype calculator resolves an explicit BF16 setting. Spark's [Flash-Next recipe](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/recipes/qwen38-flash-next-mtp3-draftvocab47k.yaml) uses BF16 recurrent state.

BF16 halves the bytes per recurrent-state element. Page padding and other allocations also contribute to runtime memory. The W4/KV19 and KV20 profiles have measured BF16 correctness and restart coverage. Their KV allocation also differs from the FP32 default, so the observed throughput cannot be attributed to precision alone. [Profile comparison](FP4-Local-AZ-trial.md#configuration)

## MTP weights are available, but HEAD2 is not ready for this checkpoint

The target index contains **1,565 `mtp.*` entries**, all in the existing model bundle. The historical MTP comparison therefore does not require another checkpoint. The selected W4 MyLLMBox launcher uses DFlash2. An MTP comparison through the older reference profile also changes runtime/configuration and must be described accordingly.

The installed `mbx_draft_head2.py` is explicitly an MTP implementation. Its source says the AutoRound head path is **not ported**; it supports a plain BF16/FP16 matrix or an NVFP4 checkpoint fallback. Our head is packed GPTQ/AutoRound INT8. Enabling `MBX_DRAFT_HEAD2` is consequently not a configuration-only optimization for this bundle. A reduced-vocabulary implementation could be developed from local weights, but requires packed-head support, calibration, token-ID mapping, and verification of its interaction with DFlash2's candidate selector if used there.

The native Windows HEAD2 reference requires its own FP4 checkpoint. [Native vLLM](Native-vLLM.md)

## Storage and measurement limits

Storage profiling is a useful secondary check because prepared PLE and LMCache already use local storage. Spark's [NVMe coalescing investigation](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/runbooks/nvme-interrupt-coalescing.md) suggests measuring small-read and restore latency, but its Linux device/service commands do not establish an applicable Windows/WSLC fix.

The receipt records model metadata and inspected safetensors headers, indexed-file presence, runtime source hashes, and the generated K3 arguments. No complete weight-file hashing, GPU startup qualification, throughput measurement, or BF16 restore test was performed. The inspection describes the November 8, 2026 runtime source.

Spark's throughput claims remain specific to its weights, runtime, workload, and memory budget. Its [122B runbook](https://github.com/styles01/sparkrun-recipes/blob/d7e6f33e3ed173263d9b9baaec37021add8e2191/runbooks/qwen-122b-v26-fp8-kv-dflash-int8.md) also has inconsistent memory arithmetic: the stated 35.55 GiB / 1,372,342-token pool implies about 27,815 bytes per token, rather than 26 bytes. Use local measurements and explicit allocations when assessing headroom.
