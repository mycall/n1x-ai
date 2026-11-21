# vLLM 0.33 serving qualification on N1X

The opt-in trial runs the W4 target and DFlash2 K3 on Linux ARM64 under WSLC. It uses the upstream 0.33 Model Runner V2, a 262,144-token context, two sequences and a 15 GiB KV pool. The graph-only trial uses a 2,048-token prefill batch. The cache-enabled launcher uses 4,096 because LMCache requires a prefill step to cover at least one complete hybrid KV block. Global KV uses FP8, and sliding-window layers keep their original precision. Prefill runs eagerly. The target and the drafter each captured two full decode graphs. These runs measure correctness. The native AMD64 timing comparison remains pending.

## C8 replacement comparison

The normal launcher offers `qwen38fn-v033` at 15 GiB and `qwen38fn-v033-kv20` at 20 GiB. Both select eight sequence slots, an 8,192-token prefill batch, DFlash2 K3, a 4 GiB host tier and a 160 GiB SSD budget. They share the model and prefill batch of the 0.32 default while using versioned, separate SSD volumes. FlashInfer autotuning stays off on both 0.33 profiles. The runtime changes include the loader, PLE reader, graph mode and cache write retry, so this is a deployment comparison with multiple runtime differences.

Use the normal launcher for the selected profile and wait for health. The comparison sends three batches of eight simultaneous clients with independent cache salts and roughly 32K input tokens each. Each client selects a tool and continues with its result. Add the wall time of all three batches, and keep the peak observed scheduler count and preemption total. A separate case is needed to measure a workload whose live contexts exceed the 15 GiB pool.

Both 0.33 profiles reached eight active requests in each repeat and passed all 24 tasks without preemptions. At 15 GiB, the three batches took 909.47 seconds combined. At 20 GiB, they took 1,001.43 seconds. The larger pool increased vLLM's reported KV capacity from 730,605 to 973,330 tokens. Both pools already held this workload. The 20 GiB arm's Windows monitor sampled 4.27 GiB of available memory during startup, close to the 4 GiB guard. The workload harness's separate host-memory field still read the default profile snapshot, so the comparison uses the trial supervisor for headroom and the workload harness for request and scheduler counters. [Per-repeat evidence](data/vllm-033-c8-20261120.json)

The 20 GiB slowdown showed up on the cold requests. Both 0.33 arms processed 786,624 cold input tokens and reused 786,432 tokens on tool continuation. Summed cold time to first token grew from 3,701.94 to 4,156.27 seconds, while summed warm time to first token fell from 199.62 to 162.91 seconds. The server's cumulative request queue, prefill and decode durations grew about 11%, 8% and 11% respectively. Draft acceptance fell from 77.7% to 76.0% with slightly fewer generated tokens overall. These durations overlap across clients. They locate the slowdown without identifying a hardware or kernel cause. The 15 GiB arm ran first, so run order and memory residency remain possible factors.

The 0.32 default passed 24/24 at the same 15 GiB, with eight active requests and zero preemptions in each repeat. Its three batches took **297.71 seconds**, making the 0.33 15 GiB deployment **3.05 times as long** on this workload. Both runs reused exactly 786,432 tokens, and their generated token totals were within 0.4%. Draft acceptance was 79.1% on 0.32 and 77.7% on 0.33. The cumulative request prefill and decode times grew by factors of 3.56 and 2.98 respectively. The result supports keeping 0.32 as the default for this system. It applies to the full serving recipes and leaves the individual effects of the loader, PLE path, graph mode and runner unresolved. [Per-repeat totals and phase counters](data/vllm-033-c8-20261120.json)

```powershell
$profile = 'qwen38fn-v033'
$run = "results/benchmarks/$profile-c8-$(Get-Date -Format yyyyMMdd-HHmmss)"
$null = New-Item -ItemType Directory -Force (Split-Path $run -Parent)
./n1x.ps1 start -Profile $profile
@{profile=$profile} | ConvertTo-Json | Set-Content "$run-host.json"
dotnet run --project benchmarks/Client -c Release -- near-full --host "$run-host.json" --url http://127.0.0.1:8000 --out $run --target 32768 --repeats 3 --sessions 8 --concurrency 8 --turns 1
./n1x.ps1 stop -Profile $profile
```

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

The per-salt counters narrow down the partial recovery. During seeding, each partial request submitted and completed 10 SSD objects. Full requests submitted 10 or 12 and completed every submitted object. The two partial retrieves submitted four SSD reads apiece and completed all four. Each full retrieve submitted and completed six. The missing coverage was present before the SSD read stage, and the seed allocation warnings make host-tier admission the leading explanation. The object count alone cannot identify which block and group combinations were missing. The follow-up records filenames by object group before and after container replacement, and checks each HTTP response for the exact block-aligned token count.

