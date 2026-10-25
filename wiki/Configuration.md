# Configuration

Settings merge in this order: `config.psd1`, the selected profile in `profiles/`, ignored `config.local.psd1`, then `-ModelRoot` and `-Port` command arguments. Local values therefore override profile settings. Copy `config.local.example.psd1` when configuring manually.

```powershell
@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'cache-dflash'
    Port = 8000
}
```

## Profiles

| Profile | Context | Speculation | LMCache | KV allocation |
| --- | --- | --- | --- | --- |
| baseline | 32,768 | Off | Off | 4 GiB |
| mtp | 32,768 | One draft token, Triton | Off | 4 GiB |
| cache | 262,144 | Off | On | 8 GiB FP8 |
| cache-mtp | 262,144 | One draft token, Triton | On | 8 GiB FP8 |
| cache-dflash (default) | 262,144 | Three DFlash2 draft tokens | On | 8 GiB FP8 |

Context includes input and output. DFlash2 allows four scheduled sequences; the other cache profiles allow up to 16, but concurrent requests share the KV pool. Output length, simultaneous prefill, vision, and host applications affect capacity. See [LMCache](LMCache.md#memory-budget) for memory controls and [Benchmarks](Benchmarks.md) for measured workloads.

MTP changes acceptance and throughput with workload. Choose the profile using representative application requests rather than assuming more draft tokens are faster.

## Scheduling

`BatchedTokens` is the scheduler's per-step token budget, not the number of sessions. DFlash2 and MTP use 4,096; their cache blocks are 1,664 and 2,048 tokens respectively. A budget of one block can serialize admission. The target-only `cache` profile uses 2,048.

Set `BatchedTokens` in `config.local.psd1` and recreate the service to apply an override. Larger budgets require memory validation. `CacheBlockTokens` and `LmcacheChunkTokens` must be compatible: the chunk size must be a positive multiple of the block size, and the runtime validates each attention group's layout. Keep the supplied per-profile values unless testing a new layout. See [agent concurrency measurements](Benchmarks.md#agent-and-restore-qualification) for the benchmark reference profile.

## Lifecycle

```powershell
.\n1x.ps1 start
.\n1x.ps1 wait
.\n1x.ps1 status
.\n1x.ps1 stop
```

Use the same profile argument across commands, or set `DefaultProfile`. Only one project profile should run at a time. Commands refuse to modify containers without the project's ownership label.

Changing only `DefaultProfile` changes which profile commands select; it does not change an existing profile's runtime settings or require recreating that profile.

Existing containers retain their creation settings. After configuration changes:

```powershell
.\n1x.ps1 recreate
.\n1x.ps1 wait
```

This replaces the selected container and preserves named volumes. Also recreate after rebuilding an image to use the new image. `start -PrintOnly` previews the launch without requiring downloaded models or WSLC access. `restart` reuses a matching configuration.

## DFlash2

The default `cache-dflash` profile uses the DFlash2 drafter with three draft tokens, 262,144-token context, four sequence slots, and an 8 GiB FP8 KV pool. Sliding-attention KV stays BF16; the compressed indexer uses FP8. Matching 1,664-token cache blocks and LMCache chunks reduce Mamba page padding to 0.48%. Its LMCache namespace includes the speculative method, indexer precision, and cache geometry to separate incompatible entries. `cache-mtp` remains available as an alternative; see [qualification results](Benchmarks.md#dflash2-comparison).

At this context limit, vLLM reports approximately 520K tokens of capacity (1.99 maximum-length requests). This is a scheduler estimate, not a guarantee of two simultaneous 262K sessions. Capacity depends on context length because sliding-attention and recurrent-state overhead are included. Four sequence slots do not imply four maximum-length contexts fit together.

Both DFlash2 and MTP pass the synthetic multi-turn agent check with thinking enabled and fail it with thinking disabled; see [agent qualification](Benchmarks.md#agent-and-restore-qualification). DFlash2 at concurrency 4 has the highest measured correct-work throughput in that check. Validate your application's tasks; this narrow qualification does not establish general agent reliability.

```powershell
.\prepare-dflash.ps1
.\n1x.ps1 stop -Profile cache-mtp
.\n1x.ps1 start -Profile cache-dflash
.\n1x.ps1 wait -Profile cache-dflash -TimeoutSeconds 1800
.\n1x.ps1 test -Profile cache-dflash
```

The first start compiles additional FlashInfer kernels. Use `-Profile cache-dflash` for lifecycle commands when selecting it explicitly. Stop it before returning to `cache-mtp`.

## Storage

- Main weights: read-only mount from ModelRoot.
- Native PLE volume: verified copy created by `prepare-native-ple.ps1`.
- Runtime cache volume: compilation and library caches.
- LMCache volume: local SSD cache, separated by runtime/model and speculative method.
- `.state/`: ignored current host-memory snapshot, monitor identity, and local test output.

Named volumes survive stop and recreate. The [SSD cache budget](LMCache.md#ssd-budget) bounds stored KV files; model weights, images, and compilation caches are separate. Cache reuse across engine restarts is not guaranteed by this project.
