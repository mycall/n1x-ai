# Development

## Builds

```powershell
.\build.ps1 -PrintOnly
.\build.ps1 -WithLMCache
# Rebuild only the cache image against an existing main image:
.\build.ps1 -CacheOnly
```

The main recipe comes from the upstream `magi-v5-public` revision pinned in `build.ps1`. The build downloads that source into ignored `upstream/`. `Dockerfile.base` supplies the base environment; `Dockerfile.lmcache` adds the constrained cache dependencies and local patches from `runtime/lmcache/`.

Keep dependencies and model revisions pinned. Upgrades require checking patch source guards, cross-process cache transfers, model correctness, and memory behavior together. Do not treat successful patch application alone as runtime validation.

## Local checks

With Python on PATH:

```powershell
.\check.ps1
```

This parses PowerShell, checks configuration/launch behavior, and runs CPU unit tests. GitHub Actions runs these checks on Windows. They require neither model weights nor a GPU.

## GPU integration

Stop model services first; these tests allocate GPU memory. Build the cache image, then run:

```powershell
wslc run --rm --gpus all --volume "${PWD}/tests:/tests:ro" `
    --entrypoint python n1x-ai:lmcache /tests/gpu_segmented.py
wslc run --rm --gpus all --volume "${PWD}/tests:/tests:ro" `
    --entrypoint python n1x-ai:lmcache /tests/gpu_cache_roundtrip.py
```

The segmented test checks shared aliases, physical segment boundaries, and byte integrity. The cache roundtrip test checks concurrent restore admission and exact restored bytes.

## Service validation

With the [service running](Configuration.md#lifecycle):

```powershell
.\n1x.ps1 test
.\n1x.ps1 test -Suite features
.\n1x.ps1 test -Suite context
```

Context checks use bounded default lengths. Validate larger contexts, simultaneous restores, and combined vision workloads against application requirements. Test output stays in ignored `.state/checks`; see [Benchmarks](Benchmarks.md#run) for performance and accuracy suites.

## Repository layout

| Path | Purpose |
| --- | --- |
| `setup.ps1`, `build.ps1` | Download and build entry points |
| `n1x.ps1`, `scripts/` | Service lifecycle, configuration, memory monitor |
| `profiles/` | Serving profiles and MTP configuration |
| `runtime/lmcache/` | Cache supervisor, compatibility modules, patch scripts, constraints |
| `tests/`, `test.ps1`, `check.ps1` | Focused validation |
| `benchmarks/`, `benchmark.ps1` | Separate API benchmark client; [usage and results](Benchmarks.md) |
| `wiki/` | User and maintenance documentation |
| `licenses/`, `NOTICE.md` | Third-party notices |