### Host-tier budget comparison

The follow-up changed the host tier to 1.5 GiB, used a fresh 16 GiB SSD volume and kept the image, workload and 4 GiB Windows memory guard fixed. The lowest sampled available Windows memory was 5.59 GiB. Both budgets returned 6/6 correct answers. The 1 GiB results come from the earlier trial, which seeded its third pair on a separate boot. [Per-request restore counts and file inventory summary](data/vllm-033-serving-20261120.json)

| Host tier | Full requests | Full pairs | External tokens recovered | SSD objects read | Shortfall |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 GiB | 4/6 | 2/3 | 81,920 | 32 | Two requests recovered 8,192 of 16,384 tokens each |
| 1.5 GiB | 5/6 | 2/3 | 94,208 | 35 | One request recovered 12,288 of 16,384 tokens |
| 1.5 GiB with write retry | 6/6 | 3/3 | 98,304 | 36 | All requests recovered 16,384 tokens |

The 1.5 GiB seed persisted 69 of 72 possible files. The same filenames and sizes were present after container replacement. Each missing file belonged to object group 0 and matched a 118,226,944-byte L1 allocation failure counted as `l1_store`. Missing group 0 in the first block was compatible with full coverage in both observed cases. Missing it in the final block cost 4,096 tokens. All submitted SSD reads completed. This connects the partial restore to host-tier write admission and shows why total files written is an insufficient readiness check.

The project already retries failed reservations after eviction for prefetch. The 1.5 GiB control left engine writes on the ordinary `storage_manager` reservation path. This budget improved coverage and still failed the full-prefix acceptance criterion on one pair.

### Bounded write retry

The trial's `-RetryCacheWrites` setting enables write-side reclamation for a single L1 manager and a single project filesystem adapter. It retries only failed reservations that reported insufficient memory. The retry considers existing eviction candidates once, skips keys from its own reservation, and keeps the normal L1 lock checks. A candidate must have a final backing file published by the filesystem adapter. File deletion and the L1 reclaim check are coordinated so an in-flight SSD delete cannot supply that check. This preserves pending writes and keeps the L1 and SSD budgets fixed.

With 1.5 GiB and write retry enabled, all four failed initial reservations recovered. All 72 expected KV files reached SSD, and the filenames and sizes matched across container replacement. **All three pairs passed strict verification.** Every answer was correct, all six requests restored 16,384 tokens each, and the counter recorded zero native prefix hits. The Windows memory guard stayed enabled throughout. This qualifies the write retry for the tested six 17K-token histories. [Image, container and per-request evidence](data/vllm-033-serving-20261120.json)

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

Use `-CacheL1GiB 1.5` on both starts to compare a 1.5 GiB host tier with the default 1 GiB. Keep the SSD volume unique to each budget and leave the Windows memory guard enabled. The restart checker inventories persisted files at the end of seeding and before verification, and requires full block-aligned external recovery per response for all three pairs.

Add `-RetryCacheWrites` to both starts to test the write retry with the 1.5 GiB budget. Build the cache image first so the launcher and server agree on the setting.

## Native AMD64 FlashInfer comparison

The local machine and its WSLC image are ARM64. The C# workload plan was validated locally. Timing awaits a native AMD64 GPU runner.

Use the same native AMD64 GPU, vLLM image, model, KV geometry and PLE path for both arms. Disable LMCache for the kernel timing comparison and hold the CUDA graph mode and prefill batch fixed. Toggle only `--kernel-config '{"enable_flashinfer_autotune":true}'` or its `false` counterpart. Give each boot a fresh autotune result directory and the same state of the ordinary kernel compilation caches. Record launch-to-health time and separate tuning start and end timestamps.

Run three paired boots in on/off, off/on, on/off order. After health, run one fixed unscored warmup per boot, then use the same C# workload on both arms. This example covers batch-one cold and appended-history requests at three input lengths.

```bash
dotnet run --project benchmarks/Client -c Release -- speed \
  --profile "$trial_label" --url http://127.0.0.1:18133 --out "$fresh_directory" \
  --mode both --depths 4096 32768 131072 --concurrency 1 --repeats 1 \
  --extension-tokens 2048 --output-tokens 128 --context-limit 262144
```

Sum valid input tokens and prefill time across the three attempts for each shape and arm. Sum generated tokens after the first token and decode time separately. Keep the timing sources consistent, and report the three startup costs and the total serving time saved on a fixed workload. The payback request count is the extra startup time divided by the serving time saved per request, when the latter is positive.
