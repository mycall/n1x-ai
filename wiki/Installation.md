# Installation

Choose the installation path for the runtime you intend to use. Best prepares its runtime around existing model and PLE assets; the original WSLC reference setup can download and build its own stack.

## Requirements

- Windows 11 ARM64 on an NVIDIA N1X system, with a working NVIDIA driver and GPU-enabled WSLC installation. Check `wslc info` and `nvidia-smi` before setup.
- 128 GiB unified memory for the supplied long-context cache profiles. The recommended dedicated GPU partition is 88 GiB, configured in the NVIDIA app. This project does not change the partition or power settings.
- Git and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`hf`) on PATH. The host Python installation serves tooling; the container has its own pinned Python/runtime environment.
- SSD space for [model assets](Model-assets.md), runtime/build layers, and the configured [cache budget](LMCache.md#ssd-budget).

Use PowerShell from the repository root. If local script execution is blocked, use the execution policy permitted on your machine, for example `powershell -ExecutionPolicy Bypass -File .\n1x.ps1 setup`.

Use a **non-administrator PowerShell** for setup and serving. Regular and elevated WSLC sessions can have different images and volumes. Firewall changes request elevation separately; [offline compaction](Configuration.md#cleanup-and-disk-reclamation) runs in an elevated terminal after detaching the disk.

## Setup

| Installation | Entry point | What it does |
| --- | --- | --- |
| Prepared best or 4K alternate | `n1x.ps1 setup -Profile qwen38fn-best` | Validate assets, restore/build a missing runtime, and create an empty LMCache volume if missing |
| Original WSLC reference | `n1x.ps1 setup -Profile qwen38fn-cache-dflash` | Download assets, build missing images, prepare native PLE, and select this reference as the local default |
| Native Windows reference | `n1x.ps1 setup -Profile qwen38fn-myllmbox` | Validate the separately installed native runtime and FP4 model |

### Prepared best profile

First satisfy the [MyLLMBox prerequisites](MyLLMBox.md#existing-installation). Create `config.local.psd1` from `config.local.example.psd1` and set your model path and default; see [configuration precedence](Configuration.md).

```powershell
.\n1x.ps1 setup -Profile qwen38fn-best
```

Setup validates target shards, drafter, prepared PLE volumes, WSLC version, and GPU partition before preparing the runtime. If the image tag is missing, it restores it from the configured image ID when available; otherwise it builds the pinned repository recipe under a unique `n1x-ai:mbx-setup-*` tag and saves `Image` and `ImageId` in `config.local.psd1`, preserving other local settings. Existing tags with a different ID are rejected. It also creates the configured LMCache volume if absent. `start` and `recreate` run this same preparation automatically; `restart` only validates the existing installation. Preview commands make no changes. Builds require all containers to be stopped.

Setup does not download best-profile weights or generate missing PLE data. These assets must already be prepared; this is not a complete fresh-machine bootstrap. A locally built runtime has passed the image build checks but has not inherited the historical GPU qualification: run `n1x.ps1 wait` and `n1x.ps1 test` after starting it. See [runtime builds](MyLLMBox.md#rebuild-lmcache-and-the-runtime) for explicit candidate upgrades.

`-ModelRoot D:\Models` overrides the path for that command. Save the path in `config.local.psd1` to use it for subsequent best-profile commands.

### Original WSLC reference

```powershell
.\n1x.ps1 setup -Profile qwen38fn-cache-dflash
```

The [model inventory](Model-assets.md#pinned-sources) lists the target, PLE source, and DFlash2 download revisions.

This calls `setup.ps1 -WithLMCache`, including DFlash2 preparation. The default ModelRoot is `~\Models`; an existing local ModelRoot is retained. Use `-ModelRoot D:\Models` to change it. Setup skips downloads when required files and Hugging Face metadata match the pinned revision and the files have not been modified since download. This is a fast completeness check, not a full checksum audit. Missing files or metadata fall back to `hf download`, which reuses completed files and available partial data.

Setup reuses the expected local image tags when they exist. After changing image sources or runtime patches, use `n1x.ps1 setup -Profile qwen38fn-cache-dflash -Rebuild` (image presence alone does not establish source freshness). Missing images trigger a build. For native PLE, setup checks the pinned revision and required file sizes against its copy manifest; missing/incomplete copies trigger preparation. The fast PLE check is not a new checksum audit; `prepare-native-ple.ps1` performs full source/destination verification.

For manually verified downloads, add `-SkipDownload`. Advanced bypasses are `-SkipBuild` and `-SkipPleCopy`; use them only when the required images and verified native PLE volume already exist. Normal setup after `clean` reuses images and native PLE without rebuilding them.

`n1x.ps1 setup -Profile qwen38fn-cache-dflash` prepares LMCache and selects `qwen38fn-cache-dflash`; it changes the local default to that reference. For the smaller baseline installation, use `setup.ps1` directly without `-WithLMCache`. Settings are saved in ignored `config.local.psd1`. Stop the service before setup needs to build images or prepare a new native PLE copy. Setup does not start the model; run `n1x.ps1 start` afterward.

## Start and verify

Follow the [README quick start](../README.md#quick-start) to start the service and send a request. Runtime model access is offline after setup. See [Troubleshooting](Troubleshooting.md#api-is-not-ready) for startup delays and [Development](Development.md#service-validation) for feature checks.

## DFlash2 drafter

The reference setup includes DFlash2. `prepare-dflash.ps1` is an optional download-only helper for an existing installation. See [model assets](Model-assets.md) for the required files and [Configuration](Configuration.md#dflash2) for serving settings.

## Proxy

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
