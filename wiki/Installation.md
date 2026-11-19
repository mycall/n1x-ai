# Installation

For the default server, prepare the W4 target and DFlash2 drafter, run setup, then start and test the API. Use a **non-administrator PowerShell** in the repository root. Elevated and regular WSLC sessions can have different images and volumes.

## Requirements

| Check | Default MyLLMBox Linux profile |
| --- | --- |
| Host | Windows 11 ARM64, NVIDIA RTX N1X, working NVIDIA driver, GPU-enabled WSLC. Verify with `wslc info` and `nvidia-smi`. The profile pins WSLC 3.0.5.0. |
| Memory | 128 GiB unified memory with a 96 GiB dedicated GPU partition. Set the partition in the NVIDIA app. The 88 GiB alternate and original cache reference need their own partition settings. |
| Tools | Git and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`hf`) on PATH. The runtime has its own pinned Python environment. |
| SSD | Room for model files, image/build layers, and prompt cache. If PLE needs preparing, allow about 49 GiB each for the host source, Linux copy, and generated map. [Model assets](Model-assets.md) · [Cache budget](LMCache.md#ssd-budget) |

If local PowerShell script execution is restricted, use the policy permitted on your machine. For example, run `powershell -ExecutionPolicy Bypass -File .\n1x.ps1 setup`.

## Setup

### Prepared best profile

1. Place the pinned W4 target and DFlash2 checkpoint under your model directory. Setup requires the indexed target shards and drafter to exist. [Pinned sources and directory names](Model-assets.md#pinned-sources)
2. The default model directory is `~\models`. To change it, copy `config.local.example.psd1` to `config.local.psd1` and edit `ModelRoot`. In an existing installation, edit the existing file. A command-line `-ModelRoot D:\Models` applies only to that invocation. [Configuration](Configuration.md)
3. Prepare the default profile. Stop all WSLC containers first if an image build is needed.

```powershell
.\n1x.ps1 setup -Profile qwen38fn-best
```

Setup checks the weights, WSLC version, and GPU partition. If the runtime tag is missing, it restores it from the configured image ID or builds the pinned recipe and saves the new image identity locally. A tag with a different ID fails validation. [Runtime image details](MyLLMBox.md#existing-installation)

Setup checks the FP8 PLE copy manifest and sizes, resumes the pinned source download if needed, and verifies the copy into its Linux volume with SHA-256. It creates missing runtime-cache and LMCache volumes. The model loader builds the PLE map on first start.

`start` and `recreate` also prepare missing runtime assets. `restart` requires an existing installation. To use pre-provisioned assets, `-SkipDownload` requires the host PLE source when a copy is needed, `-SkipPleCopy` requires a prepared PLE volume, and `-SkipBuild` requires a runtime image.

## Start and verify

```powershell
.\n1x.ps1 start -Profile qwen38fn-best
.\n1x.ps1 test -Profile qwen38fn-best
```

Start waits for readiness. Cold loading, PLE map generation, and kernel compilation can take several minutes. The smoke test checks the running API, including after a local rebuild. Once ready, use `http://127.0.0.1:8000/v1` with model ID `qwen/qwen38fn-best`. [Connect a client](Configuration.md#agent-clients) · [Diagnose startup](Troubleshooting.md#api-is-not-ready)

## Other installation paths

### Original WSLC reference

```powershell
.\n1x.ps1 setup -Profile qwen38fn-cache-dflash
```

This runs `setup.ps1 -WithLMCache`, downloads the pinned weights, builds missing reference images, prepares native PLE, and **sets this reference as the local default**. Start it with `n1x.ps1 start`. For the smaller baseline, use `setup.ps1` without `-WithLMCache`.

The model path defaults to `~\Models`. Reference setup retains an existing local path or accepts `-ModelRoot`. It reuses downloads when file and revision metadata match. Missing files resume through `hf download`. PLE copy and verification run the C# tool with the `mcr.microsoft.com/dotnet/sdk:10.0` WSLC image. Pull it before offline setup with `wslc pull mcr.microsoft.com/dotnet/sdk:10.0`. The PLE fast check uses the revision, manifest, and file sizes. Use `prepare-native-ple.ps1` for full source/destination verification.

Stop serving before building images or preparing a new PLE copy. After changing image sources or patches, pass `-Rebuild` to reference setup. Existing tags are otherwise reused. Use `-SkipDownload`, `-SkipBuild`, or `-SkipPleCopy` only for assets already verified on this installation.

### Native Windows reference

Install the separate ARM64 runtime and FP4 model, then validate them with `n1x.ps1 setup -Profile qwen38fn-myllmbox`. [Native installation and configuration](Native-vLLM.md#installation-and-configuration)

### DFlash2 drafter

Reference setup includes the drafter. For an existing installation, `prepare-dflash.ps1` downloads it separately. [Model assets](Model-assets.md)

## Proxy

Before downloads, clones, and image builds, the scripts load `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, and `ALL_PROXY` from the Windows user environment, falling back to machine settings. This picks up persistent changes in an open terminal. Offline serving and local tests skip this check.

| Desired behavior | PowerShell setting |
| --- | --- |
| Refresh from Windows (default) | Leave `N1X_PROXY_SOURCE` unset or set it to `auto` |
| Use the terminal’s proxy variables | `$env:N1X_PROXY_SOURCE = 'process'` |
| Return to automatic detection | `Remove-Item Env:N1X_PROXY_SOURCE -ErrorAction SilentlyContinue` |

Builds synchronize the WSLC Docker daemon’s HTTP/HTTPS proxy and pass settings to each build stage. Use an interactive terminal and stop WSLC containers before a daemon proxy change. Empty persistent settings clear the daemon proxy. If synchronization replaces the daemon, the build closes its idle session so serving opens a fresh one. Images and named volumes persist.
