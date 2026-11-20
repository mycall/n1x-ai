# vLLM 0.33 on N1X

The deployment under test is `qwen38fn-best`: Qwen3.8-Flash-Next W4A16, external FP8 PLE, DFlash2 K3, and LMCache multiprocess restore on a 96 GiB partition. The trial uses the existing target and DFlash2 weights.

## Versions and artifacts

| Artifact | Version or immutable reference |
| --- | --- |
| Project runtime tested for compression | MyLLMBox v5.4, vLLM 0.32.0, Torch 2.13.0, LMCache 0.5.6 |
| Official vLLM candidate | `vllm/vllm-openai@sha256:e3481489818d3e563cae517b84ab959cc8b69f85a9fbb771c189140131ffc65c`, Linux ARM64 0.33.0 |
| Upstream 0.33 source | `4ba787ec9959e566d3b587a796dff07673324da5` |

PyPI publishes the final 0.33.0 ARM64 wheel with Torch 2.14.0. The project's extension and patch contracts pin a different Torch/vLLM combination. Its packaged MBX loader and asynchronous PLE library are vendor components. The existing image should be retained for comparisons and rollback. [0.33.0 package](https://pypi.org/project/vllm/0.33.0/) · [Tagged source](https://github.com/vllm-project/vllm/tree/v0.33.0) · [Project build contracts](MyLLMBox.md#upgrade-dependencies)

## Why stock 0.33 rejects DFlash2

Both images ran on the same ARM64 N1X with the same mounted target and drafter. The project's patched 0.32 image accepted DFlash2 K3. Stock 0.33 identified both model architectures, then rejected the combination during engine configuration. Running `vllm serve /model --config /profiles/qwen38fn-best.yaml` in stock 0.33 reproduced the same failure before loading weights. Its Qwen4Exp validator allows `mtp`, `ngram` and `ngram_gpu`. That check applies on either CPU architecture. [Upstream validator](https://github.com/vllm-project/vllm/blob/v0.33.0/vllm/model_executor/models/config.py#L1051-L1059) · [Probe and recipe results](data/vllm-033-compat-20261120.json)

Our 0.32 build adds `dflash` to this validator and installs an adapter in the target model. The drafter consumes completed outputs from target layers 5, 15, 25, 35 and 45, averaged over the model's hyper-connection streams. Changing the allowed methods alone supplies none of those features. A 0.33 build needs compatible target capture and a check that speculative tokens are actually accepted during generation. The existing patch verifies the exact 0.32 target source before editing it. [Project build patch](../runtime/myllmbox/patch_dflash.py) · [Target capture implementation](../runtime/native/n1x_dflash_capture.py)

Both images passed a BF16 matrix multiply and the vLLM FP8 quantization probe on SM 12.1, with identical relative RMS error of 0.0255. Both packaged LMCache 0.5.6. The patched image registered `MbxModelLoader` and contained the asynchronous PLE library. Stock 0.33 lacked both dependencies of the current W4 recipe. These checks cover configuration and individual GPU operations. The candidate produced no inference or restore timings. [Repeatable image probe](../benchmarks/vllm_compat.py)

## Other changes worth evaluating

**Next timing comparison.** Resume relative on/off testing when a native AMD64 vLLM 0.33 environment is available. This checkout's Windows host is ARM64 and its Linux candidate is ARM64 under WSLC. Record the native machine, GPU, driver, package build and model hashes. Reuse the same 15 GiB pool, KV salts, cold and restored prefixes, and alternating trial order within each environment. Rebuild or port the PLE adapter to that runner's reader ABI and pass byte parity before timing it.

**0.34 native PLE disk offload** is the most relevant follow-up. Qwen4Exp on CUDA can read rows from file-backed checkpoint tensors with `--engram-config '{"disk_offload": true}'`. Our local W4 index has 224,454 tensors across 68 shards and zero n-gram embedding table entries. Its FP8 table lives in a separate volume. An isolated combined checkpoint view or an external-table loader port is needed before comparing native disk offload with the MBX reader. Measure repeated and newly appended material with the same 15 GiB pool. [Upstream Engram guide](https://github.com/vllm-project/vllm/blob/v0.34.0/docs/features/engram.md) · [Local PLE findings](Compression.md)

**DFlash and restore fixes in 0.34** include a FULL CUDA graph acceptance fix, an LMCache MP connector change for extensible KV caches, and Qwen3.8 loading fixes. Exercise acceptance counters, tool-call continuation and post-restart SSD hits in a separate namespace. A correct reply alone does not demonstrate restore. The Qwen QSA source in both 0.33 and 0.34 retains the BF16/FP8-e4m3 main-KV restriction. [0.34 release](https://github.com/vllm-project/vllm/releases/tag/v0.34.0) · [0.34 QSA implementation](https://github.com/vllm-project/vllm/blob/v0.34.0/vllm/models/qwen4_exp/nvidia/qsa.py)

The blazux DGX Spark recipe is a reference for a **patched** 0.33 port. It adds external PLE access, QSA FP8 KV and a Qwen4Exp DFlash capture adapter. Its NVIDIA ModelOpt hybrid patches and checkpoint differ from the default GPTQ/AutoRound W4 deployment here. Validate W4 scales, the N1X kernel path, and LMCache serialization separately. [DGX Spark Dockerfile](https://github.com/blazux/qwen3.8-flash-DGX/blob/main/Dockerfile)
