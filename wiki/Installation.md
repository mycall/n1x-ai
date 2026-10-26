# Installation

## Requirements

- Windows 11 ARM64 on an NVIDIA N1X system, with a working NVIDIA driver and GPU-enabled WSLC installation. Check `wslc info` and `nvidia-smi` before setup.
- 128 GiB unified memory for the supplied long-context cache profiles. The recommended dedicated GPU partition is 88 GiB, configured in the NVIDIA app. This project does not change the partition or power settings.
- Git and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`hf`) on PATH. The host Python installation serves tooling; the container has its own pinned Python/runtime environment.
- Enough SSD space for both downloaded models, the native PLE copy, container images/build layers, and the growing SSD cache. Inspect the model repository sizes before downloading; installation retains the source PLE table as well as its native copy.

Use PowerShell from the repository root. If local script execution is blocked, use the execution policy permitted on your machine, for example `powershell -ExecutionPolicy Bypass -File .\n1x.ps1 setup`.

Use a **non-administrator PowerShell** consistently for setup and serving. WSLC can use separate sessions for regular and elevated terminals, with different images, containers, and volumes. An image missing in an elevated terminal does not mean the regular session's installation was deleted. Elevation is only needed for [offline disk compaction](Configuration.md#cleanup-and-disk-reclamation).

### Proxy

Before model downloads, upstream HTTPS clones, and runtime or benchmark image builds, the scripts refresh `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, and `ALL_PROXY` from the Windows user environment, falling back to machine settings. This detects changes made by `proxy.ps1 on/off` even in an already-open terminal. It also clears stale process values when the persistent proxy is removed. No proxy address is hard-coded.

`N1X_PROXY_SOURCE` controls this check:

| Value | Behavior |
| --- | --- |
| Unset or `auto` | Refresh from Windows user/machine environment before internet work |
| `process` | Use the current terminal's proxy variables without refreshing them |

For an intentional per-terminal override:

```powershell
$env:N1X_PROXY_SOURCE = 'process'
# Return to automatic detection:
Remove-Item Env:N1X_PROXY_SOURCE -ErrorAction SilentlyContinue
```

Offline model reuse, local API tests, serving, and cleanup do not trigger this check. These settings are environment variables, not Windows PAC/WinINet discovery, and changes are checked before operations rather than monitored continuously.

Before building, the script synchronizes WSLC's Docker daemon HTTP/HTTPS proxy settings and forwards proxy variables to all build stages. A daemon proxy change requires all WSLC containers to be stopped; the script refuses to interrupt them. Run setup from an interactive terminal because WSLC session commands require a console. Empty proxy settings clear the daemon proxy and build arguments; if `proxy.ps1 off` restores a previous proxy, that restored setting is used. This routes HTTP/HTTPS requests through the proxy; it does not change the DNS server or proxy arbitrary network traffic.

When proxy synchronization replaces the daemon, the build closes that idle WSLC session afterward, preserving images and named volumes. Serving then opens a fresh session: this avoids lifecycle commands hanging on stale daemon event subscriptions. Proxy synchronization is repeated when needed for the next build; it does not globally configure arbitrary `wslc` commands.

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

Setup reuses the expected local image tags when they exist. After changing image sources or runtime patches, use `n1x.ps1 setup -Rebuild` (image presence alone does not establish source freshness). Missing images trigger a build. For native PLE, setup checks the pinned revision and required file sizes against its copy manifest; missing/incomplete copies trigger preparation. The fast PLE check is not a new checksum audit; `prepare-native-ple.ps1` performs full source/destination verification.

For manually verified downloads, add `-SkipDownload`. Advanced bypasses are `-SkipBuild` and `-SkipPleCopy`; use them only when the required images and verified native PLE volume already exist. Normal setup after `clean` reuses images and native PLE without rebuilding them.

`n1x.ps1 setup` prepares LMCache and selects `cache-dflash`. For the smaller baseline installation, use `setup.ps1` directly without `-WithLMCache`. Settings are saved in ignored `config.local.psd1`. Stop the service before setup needs to build images or prepare a new native PLE copy. Setup does not start the model; run `n1x.ps1 start` afterward.

## Start and verify

Follow the [README quick start](../README.md#quick-start) to start the service and send a request. Runtime model access is offline after setup. See [Troubleshooting](Troubleshooting.md#api-is-not-ready) for startup delays and [Development](Development.md#service-validation) for feature checks.

## DFlash2 drafter

Setup includes the DFlash2 drafter; no separate preparation command is needed. `prepare-dflash.ps1` remains an optional download-only helper for an existing installation. The BF16 weights require about 1.2 GB of disk space. See the [profile configuration](Configuration.md#dflash2).
