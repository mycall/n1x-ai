# vLLM 0.33 serving qualification on N1X

The opt-in trial runs the W4 target and DFlash2 K3 on Linux ARM64 under WSLC. It uses the upstream 0.33 Model Runner V2, a 262,144-token context, two sequences and a 15 GiB KV pool. The graph-only trial uses a 2,048-token prefill batch. The cache-enabled launcher uses 4,096 because LMCache requires a prefill step to cover at least one complete hybrid KV block. Global KV uses FP8, and sliding-window layers keep their original precision. Prefill runs eagerly. The target and the drafter each captured two full decode graphs. These runs measure correctness. The native AMD64 timing comparison remains pending.

## External PLE and graph replay

The original eager reader copies row IDs to the CPU synchronously. The new reader queues that copy, gathers the mapped checkpoint rows in a native CUDA host callback, then copies the FP8 bytes back to the GPU. It can overlap the preceding decoder layer. All transfers for a lookup use the same CUDA stream, and the consuming layer waits on that stream. Across 15 CUDA graph replays at batch sizes 1, 2 and 4, all 560 gathered rows matched the original bytes, including shard boundaries and the last vocabulary row. This checks row selection and ordering. It supplies no estimate of time saved. [Reader](../runtime/vllm033/n1x_prefetch.py) · [Native gather](../runtime/vllm033/ple_prefetch.cpp) · [Parity check](../runtime/vllm033/check_prefetch.py)

The first serving image passed 12/12 short requests and accepted 141/153 draft tokens across three runs, the same counts as the eager control. This workload passed before the DFlash graph backport. Upstream also fixed a stale drafter KV block table during full graph replay. The candidate applies that fix against a checked source digest. [Upstream change](https://github.com/vllm-project/vllm/pull/64059) · [Eager control](data/vllm-033-dflash-20261120.json)

## Tool calls and short vision probes

The graph-only image completed **3/3 near-full inventory tasks** on the first attempt. Each selection processed 250,002 input tokens, produced the requested tool and SKU, and stopped for the tool call. The three continuations processed 250,184 to 250,219 tokens, reused 249,856 tokens from the native prefix cache each time and returned the exact expected answer. The short image fixture passed shape recognition and OCR in all three attempts, including the exact code `N1X-742`. Long-context vision and higher concurrency remain unmeasured here. [Per-request results](data/vllm-033-serving-20261120.json)

With LMCache enabled and FlashInfer autotuning disabled, the backported image also passed **3/3 near-full inventory tasks**. Each selection started cold at 250,002 tokens. The continuations used 250,193 to 250,200 tokens and each reused 249,856 tokens through the GPU prefix cache. All six requests had zero external cache hits and zero scheduler preemptions. The near-full benchmark's host-memory field pointed at the default profile's stale snapshot, so these results use request and vLLM counters only. The trial supervisor separately used the live trial memory monitor. [Per-request results and counter deltas](data/vllm-033-serving-20261120.json)

## SSD restore after container replacement

The cache-enabled candidate passed 12/12 short requests and accepted 140/153 draft tokens across three runs with FlashInfer autotuning disabled.

All six archive queries answered correctly after replacing the trial container. **Two of the three pairs recovered the full block-aligned prefix.** Four requests recovered 16,384 tokens each and two recovered 8,192 each. The six requests totaled 81,920 external cache-hit tokens, 32 SSD objects loaded and six completed LMCache retrieves. Native prefix-cache hits were zero. The seed logs for the partial pair show L1 allocation failures. Both restores in that pair retained four SSD objects apiece, compared with six apiece in the full pairs. The 1 GiB host tier therefore demonstrated SSD recovery with inconsistent full-prefix coverage under this workload. [Per-pair counters](data/vllm-033-serving-20261120.json)

The third seed pair ran after the earlier pause. It returned both answers and recorded eight completed SSD stores before the Windows memory guard ended that boot. The first two pairs had already recorded settled disk writes. All three pairs used the same named SSD volume, image and cache settings. Local raw data is under `results/benchmarks/serving033/restart-1`. Use a fresh results directory and trial volume for a complete rerun.

## Reproduce

The cache-enabled trial uses a 1 GiB host tier and a dedicated 16 GiB SSD tier. The Windows 4 GiB memory guard stopped a 2 GiB host-tier trial during model loading and a 1 GiB trial during the FlashInfer tuning sweep. LMCache had registered 78 KV layers before the latter stop. The cache launcher disables FlashInfer autotuning to reduce startup memory pressure.

The sweep benchmarks available implementations of FlashInfer operations for token-count buckets. FlashInfer uses heuristic choices for operations without tuned results. The graph-only trial's 2,048-token sweep took 165 seconds. With the sweep disabled, startup still selected the FlashInfer GDN prefill kernel and captured full decode graphs. The two profiles used different prefill batch sizes and cache settings, so a matched tuning-on/tuning-off comparison is still needed to quantify the effect on serving latency and throughput. [vLLM 0.33 warmup source](https://github.com/vllm-project/vllm/blob/v0.33.0/vllm/model_executor/warmup/kernel_warmup.py)

Build the candidates on an idle N1X with the project's W4 model, drafter and FP8 PLE volume prepared. The cache image rebuilds LMCache 0.5.6 from a digest-checked source archive against the image's Torch 2.14 and CUDA 13. The packaged ARM64 extension originally failed to import because it referenced an unavailable Torch CUDA symbol. The upstream image ships CPython 3.12.3 and its native extensions target that ABI. The benchmark client uses C# and .NET 10.

```powershell
./runtime/vllm033/build-cache.ps1
$tests = (Resolve-Path runtime/vllm033).Path
wslc run --rm --gpus all --volume "${tests}:/test:ro" --volume n1x-ple-native:/ple:ro --env N1X_W4_PLE_DIR=/ple --entrypoint python3 n1x-ai:v033-serving -P /test/check_prefetch.py
./runtime/vllm033/start-trial.ps1 -Serving
```

The graph-only server listens on localhost port 18133. The near-full C# workload uses `near-full --target 250000 --repeats 3 --sessions 1 --concurrency 1 --turns 1` with the trial URL, host metadata file and a fresh output directory. The existing `test.ps1` accepts `-Port 18133 -Tests vision_shapes,vision_ocr` for the short image probes.

For the SSD test, remove the graph-only trial, choose a fresh `n1x-033-*` volume and start the cache-enabled image. Wait for HTTP 200 from `http://127.0.0.1:18133/health` after each start. Both processes run inside the trial, so replacing the container clears the GPU and host cache tiers. The C# client joins its network namespace to read the local cache metrics. Verify uses the seed's image, volume and saved benchmark binary.

```powershell
$volume = 'n1x-033-restore-example'
$results = 'results/benchmarks/033-restore-example'
wslc volume create $volume
./runtime/vllm033/start-trial.ps1 -Serving -CacheVolume $volume
# After health returns 200
./runtime/vllm033/test-restore.ps1 -Stage seed -Directory $results
wslc stop n1x-trial-v033
wslc rm n1x-trial-v033
./runtime/vllm033/start-trial.ps1 -Serving -CacheVolume $volume
# After health returns 200
./runtime/vllm033/test-restore.ps1 -Stage verify -Directory $results
wslc stop n1x-trial-v033
wslc rm n1x-trial-v033
```
