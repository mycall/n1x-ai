# Compression trials

Run with PowerShell 7 from a prepared N1X checkout. The reader adapter targets the pinned MyLLMBox v5.4 ARM64 asynchronous FP8 reader ABI. It retains original bytes for immutable 160-byte rows. The payload limit is 16 MiB. Metadata and temporary buffers consume additional host RAM.

```powershell
./benchmarks/compression/ple_trial.ps1 -CheckOnly
./benchmarks/compression/ple_trial.ps1
```

The first command compiles the adapter in the selected image, compares stock and cached rows through eviction and reset, and measures host memory. The second also starts an isolated server using the best profile's settings and a fresh LMCache volume. It requires an idle serving GPU, runs adjacent on/off pairs and saves JSONL, an aggregate summary and the server log under the printed results directory. Use `-Port` to select the trial port. The runner removes the trial container and L2 volume after capturing the results. The adapter is selected only in that container.

The workload uses repository Markdown and PowerShell excerpts, followed by C# excerpts for the append-turn check. Fresh KV salts isolate fresh requests. The long-prefix cases exercise normal KV prefix reuse. Measure whole-request completion for serial jobs and time to complete both requests at concurrency two. `summary.json` includes paired results for equal prompts, cached tokens, generated tokens and output, plus unfiltered results and correctness counts.

## Test populated LMCache objects

The standalone probes accept a read-only cache mount at `/lmcache`. Use the image from the measured service and a snapshot or quiescent L2 volume. The example uses the configured best profile's image and volume.

```powershell
. ./scripts/config.ps1
$c = Get-N1xConfig -Root $PWD.Path -Profile qwen38fn-best
$src = (Resolve-Path benchmarks/compression).Path
$mounts = @('--volume', "${src}:/trial:ro", '--volume', "$($c.LmcacheVolume):/lmcache:ro")
wslc run --rm --pull never @mounts --entrypoint python3 $c.ImageId /trial/codec.py
wslc run --rm --pull never @mounts --entrypoint python3 $c.ImageId /trial/group.py
$scratch = 'n1x-codec-' + [guid]::NewGuid().ToString('N')
wslc volume create $scratch
try {
    wslc run --rm --pull never @mounts --volume "${scratch}:/scratch" --entrypoint python3 $c.ImageId /trial/direct.py
} finally {
    wslc volume rm $scratch
}
```

`codec.py` samples about one MiB per eight MiB of stored data. It measures LZ4 and Zstd-1 on identical blocks and checks lossless recovery. `group.py` needs prefixes with all three object groups. An empty list means none qualified. `direct.py` stages raw and compressed frames on a separate temporary scratch mount for an O_DIRECT comparison. Place scratch on the same SSD class as the L2 data. [Results and interpretation](../../wiki/Compression.md)
