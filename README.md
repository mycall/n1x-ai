# n1x-ai

Run a local, OpenAI-compatible Qwen3.8 Flash Next server on NVIDIA RTX N1X and Windows ARM64. This repository provides PowerShell commands for model preparation, container builds, service management, client registration, and benchmarks. It includes DFlash2 speculative decoding and LMCache integration for reusing prompt state.

The default profile is `qwen38fn-best`, using the MyLLMBox Linux runtime through Windows Subsystem for Linux Containers (WSLC). Reference profiles support other configurations and a native Windows runtime. See the [profile comparison](wiki/Profile-review.md) for the selection and its measured limits.

## Quick start

Read [Installation](wiki/Installation.md) first. The default profile requires a prepared runtime, model files, PLE data, and the documented GPU partition. Its `setup` command validates those assets and creates an empty LMCache volume if needed; it does not bootstrap a fresh installation.

From a non-administrator PowerShell in this repository:

```powershell
.\n1x.ps1 setup
.\n1x.ps1 start
.\n1x.ps1 wait
.\n1x.ps1 test
```

The default API is **`http://127.0.0.1:8000/v1`**, with model ID **`qwen/qwen38fn-best`**. Use the [request example and client setup](wiki/Configuration.md#agent-clients) to connect applications. [AGENTS.md](AGENTS.md) describes reasoning, output budgets, and tool-call handling.

## Daily use

```powershell
.\n1x.ps1 list profiles
.\n1x.ps1 status
.\n1x.ps1 logs
.\n1x.ps1 stop
```

Set local paths and the default profile in `config.local.psd1`; see [Configuration](wiki/Configuration.md). Use `recreate` after changing runtime settings. Start and stop manage this checkout's model entries in supported clients without changing their selected defaults.

## Documentation

- [Install and prepare the runtime](wiki/Installation.md)
- [Configure profiles, clients, networking, and cleanup](wiki/Configuration.md)
- [Review benchmark results and the top ten combinations](wiki/Profile-review.md)
- [Review the current 96 GiB best-profile selection](wiki/96GiB-comparison-campaign.md)
- [Compare historical 88 GiB read/write speed across C1–C8 and 4K–262K](wiki/Qwen38fn-speed-matrix.md)
- [Browse the documentation](wiki/Home.md), including builds, model files, cache limits, and troubleshooting

## License

Project scripts and original changes use the [MIT license](LICENSE). [Third-party notices](NOTICE.md) cover upstream code and separate model licenses. Model weights are not included in this repository.
