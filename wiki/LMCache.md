# LMCache

The cache profiles run vLLM and LMCache together in one container. LMCache uses an 8 GiB host L1 pool with LRU eviction and a native SSD L2 cache. vLLM also retains its GPU prefix cache. The native PLE table serves model embeddings and is independent of KV caching.

## Compatibility

The image pins LMCache 0.5.6, vLLM 0.32.0, PyTorch 2.13.0, and FlashInfer 0.7.0.post1. Local patches provide exportable CUDA VMM allocations, physical segments capped at 2 GiB, alias-safe sharing, staged transfers, bounded admission, and an optional restore queue for WSLC. These are experimental platform adaptations, not an upstream support guarantee. Patch application checks the expected source.

## Memory budget

On the target 128 GiB system, use the 88 GiB dedicated GPU partition with the supplied 8 GiB GPU KV and 8 GiB host L1 settings. Leave at least 4 GiB Windows memory available; aim for 6 GiB for browsing and a harness.

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

## Agent reuse

Keep reusable prompt prefixes and cache salts stable. Append messages rather than rewriting earlier content. Correctness, actual cache hits, and end-to-end latency should all be checked in the consuming application. Chunk size is 2,048 tokens; partial chunks and changed prefixes affect reuse.

## Ports and privacy

Only the model API is published, on Windows loopback port 8000 by default. LMCache TCP 5555 and its HTTP/metrics port 8080 bind to container loopback. They do not need separate Windows ports.

Outbound usage telemetry is disabled with `LMCACHE_TRACK_USAGE=false`, `DO_NOT_TRACK=1`, `VLLM_NO_USAGE_STATS=1`, and `HF_HUB_DISABLE_TELEMETRY=1`. Internal cache counters remain available for verification. The filesystem cache contains application data; protect its storage accordingly.
