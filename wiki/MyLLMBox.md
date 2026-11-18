# MyLLMBox Linux runtime

The default W4 profile and the 96 GiB W4 and AZ alternatives run in a pinned MyLLMBox v5.4 Linux image with the project’s LMCache and DFlash2 adapters. Use this guide to identify the image, rebuild it, or select a candidate. For first launch, follow [Installation](Installation.md#prepared-best-profile).

## Existing installation

The launcher checks both image tag and immutable ID. The 88 GiB alternate uses its own image. The W4 profiles share model assets, while AZ requires the FP4-Local-AZ checkpoint. [Model assets](Model-assets.md)

| Profile | Image tag | Immutable image ID | GPU partition |
| --- | --- | --- | --- |
| 96 GiB W4 and AZ profiles | `n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d` | `sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc` | 96 GiB |
| 88 GiB `qwen38fn-lmcache-4k` | `n1x-ai:mbx-cache-test` | `sha256:de420cb63cedf084f8838e1e11a7db611e43418c04b3cebc756bc4a5955571aa` | 88 GiB |

The following software measurements describe the historical image; use image provenance for the exact contents of another build.

| Component | Pinned or measured value |
| --- | --- |
| Guest Python / vLLM | 3.12.3 / 0.32.0 |
| Guest Torch / CUDA | 2.13.0+cu130 / 13.0.88 |
| LMCache | 0.5.6 with local compatibility patches |
| Required WSLC version | 3.0.5.0 |
| Measured host driver / CUDA toolkit | 621.14 / 13.5.37 |
| Model and storage prerequisites | [W4 target, DFlash2, and both prepared PLE volumes](Model-assets.md) |

The host toolkit does not replace the guest toolkit. Rebuilding can produce a different image identity; the launcher rejects a tag whose ID differs from the profile.

Setup, start, and recreate can restore a missing image tag from its immutable ID or build the pinned recipe and save a new local image identity. A locally built image needs serving validation. For the W4 profiles, the loader generates the FP8 PLE map on first startup. The AZ profiles use PLE from their checkpoint. [Setup and verification](Installation.md#prepared-best-profile) · [Upstream loader](https://github.com/myllmbox/qwen38-flash-next-recipe/blob/main/run.sh)

## Rebuild LMCache and the runtime

Stop all containers before building. Preview the build without downloading or compiling:

```powershell
.\n1x.ps1 build -Profile qwen38fn-best -Rebuild -LmcacheFromSource -PrintOnly
```

Remove `-PrintOnly` to build. The command dispatches to `build.ps1 -Myllmbox` and creates a candidate image without changing the selected profile or downloading model weights.

| Option | Behavior |
| --- | --- |
| `-Rebuild` | Bypass image layer caching |
| `-LmcacheFromSource` | Compile the pinned LMCache release against the guest Torch/CUDA stack; otherwise use package installation |
| `-ImageTag n1x-ai:<name>` | Choose a candidate tag; default is `n1x-ai:mbx-cache-candidate` |

Configured serving tags cannot be overwritten by this build path. Source builds target N1X architecture `12.1a` with one compilation job. The installer checks the native extension import and preserves the vendor's core binaries/source, then applies and validates local patches. Build provenance under `/opt/n1x` records package versions, core hashes, and compiler details. See [patch validation](Development.md#builds) and [LMCache source-build guidance](https://docs.lmcache.ai/getting_started/compatibility.html).

### Upgrade dependencies

A fresh build reproduces the pinned stack; it does not automatically select newer libraries. Review these inputs together when upgrading:

- Base image digest in `Dockerfile.myllmbox-lmcache`.
- Dependency pins in `runtime/lmcache/constraints.txt` and `runtime/myllmbox/install_cache.py`.
- Patch contracts in `runtime/lmcache/` and `runtime/myllmbox/`.

Changed vendor versions or source fail validation until reviewed. Compile extensions against the new guest stack and run the [local and GPU checks](Development.md) before comparing model correctness and performance.

The [November 15 CUDA allocator trial](CUDA-allocator-trial.md) found that adding `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` alone is rejected by this image's KV-connector compatibility guard. Keep it off with the selected LMCache runtime; the CuMem alternative requires separate integration qualification.

Candidate builds also apply `runtime/myllmbox/patch_qsa_ring.py`, guarded by the audited QSA source hash. It makes the speculative raw-key ring fit power-of-two attention blocks for DFlash2 depths 5-7. The historical `mbx-cache-test` image predates this fix. Selecting another draft depth does not patch an existing image; see [experimental draft depth](Configuration.md#experimental-draft-depth).

### Select a candidate

Successful builds print their immutable image ID. Set `Image` and `ImageId` together in `config.local.psd1`, then run `setup` and `recreate` for the selected profile. Validate GPU behavior and first-attempt quality before retaining the override. Remove both overrides to return to the pinned runtime.

Runtime software and generated KV data are separate: deleting LMCache does not rebuild libraries. See [cache limits](LMCache.md#ssd-budget) and [cleanup](Configuration.md#cleanup-and-disk-reclamation). The separate [native Windows profile](Native-vLLM.md) has its own installation and dependencies.
