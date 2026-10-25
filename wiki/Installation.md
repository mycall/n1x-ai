# Installation

## Requirements

- Windows 11 ARM64 on an NVIDIA N1X system, with a working NVIDIA driver and GPU-enabled WSLC installation. Check `wslc info` and `nvidia-smi` before setup.
- 128 GiB unified memory for the supplied long-context cache profiles. The recommended dedicated GPU partition is 88 GiB, configured in the NVIDIA app. This project does not change the partition or power settings.
- Git and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`hf`) on PATH. The host Python installation serves tooling; the container has its own pinned Python/runtime environment.
- Enough SSD space for both downloaded models, the native PLE copy, container images/build layers, and the growing SSD cache. Inspect the model repository sizes before downloading; installation retains the source PLE table as well as its native copy.

Use PowerShell from the repository root. If local script execution is blocked, use the execution policy permitted on your machine, for example `powershell -ExecutionPolicy Bypass -File .\n1x.ps1 setup`.

## Setup

```powershell
.\n1x.ps1 setup
```

Setup downloads these pinned revisions:

| Model | Revision | Directory under ModelRoot |
| --- | --- | --- |
| [Main model](https://huggingface.co/Saren/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid) | `8b82f0b7abe3d1150a7827d298c75e86267636ae` | `Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid` |
| [PLE table](https://huggingface.co/Saren/Qwen3.8-Flash-Next-ple-table-fp8) | `50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14` | `ple-table-fp8` |
| [DFlash2 drafter](https://huggingface.co/incoai/Qwen3.8-Flash-Next-DFlash2), with LMCache setup | `a22a1744e85c17364dcc54a6a420af7135d4c7f6` | `Qwen3.8-Flash-Next-DFlash2` |

This calls `setup.ps1 -WithLMCache`, including DFlash2 preparation. The default ModelRoot is `~\Models`; an existing local ModelRoot is retained. Use `-ModelRoot D:\Models` to change it. Setup skips downloads when required files and Hugging Face metadata match the pinned revision and the files have not been modified since download. This is a fast completeness check, not a full checksum audit. Missing files or metadata fall back to `hf download`, which reuses completed files and available partial data.

For existing downloads, add `-SkipDownload`. Advanced reuse options are `-SkipBuild` and `-SkipPleCopy`; use them only when the required images and verified native PLE volume already exist.

`n1x.ps1 setup` builds LMCache and selects `cache-dflash`. For the smaller baseline installation, use `setup.ps1` directly without `-WithLMCache`. Settings are saved in ignored `config.local.psd1`. Stop the service before setup prepares the native PLE volume.

## Start and verify

Follow the [README quick start](../README.md#quick-start) to start the service and send a request. Runtime model access is offline after setup. See [Troubleshooting](Troubleshooting.md#api-is-not-ready) for startup delays and [Development](Development.md#service-validation) for feature checks.

## DFlash2 drafter

Setup includes the DFlash2 drafter; no separate preparation command is needed. `prepare-dflash.ps1` remains an optional download-only helper for an existing installation. The BF16 weights require about 1.2 GB of disk space. See the [profile configuration](Configuration.md#dflash2).
