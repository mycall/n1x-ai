# LMCache

The cache profiles run vLLM and LMCache together in one container. LMCache uses an 8 GiB host L1 pool with LRU eviction and a native SSD L2 cache. vLLM also retains its GPU prefix cache. The native PLE table serves model embeddings and is independent of KV caching.

## Compatibility

Local patches provide exportable CUDA VMM allocations, physical segments capped at 512 MiB, alias-safe sharing, staged transfers, bounded admission, and an optional restore queue for WSLC. Smaller physical segments preserve the full KV pool while reducing individual driver allocation sizes. These are experimental platform adaptations, not an upstream support guarantee. See [Development](Development.md#builds) for pinned builds and patch validation.

## Memory budget

Use the [recommended hardware partition](Installation.md#requirements) with the supplied cache settings. Leave at least 4 GiB Windows memory available; aim for 6 GiB for browsing and a harness.

A hidden PowerShell monitor updates the latest Windows headroom every five seconds while the cache container runs. The supervisor stops both services if available memory drops below `WindowsMinimumGiB` (default 4), or the snapshot becomes unavailable/stale. This guard cannot reserve memory or prevent every transient allocation failure.

For less host-cache pressure, edit `config.local.psd1`:

```powershell
@{
    DefaultProfile = 'cache-mtp'
    LmcacheL1GiB = 4
    RestoreWaitMs = 2000
}
```

The restore queue can wait briefly for space released by another restore. It does not increase capacity. The default wait is zero; cold recomputation remains possible on a cache miss or admission failure. Apply changes with `n1x.ps1 recreate`.

## Cache reuse

Chunk size is 2,048 tokens for the standard cache profiles and 1,664 for the experimental DFlash2 profile. Partial chunks and changed prefixes affect reuse. See [API guidance](../AGENTS.md) for prompt construction and cache salts, and [benchmark results](Benchmarks.md#feature-and-cache-validation) for verified restores.

## Ports and privacy

Only the model API is published, on Windows loopback port 8000 by default. LMCache TCP 5555 and its HTTP/metrics port 8080 bind to container loopback. They do not need separate Windows ports.

Outbound usage telemetry is disabled with `LMCACHE_TRACK_USAGE=false`, `DO_NOT_TRACK=1`, `VLLM_NO_USAGE_STATS=1`, and `HF_HUB_DISABLE_TELEMETRY=1`. Internal cache counters remain available for verification. The filesystem cache contains application data; protect its storage accordingly.
