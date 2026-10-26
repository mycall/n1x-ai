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

The patch scripts share `runtime/lmcache/n1x_patch.py`: every replacement requires one match, section boundaries must be unique and ordered, and edited files must compile before being written. Missing or ambiguous targets fail with the patch name and file path, including when Python optimization is enabled. Apply VMM before segmented; both scripts check this ordering because VMM's validation rewrite would otherwise erase the segmented initialization hook.

The cache image build runs `verify_patches.py` after all patches. It compiles the touched files and local helpers, checks the final hooks, and imports the IPC definitions and local compatibility modules without constructing GPU allocations. These checks catch source and import failures; the GPU integration tests below still validate transfers, aliases, and restored bytes.

## Local checks

With Python on PATH:

```powershell
.\check.ps1
```

This parses PowerShell, checks configuration/launch behavior, and runs CPU unit tests. GitHub Actions runs these checks on Windows. They require neither model weights nor a GPU.

Client tests use temporary configurations to check registration, removal, and preservation of user edits. Firewall tests mock elevation and inspect the generated rule scope; they do not change Windows Firewall. Live client conversations and access from a second LAN computer require separate integration checks described in [Configuration](Configuration.md#lan-access).

After building the cache image, test its real filesystem adapter without a GPU or persistent cache volume:

```powershell
wslc run --rm --volume "${PWD}/tests:/tests:ro" `
    --entrypoint python n1x-ai:lmcache /tests/disk_adapter_integration.py
```

This checks concurrent stores, bounded eviction, loaded bytes, and restart accounting in a disposable container.

Check Linux broker restart handling without a GPU:

```powershell
wslc run --rm --volume "${PWD}:/project:ro" `
    --entrypoint python n1x-ai:lmcache /project/tests/test_vmm_socket.py
```

These tests cover stale socket recovery and preservation of live sockets and ordinary files. Windows local checks skip these Linux-specific cases.

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
