# Installation

## Requirements

- Windows 11 ARM64 on an NVIDIA N1X system, with a working NVIDIA driver and GPU-enabled WSLC installation. Check `wslc info` and `nvidia-smi` before setup.
- 128 GiB unified memory for the supplied long-context cache profiles. The recommended dedicated GPU partition is 88 GiB, configured in the NVIDIA app. This project does not change the partition or power settings.
- Git and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`hf`) on PATH. The host Python installation serves tooling; the container has its own pinned Python/runtime environment.
- Enough SSD space for both downloaded models, the native PLE copy, container images/build layers, and the growing SSD cache. Inspect the model repository sizes before downloading; installation retains the source PLE table as well as its native copy.

Use PowerShell from the repository root. If local script execution is blocked, use the execution policy permitted on your machine, for example `powershell -ExecutionPolicy Bypass -File .\setup.ps1 -WithLMCache`.

## Setup

```powershell
.\setup.ps1 -WithLMCache
```

Setup downloads these pinned revisions:

| Model | Revision | Directory under ModelRoot |
| --- | --- | --- |
| [Main model](https://huggingface.co/Saren/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid) | `8b82f0b7abe3d1150a7827d298c75e86267636ae` | `Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid` |
| [PLE table](https://huggingface.co/Saren/Qwen3.8-Flash-Next-ple-table-fp8) | `50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14` | `ple-table-fp8` |

The default ModelRoot is the current user's `models` directory. Use `-ModelRoot D:\Models` to change it. Rerun setup after interrupted downloads; `hf` reuses completed files and available partial data.

For existing downloads, add `-SkipDownload`. Advanced reuse options are `-SkipBuild` and `-SkipPleCopy`; use them only when the required images and verified native PLE volume already exist.

With `-WithLMCache`, setup selects `cache-mtp`. Omit it to build and select `baseline`. Settings are saved in ignored `config.local.psd1`.

## Start and verify

Follow the [README quick start](../README.md#quick-start) to start the service and send a request. Runtime model access is offline after setup. See [Troubleshooting](Troubleshooting.md#api-is-not-ready) for startup delays and [Development](Development.md#service-validation) for feature checks.

## Optional DFlash2 drafter

`prepare-dflash.ps1` downloads [incoai/Qwen3.8-Flash-Next-DFlash2](https://huggingface.co/incoai/Qwen3.8-Flash-Next-DFlash2) revision `a22a1744e85c17364dcc54a6a420af7135d4c7f6` into the configured ModelRoot. The BF16 weights require about 1.2 GB of disk space. This download is separate from standard setup; see the [experimental profile](Configuration.md#dflash2).
