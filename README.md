# n1x-ai

Run a local, OpenAI-compatible Qwen3.8 Flash Next server on NVIDIA RTX N1X and Windows ARM64. This repository provides PowerShell commands for model preparation, container builds, service management, client registration, and benchmarks. It includes DFlash2 speculative decoding and LMCache integration for reusing prompt state.

The default profile is `qwen38fn-best`, using the MyLLMBox Linux runtime through Windows Subsystem for Linux Containers (WSLC). Reference profiles support other configurations and a native Windows runtime. See the [profile comparison](wiki/Profile-review.md) for the selection and its measured limits.

## Quick start

Follow [Installation](wiki/Installation.md) to check the GPU partition and place the pinned W4 target and DFlash2 drafter under your model directory. Setup validates those weights, restores or builds the runtime, prepares missing PLE data, and creates the cache volumes.

From a non-administrator PowerShell in this repository:

```powershell
.\n1x.ps1 setup
.\n1x.ps1 start
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

Set local paths and the default profile in `config.local.psd1`; see [Configuration](wiki/Configuration.md). `start` applies changed container settings and waits for API readiness; use `start -NoWait` to return after launch. Start and stop manage this checkout's model entries in supported clients without changing their selected defaults.

## Documentation

- [Server guide](wiki/Home.md) for installation, daily operation, and troubleshooting
- [Serving profiles](wiki/Profile-review.md) for the default and workload-specific choices
- [Benchmark results](wiki/Benchmarks.md) for measured throughput, correctness, and cache recovery

## License

Project scripts and original changes use the [MIT license](LICENSE). [Third-party notices](NOTICE.md) cover upstream code and separate model licenses. Model weights are not included in this repository.

### Infernix on N1X

Clone the sibling engine checkout on branch `n1x`. Its external artifacts go under the configured model root. Build the ARM64 CUDA 13.5 server, stage the n-gram into a WSLC volume, then start and test it:

```powershell
git clone --branch n1x https://github.com/mycall/Infernix-dgx-spark-gb10.git ../Infernix-dgx-spark-gb10
./n1x.ps1 build -Profile infernix-hc4
./n1x.ps1 setup -Profile infernix-hc4
./n1x.ps1 start -Profile infernix-hc4
./n1x.ps1 test -Profile infernix-hc4
```

Use `http://127.0.0.1:8001/v1` with model ID `infernix-hc4`. This profile uses DFlash2 K3, eight lanes, and eager CUDA execution. Select a different engine checkout or volume with `InfernixRoot` or `InfernixVolume` in `config.local.psd1`. The running model owns the GPU; stop it before starting another large engine.
