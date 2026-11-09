# MyLLMBox Linux runtime

The selected profiles use a pinned MyLLMBox v5.4 image with the project's LMCache and DFlash2 adapters. This page covers runtime prerequisites, reproducible builds, and dependency upgrades. See [Configuration](Configuration.md#profiles) for serving settings, [Model assets](Model-assets.md) for files and volumes, and [Component review](Profile-review.md) for the selection rationale.

## Existing installation

`qwen38fn-best` and `qwen38fn-lmcache-4k` share the runtime and model assets below. Loading is offline.

| Component | Pinned or measured value |
| --- | --- |
| Image tag | `n1x-ai:mbx-cache-test` |
| Required image ID | `sha256:de420cb63cedf084f8838e1e11a7db611e43418c04b3cebc756bc4a5955571aa` |
| Guest Python / vLLM | 3.12.3 / 0.32.0 |
| Guest Torch / CUDA | 2.13.0+cu130 / 13.0.88 |
| LMCache | 0.5.6 with local compatibility patches |
| Required WSLC version | 3.0.5.0 |
| Required GPU partition | 88 GiB |
| Measured host driver / CUDA toolkit | 621.14 / 13.5.37 |
| Model and storage prerequisites | [W4 target, DFlash2, and both prepared PLE volumes](Model-assets.md) |

The host toolkit does not replace the guest toolkit. Rebuilding can produce a different image identity; the launcher rejects a tag whose ID differs from the profile.

Use the [prepared-installation setup](Installation.md#prepared-best-profile) to validate these prerequisites and create an empty LMCache volume. Missing weights, runtime images, or prepared PLE data require restoration or preparation separately. The current scripts do not bootstrap the entire best installation from an empty machine.

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

### Select a candidate

Successful builds print their immutable image ID. Set `Image` and `ImageId` together in `config.local.psd1`, then run `setup` and `recreate` for the selected profile. Validate GPU behavior and first-attempt quality before retaining the override. Remove both overrides to return to the pinned runtime.

Runtime software and generated KV data are separate: deleting LMCache does not rebuild libraries. See [cache limits](LMCache.md#ssd-budget) and [cleanup](Configuration.md#cleanup-and-disk-reclamation). The separate [native Windows profile](Native-vLLM.md) has its own installation and dependencies.
