# LMCache

LMCache stores reusable prompt KV state in RAM and on SSD. Cache profiles run it alongside vLLM in one container; vLLM also maintains its GPU prefix cache. Prepared PLE serves model embeddings and is separate from prompt caching. See [profiles](Configuration.md#profiles) for serving settings and [model assets](Model-assets.md) for exact storage dependencies.

## Compatibility

Local patches provide exportable CUDA VMM allocations, physical segments capped at 512 MiB, alias-safe sharing, staged transfers, bounded admission, and an optional restore queue for WSLC. Smaller physical segments preserve the full KV pool while reducing individual driver allocation sizes. These are experimental platform adaptations, not an upstream support guarantee. See [Development](Development.md#builds) for pinned builds and patch validation.

The local descriptor broker recovers abandoned socket paths when container restarts reuse process IDs. It preserves live listeners and refuses to replace ordinary files or sockets owned by another user.

## Memory budget

Use the [recommended hardware partition](Installation.md#requirements) with the supplied cache settings. Leave at least 4 GiB Windows memory available; aim for 6 GiB for browsing and a harness.

A hidden PowerShell monitor updates Windows physical and commit headroom every five seconds while the cache container runs. The supervisor stops both services if either reserve drops below `WindowsMinimumGiB` (default 4), or the snapshot becomes unavailable/stale. This guard cannot reserve memory or prevent every transient allocation failure.

Both `benchmark.ps1` and `test-restores.ps1` verify the selected profile's effective `RequiredPartitionMiB` before cache tests: 96 GiB for best, with an 88 GiB fallback for reference profiles that do not specify a partition. A mismatch prompts for a manual change and rechecks the hardware; cancellation prevents testing. Restart-restore results include a `partition.json` receipt. Neither command changes the partition or reboots the machine.

To change the host pool or restore wait, edit the corresponding keys in `config.local.psd1`:

```powershell
@{
    LmcacheL1GiB = 4
    RestoreWaitMs = 2000
}
```

The restore queue can wait briefly for space released by another restore. It does not increase capacity. The default wait is zero; cold recomputation remains possible on a cache miss or admission failure. Apply changes with `n1x.ps1 recreate`.

## Cache reuse

### SSD budget

Best sets `LmcacheL1GiB = 4` and `LmcacheL2GiB = 160`: a 4 GiB RAM cache pool and a 160 GiB SSD KV-data budget. The original reference default is 16 GiB on SSD. The SSD budget covers this project's namespaces **within the configured volume**, not every volume on the machine. Separate trial volumes each have their own budget and remain on disk after the experiment unless removed.

A local filesystem-adapter patch serializes store reservations and evicts the least recently used files before writes. Reads refresh their recency. It also leaves 20 GiB available on the Linux filesystem; this floor does not reserve Windows disk space. Run only one project serving profile at a time. These are cache-data budgets, not limits on total process memory, filesystem metadata, model weights, images or the WSLC virtual disk.

There is no configured age-based expiry (TTL). Cold entries are removed when capacity is needed; an idle cache can retain entries indefinitely without exceeding its data budget. Reuse the selected volume for routine operation and retire disposable trial volumes after saving results. Reducing the SSD budget evicts excess entries at the next cache initialization. Reclaiming Windows space may also require TRIM and offline VHDX compaction; see [cleanup](Configuration.md#cleanup-and-disk-reclamation).

Set `LmcacheL2GiB = 8` for a smaller cache, or `0` to disable new SSD caching while retaining RAM caching. Disabling SSD caching does not remove existing files. Rebuild the cache image after patch changes, and recreate the service after configuration changes.

The budget is a working-set choice, not a fixed context-length guarantee. DFlash2 and MTP produce different entry sizes; see [historical sizing](Benchmarks.md#ssd-budget-validation) and [restore qualification](Benchmarks.md#feature-and-cache-validation). Additional entries compete for space, and eviction can reduce prefix hits or require recomputation.

### Prompt reuse

Cache geometry is profile-specific: best uses 4,096-token blocks/chunks, the reference DFlash2 profile uses 1,664, and the other reference cache profiles use 2,048. Partial chunks and changed prefixes affect reuse. Keep compatible geometry together as described in [Scheduling](Configuration.md#scheduling).

Named volumes surviving a restart does not prove a successful restore. Check cache-hit and transfer evidence; a correct response may have been recomputed. See [API guidance](../AGENTS.md) for prompt construction and cache salts and [measured results](Benchmarks.md) for verified behavior.

## Ports and privacy

Only the model API is published, according to [LAN access settings](Configuration.md#lan-access). LMCache TCP 5555 and its HTTP/metrics port 8080 bind to container loopback and need no separate Windows ports.

Outbound usage telemetry is disabled with `LMCACHE_TRACK_USAGE=false`, `DO_NOT_TRACK=1`, `VLLM_NO_USAGE_STATS=1`, and `HF_HUB_DISABLE_TELEMETRY=1`. Internal cache counters remain available for verification. The filesystem cache contains application data; protect its storage accordingly.
