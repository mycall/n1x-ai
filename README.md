# n1x-ai

Qwen3.8-Flash-Next on NVIDIA RTX Spark N1X, Windows ARM64, and WSLC.
The initial stable-serving checks are complete. Performance-mode benchmarks
and profile comparisons are recorded below and in `performance-results.json`.

Tested on October 22, 2026 in the user's lowest power mode. The baseline passed
text checks, streaming, JSON output, a tool-call round trip, separate reasoning
output, image shape recognition, OCR, and three-code retrieval through 31,627
input tokens. See `validation.json` for the exact image and qualification record.
The optional Triton MTP profile passed the same feature checks, and the separate
262K profile passed retrieval through 261,002 input tokens with short replies.
The combined `mtp-long-context` profile also passed the feature checks and
64,402 / 129,927 / 261,002 input-token retrieval. The longest request produced
12 MTP draft tokens, all accepted, confirming MTP remained active near the limit.
These are focused correctness checks; sustained use and broader model quality
remain to be evaluated. No throughput benchmark was run during that initial
low-power qualification; the later performance runs are separate evidence.

The October 23 `candidate-fast` profile passed the feature checks, eight label-copy
requests, all 64 native vLLM concurrency benchmark requests, and retrieval at
261,002 input tokens with MTP active. With Performance mode and user-enabled
Boost, median single-request decode rates were 34.04 tokens/s at roughly 1K
input and 31.57 at 8K. See
`candidate-validation.json` and the performance tables below. The default
`baseline` profile remains unchanged; select `-Profile candidate-fast` explicitly.
The subsequent `candidate-16` experiment changes only the active-sequence limit
from 8 to 16. It has passed 16 label-copy checks, 128 native vLLM benchmark
requests, and near-262K MTP retrieval. The first performance comparison included
a USB-C power disconnection (Windows reported Offline at 19:07:44 and Online at
19:08:23 on October 23). It is retained as mixed-power evidence. The repeat in
`results/performance-candidate-16-ac` completed all 128 benchmark requests and
six feature checks with external-power monitoring. Windows available RAM fell
to 4.47 GiB, below the 6 GiB target; guest swap and stalls make throughput
comparisons inconclusive. The historical directory name uses "ac"; the supply
is user-reported 100 W USB-C. Check `wslc list` for the active container.

## Runtime

The agent/cache comparisons are specified in
[`OPTIMIZATION_PLAN.md`](OPTIMIZATION_PLAN.md) and launched with
`run-optimization-matrix.ps1`. Each comparison records its exact image digest.
For future agent harnesses, keep system instructions, tool definitions, and
reference documents in a stable order; append new user/tool messages to the
history. Put changing turn identifiers and timestamps after reusable content.
Keep a session's cache salt stable across turns and resumes. Replacing that salt
or rewriting earlier messages prevents reuse of the corresponding token prefix.

### 88 GiB GPU partition / 8 GiB LMCache capacity check (October 24)

After the user changed the NVIDIA App partition from 96 to 88 GiB, Windows
visible RAM increased from 30.50 to 38.50 GiB. The segmented test image passed
24 requests with an 8 GiB GPU KV pool and an 8 GiB LMCache host L1 pool
(previously 4 GiB). Four concurrent clients each submitted 130,983 prompt
tokens; all cold, warm, and GPU-reset answers were correct, with zero measured
preemptions. The GPU-reset stage loaded 252 chunks and reported 507,904
external-hit tokens. This does not mean every prompt token was restored.

Peak sampled GPU usage was 85.53/88 GiB (2.47 GiB remaining). Windows available
RAM stayed above 8.70 GiB including startup, and above 9.93 GiB in paired serving
samples. No allocation-failure messages were found in the service logs;
EngineDeadError was logged during explicit post-test shutdown. All six feature
checks passed, including separate OCR and image-shape checks. The container
stopped after completion. Evidence: `results/gpu88-lmcache8-verification.json`
and `results/cache-four-131k-gpu88-l1-8g-20261024/`.

The subsequent two-client check at the same 88/8/8 configuration passed both
260,988-token sessions in cold/warm/reset stages. Forced GPU reset loaded 254
chunks, reporting 516,096 external-hit tokens with zero measured preemptions.
Peak sampled GPU usage was 85.53 GiB; Windows available RAM stayed above 9.43
GiB including startup and 10.57 GiB in paired serving samples. All six feature
checks passed on this retry. The first attempt stopped at OCR after producing
HTML and reaching the output limit; that failed response is retained. Evidence:
`results/two-262k-gpu88-verification.json`. Cold long prefills were observed being
scheduled one at a time; this is concurrent-client and restored-prefix evidence.

The prior 96 GiB / 4 GiB L1 four-client run also passed all answers and loaded
252 chunks after GPU reset, but recorded one L1 allocation failure during the
warm stage. See `results/four-131k-verification.json`. The larger pool fits with
more Windows headroom; these battery-mode results are not a controlled speed
comparison. Sustained use, restart, and combined long-context vision remain
unqualified at the new partition. Default
serving settings are unchanged.

Desktop memory budget: target 6 GiB of available Windows RAM, with a 4 GiB
minimum during qualification, while VS Code/Codex and normal desktop applications
are open. These thresholds are recorded in `memory-budget.psd1`; memory captures
and benchmark summaries report violations. They are qualification criteria,
not an operating-system reservation. Browser and harness growth must fit within
this headroom. Windows and guest available memory must not be added together.
LMCache's RAM pool, transfer buffers, process overhead, and filesystem cache must
all fit this budget; no large host cache is assumed affordable. LMCache is
installed in a separate test image and is not qualified as the serving default.

- Ubuntu 26.04 / CUDA 13.4.3 development image.
- vLLM 0.32.0 with the `magi-v5-public` hybrid-weight and SSD PLE patches.
- Upstream commit `1c66e5b1a69c7bab499ff7649b4143e989bd0ed0`.
- Python 3.12.15; Python dependencies pinned in `runtime-packages.txt`.
- PyTorch 2.13.0+cu130: its prebuilt CUDA 13.0 runtime works with the host's
  CUDA 13.4-capable driver and the CUDA 13.4.3 development toolkit.
- INT4 routed experts, FP8 side layers, INT8 output head; original downloaded
  weights are mounted read-only.
- PLE lookup table mapped from local SSD; full-table prewarming disabled.
- Initial profile: 32,768-token context, one sequence, 4 GB BF16 KV cache,
  BF16 recurrent state, eager execution, no speculative drafter.
- Persistent Linux cache volume `n1x-qwen38-cache`.
- Local API: `http://127.0.0.1:8000/v1`, model name `qwen`.

The project borrows halo-ai's separation of model storage, runtime images,
persistent caches, lifecycle commands, and correctness checks. It uses WSLC
directly and does not install Docker Engine.

## Build and run

### Unified cache qualification

The verified experimental cache path uses **88 GiB dedicated GPU, 8 GiB GPU KV,
and 8 GiB host L1**, with segmented VMM sharing, bounded demand admission,
FP8-e4m3 KV, BF16 recurrent state, and 2,048-token blocks. Batch 2048 delivered
38–48% more correct warm agent turns per second than batch 8192 at four
near-131K sessions. MTP helps the short coding fixtures; MTP-off was modestly
faster in the four-agent inventory loop. Both passed focused vision checks and
two near-262K restores. OCR has also failed intermittently; validate responses.

The [core audit](optimization-audit.json) and
[controlled results](efficiency-results.json) record the measured scope.
The [optimization plan](OPTIMIZATION_PLAN.md) covers interpretation and limits;
[AGENTS.md](AGENTS.md) gives minimal API-consumer guidance.

After preparing the downloaded models, native PLE volume, stopped
`candidate-16` container definition, and segmented/admission/optimization images,
repeat the controlled comparison with external USB-C power connected:

```powershell
.\run-efficiency-tests.ps1
```

The runner uses one model at a time, a fixed request seed, unique cache
namespaces, and the 4 GiB Windows guard / 6 GiB headroom target. It scores
checked tool/answer turns, reporting cold and forced-restore costs separately.
The completed [MTP-off follow-up](efficiency-followup-results.json) covers its
smaller-concurrency and long-context checks. At batch 2048, MTP-on was faster
with one or two agents; MTP-off gave a modest 4–6% advantage at four. Both
modes passed twelve growing turns at concurrency 1/2/3/4 and two near-262K
restores. Four clients were the fastest tested point for this work unit.
See the full table in the optimization plan. These qualification
containers stop after completion; they do not provide a persistent service.

With only 4 GiB host L1, the experimental sparse restore queue admitted a
second near-262K restore after 53 ms and avoided recomputation: both requests
completed in about five seconds. This path requires the revision-2 child
image; `run-optimization-matrix.ps1` selects it for `pressure-wait`. The normal
8 GiB-L1 comparisons keep waiting disabled.

<details>
<summary>Earlier LMCache investigation and qualification history</summary>

**Two near-262K sessions tested:** `results/cache-two-262k-20261024-172717`
completed 18 recorded requests. Two 260,988-token prompts returned correct
answers in cold, GPU-warm, and forced GPU-reset stages, with zero measured
preemptions in each stage. GPU use peaked at 86.33/96 GiB; Windows available
memory reached 5.32 GiB in the guard stream and stayed above 5.65 GiB in paired
serving samples. The GPU KV pool remains 8 GiB and host L1 remains 4 GiB.

The reset stage is **not a dual-full-cache-hit pass**: LMCache restored one
258,048-token prefix (127 chunks); the second reservation encountered locked
objects and recomputed instead. Both responses were correct. This identifies
bounded restore queuing as the next improvement without increasing host L1.
The runner accepts `-ParallelContextTokens 261000 -ParallelRestore`; group
metrics count shared counters once rather than adding overlapping per-request
intervals. Evidence: `results/two-262k-verification.json`.

**Segmented 8 GiB capacity check passed on retry.**
`results/cache-capacity-segmented-8g-retry-20261024-145809` completed all 22
recorded requests plus JSON, tools, reasoning, OCR, and shape checks. The actual
8,575,254,528-byte KV pool uses four physical segments and provides 550,316
cached tokens (vLLM reports 2.10x capacity at 262,144 tokens). Near-262K reset
restored 258,048 tokens / 127 chunks correctly, with 44/44 MTP drafts accepted
across that group. Two concurrent 128,958-token prompts returned correct answers
with zero measured preemptions. This does not yet verify two concurrent 262K
requests, concurrent external restores, or long-context vision combinations.

Peak reported GPU use was **85.69/96 GiB**. Windows available memory stayed
above **5.67 GiB** across startup and above **7.49 GiB** in paired serving samples.
The host LMCache cap remained 4 GiB. This was an Eco/Energy Saver correctness run,
not a speed comparison. Evidence: `results/segmented-kv-capacity-pass.json` and
the run's `memory-balance.json`. The earlier startup guard failure remains
recorded below; this successful retry used the same image and limits.

The memory-balance audit (`summarize-memory.ps1 -RunDirectory
results/cache-suite-admission-4g-retry-20261024`) found a peak reported GPU use
of 81.93/96 GiB, leaving 14.07 GiB reported unused. The separate paired telemetry
stream sampled Windows as low as 4.14 GiB available (the guard stream sampled
4.17 GiB). Guest memory is part of host memory, not an additional pool.
See the run's `memory-balance.json` for paired counters and accounting limits.

The current 3.91 GiB GPU KV pool does not maximize reported GPU capacity, but
simply increasing its size is blocked: isolated VMM probes pass at 4,000 MiB
and fail at 4,096 MiB and 8,192 MiB with `cuMemCreate` out-of-memory. Two separate
4,000 MiB allocations retained together pass cross-process data/padding checks.
This supports investigating multiple smaller KV allocations; it does not yet
qualify an 8,000 MiB pool alongside the full model. Evidence:
`results/vmm-4g-boundary-probe.log`, `results/vmm-8g-capacity-probe.log`, and
`results/vmm-two-pools-probe.log`. Current user-reported power mode is Eco Mode
with Energy Saver; these are allocation/correctness checks, not speed comparisons.

`n1x-ai:lmcache-segmented-test` now preserves one contiguous KV virtual range
while backing it with exportable physical segments no larger than 2 GiB. Its
experimental LMCache descriptor carries every segment ID/size and retains one
refcounted imported pool across layer aliases. An 8 GiB probe passed 76 aliases,
three boundary-crossing views, MessagePack roundtrips, writeback, untouched
sentinels, and close-one-alias checks (`results/vmm-segmented-boundaries.log`).
The real MP service also restored SSD-backed data at low/high block indices in
a roughly 8 GiB pool under L1 pressure (`results/mp-segmented-pressure.log`).

The full-model capacity run is `results/cache-capacity-segmented-8g-20261024`.
It uses `-Vmm -Admission -Segmented -CapacityCheck -KvCacheBytes 8589934592`
with 4 GiB host L1 and the existing Windows floor. `-CapacityCheck` runs feature,
synthetic long-context restore, and optional two-request concurrency checks;
it deliberately excludes LongBench, engine-restart, and baseline comparisons.
This attempt stopped at the Windows memory guard during model startup, before
KV allocation or inference: the guard sampled 3.96 GiB available, and the
separate telemetry stream sampled 3.83 GiB. At that point guest `Cached` was
5.95 GiB and guest `MemAvailable` 5.83 GiB; those are overlapping Linux counters,
not additional Windows headroom or proof that all those pages can be returned
immediately. No full-model segmented-pool result is established. Original
serving defaults are unchanged. `-PowerModeNote` records the current user-reported
mode rather than assuming Performance Boost.

**Latest result (October 24):** the experimental admission image passed the
260,988-token single-session GPU-reset check: **258,048 restored tokens,
127 loaded chunks**, correct answer and follow-up. The hook reclaimed 12 objects
without increasing the 4 GiB L1 cap. The reset request took 3.11 seconds in this
run (battery operation; not a controlled power-mode comparison). MTP accepted
44/44 draft tokens across this test group. Windows headroom reached a minimum of
4.17 GiB during this run, so this is not a comfortable 6 GiB-headroom
profile. Three LongBench canaries passed restoration; the fourth cold response
was truncated at the harness's 128-output-token limit before giving its answer.
The suite stopped there, before concurrency, engine restart, or the no-connector
baseline. LongBench requests now allow 1,024 output tokens, with matching context
headroom checks; that adjustment has not been rerun. Evidence:
`results/lmcache-admission-verification.json`.

**Earlier 4 GiB baseline:** the unmodified-admission run verified external-cache
restoration for text prompts through 127,968 tokens (124,928 hit tokens), plus
the short image-prompt check. The 260,988-token request returned correct answers,
but its GPU-reset request restored zero chunks and recomputed the prompt. L1
could not reserve a 63-object prefetch batch; the strict restore gate stopped
the suite. Concurrent restoration, long-context vision, restart, and baseline
comparisons remain unqualified. Windows available memory reached **4.51 GiB**:
above the 4 GiB floor, below the desired 6 GiB headroom. See
`results/lmcache-4g-verification.json`. The following paragraphs record earlier
qualification stages, not additional current blockers.

An isolated installed-runtime experiment, `cache-tests/probe_eviction_pressure.py`,
reproduces allocation failure below the default eviction threshold: 48 MiB of a
64 MiB pool is occupied, and a 32 MiB batch fails. Demand-driven reclamation of
16 MiB permits the batch with both LRU and ARC. Checks preserve locked reads and
writes, decline oversized requests, and release temporary buffers after use.
The follow-on `n1x-ai:lmcache-admission-test` image integrates bounded reclamation
and retry for failed prefetch reservations. `-Vmm -Admission` selects it in the
PowerShell runner. It serializes write reservations, uses the existing eviction
policy, and relies on the manager's lock-checked deletion. Successful reservations
are preserved; oversized or fully locked cases retain the miss/recompute path.
This is an allocation-failure recovery hook, not a streaming prefetch implementation.

Both LRU and ARC pass the integrated allocator checks. A simultaneous two-writer
test admits one 48 MiB batch and declines the other in a 64 MiB pool. A real
MP-service/SSD pressure probe returns zero hits on the original image and restores
both 2K chunks with byte-for-byte correctness on the patched image. Evidence:
`results/probe-admission-integrated.log`, `results/probe-mp-admission-control.log`,
and `results/probe-mp-admission-final.log`. The first full-model attempt,
`results/cache-suite-admission-4g-20261024`, stopped during weight loading when
the host-monitor file disappeared between `exists()` and `stat()` on VIRTIOFS.
The reader now opens a snapshot once and briefly retries replacement gaps;
missing/stale monitors still fail closed (two focused tests pass). Full-model retry:
`results/cache-suite-admission-4g-retry-20261024`; inspect its summary for completion.
These small probes alone do not qualify near-262K restoration or concurrent
hybrid-model checkpoints. No cache limit was increased.

An experimental workaround is being qualified on October 24: FD-based CUDA
VMM sharing succeeds where legacy memory IPC fails. `-Vmm` builds the isolated
`n1x-ai:lmcache-vmm-test` image. It changes only KV-pool allocation to exportable
VMM memory and extends LMCache's VMM wrapper to preserve bounded strided views.
Cross-process read/write and untouched-padding checks passed at 64 MiB and
4,000 MiB. CUDA event IPC also passed; raw legacy memory IPC and disabling
PyTorch's event dependency did not help. This is not yet a model-level pass.

The full-model run now allocates its 4,171,235,328-byte KV pool successfully
after releasing unused PyTorch cached blocks following vision profiling.
Registration exposed a second issue: repeated mappings of the same allocation
failed at `cuMemSetAccess` with `CUDA_ERROR_NOT_READY`. A standalone 4,000 MiB
reproducer failed on alias 29. Sharing an allocation identity across layer views
now passes all 76 aliases with one imported mapping, including closing one alias
while the others remain valid. Twelve upstream wrapper tests also pass (two
skipped, one obsolete missing-resolver expectation deselected). Evidence:
`results/vmm-alias-validation.json`. Full-model cache restoration remains pending.

With shared mappings, the full model registered all 76 layers and returned correct
cold and GPU-warm answers. Its first external-store path then encountered an
illegal CUDA memory access. Isolated padded-block kernels (local and imported)
and registered host-memory copies passed. A real MP-server reproducer stalled on
the default transfer fast paths but passed store, lookup, and byte-verified restore
using the staged asynchronous path. The VMM image now enables this fallback with
`N1X_LMCACHE_STAGED_TRANSFER=1`; see `results/probe-mp-store-image.log`.
This synthetic pass does not yet qualify Qwen prefix restoration or long contexts.

The staged full-model run completed stores and returned correct cold, GPU-warm,
and GPU-reset answers, but the 4,087-token gate produced zero external hits.
Only the full-attention object was stored; this is not a restore pass. The gate
now targets 16K tokens to exercise multiple prefill chunks and allow recurrent
checkpoints despite speculative decoding's checkpoint backoff. The strict
positive loaded-chunk requirement remains unchanged.

**Verified text restore:** `cache-suite-vmm-gate16k-20261024` passed the 16K gate:
after a successful GPU-prefix reset, LMCache reported 12,288 hit tokens, seven
loaded cache chunks, and one completed retrieval; all three requested codes and
the follow-up answer were correct. MTP accepted 52/52 draft tokens across the gate.
JSON, tool-call/result, and reasoning checks passed. OCR returned the correct code
inside a Markdown fence; the original run stopped because its scorer required bare
text. The scorer now accepts a surrounding fence, with wrong/extra-content tests.
Long-context, multimodal restore, concurrent restore, and restart checks remain
unqualified. No battery/external-power speed comparison is claimed.

The subsequent `cache-suite-vmm-qualification-20261024` run also passed image-prompt
restore (4,096 restored tokens), OCR/shapes, JSON, tools, and reasoning. At 32K,
answers remained correct but the 0.5 GiB L1 pool had allocation/prefetch failures
and zero restored chunks after GPU reset. The runner now accepts `-LmcacheL1GiB`
for explicit capacity experiments; the 4 GiB Windows floor remains enforced.

Outbound usage reporting is disabled in the test images, launcher, and service
supervisor with `LMCACHE_TRACK_USAGE=false`, `DO_NOT_TRACK=1`,
`VLLM_NO_USAGE_STATS=1`, and `HF_HUB_DISABLE_TELEMETRY=1`. LMCache's tracking gate
was verified false inside the image. Local Prometheus metrics remain enabled
for cache verification.

```powershell
.\run-cache-tests.ps1 -Vmm -AllowBattery
```

`-AllowBattery` is explicitly for correctness qualification when battery
operation is acceptable. It preserves the 4 GiB Windows memory floor and records
power status; timings must not be compared as external-power benchmarks.
The original serving image and default profile are unchanged.

**Legacy IPC baseline: blocked at CUDA IPC import on the tested WSLC runtime.**
With external USB-C power Online throughout and Windows available RAM never
below 7.43 GiB, LMCache's server failed to import the exported KV allocation:
`CUDA error: invalid resource handle`. A standalone spawned-process test
reproduced the same failure for both 1 MiB and 64 MiB allocations, with CUDA
explicitly initialized in the receiving process. Successful export alone is
insufficient. See `results/lmcache-ipc-roundtrip-probe.txt` and
`results/cache-suite-fp8-4000m-block2048-usbc-20261023/lmcache-server.log`.
That legacy run passed no LMCache inference, restored-prefix correctness, or latency
comparison. This result does not establish a universal Windows/WSL limitation.
The runner now performs this roundtrip preflight before any model load.

`run-cache-tests.ps1` builds a separate `n1x-ai:lmcache-test` image and runs
the model, LMCache service, and lightweight standard-library test client in one
container. Stop other WSLC workloads first. Run from PowerShell:

```powershell
.\run-cache-tests.ps1
```

The separate image pins LMCache 0.5.6 and retains vLLM 0.32.0, Torch 2.13.0,
and FlashInfer 0.7.0.post1. LMCache requires changes to some supporting packages;
the resolved package list is stored in `/opt/lmcache-runtime-packages.txt`.
The original serving image is preserved. This is an experimental qualification
runner, not a promoted default profile.

The current test-runner default is **FP8-e4m3 KV with a 4,000 MiB pool and
2,048-token blocks**;
this does not change `n1x.ps1` serving defaults. The first BF16/10 GB LMCache
attempt failed during CUDA IPC export before any request. Small probes showed
2 GiB, 3 GiB, 3,900 MiB and 4,000,317,440-byte exports succeeding, but 4 GiB exports failing
with CUDA out-of-memory even on an otherwise nearly empty GPU. Exportable CUDA
VMM allocations also failed at 4 GiB. vLLM 0.32 allocates its KV cache in one
backing allocation. The installed QSA backend explicitly supports FP8-e4m3;
the initial 4 GB decimal experiment could only accommodate an estimated
260,176 tokens. The automatic 1,616-token block size failed LMCache recurrent-state
tiling. A direct layout probe passes with 2,048-token blocks, whose added padding
requires a larger pool. A 4,000 MiB CUDA IPC export passed with 72 GiB ballast.
the smaller pool experiment must still establish context capacity, restored
answer correctness and MTP/vision behavior. No BF16-equivalent quality claim
is implied. See `results/lmcache-ipc-*-probe.txt` and
`results/cache-suite-20261023/summary.json` for the initial failure evidence.

The test order is a 16K cache gate, feature checks (including tool use, reasoning,
vision and multimodal restore), 32K/128K/near-262K retrieval, halo-ai's pinned
six-sample LongBench-v2 canary, and two independent roughly 129K conversations.
LongBench samples outside the native context are explicitly skipped, never
truncated. This bounded subset is not a full LongBench score. The dataset
revision, SHA-256, selection policy and official prompt format match halo-ai's
LongBench-v2 helper; dataset preparation happens before model startup.

Each case compares a fresh KV prefix, GPU prefix reuse, a GPU-only prefix reset,
and a follow-up turn. LMCache restore requires a positive external chunk-load
counter. A single engine restart checks cross-process recovery. The same image
also runs a separate no-connector baseline. Model loads are grouped by
configuration, not repeated for every context length. PLE filesystem cache is
not flushed, so "cold" refers to KV reuse rather than cold SSD data.

LMCache starts with a 0.5 GiB L1 pool and native-volume filesystem L2 using
direct I/O. This is a candidate memory budget, not evidence that an entire
262K prefix can be restored through that pool. Actual retrieved chunks,
correctness and timings determine the result. The host monitor records the
user-reported 100 W USB-C supply and Windows external-power status; the latter
does not measure negotiated USB-C wattage. The runner stops service processes
after persistent loss of the 4 GiB Windows headroom minimum, external power,
or fresh host telemetry. Partial results and logs remain under `results/`.

The build passes session proxy variables as temporary build secrets. The
existing `C:\Users\michael\source\bin\wslc-proxy.ps1` handles engine proxy
configuration, but its engine restart was followed by container-launch
timeouts in this session. Terminating the idle WSLC session and letting WSLC
start its normal engine restored launches. Local-image builds with proxy
secrets do not require that engine restart.

</details>

### Normal serving

In PowerShell, from this directory:

```powershell
.\build.ps1
.\n1x.ps1 start
.\n1x.ps1 wait
.\n1x.ps1 status
.\n1x.ps1 logs
.\n1x.ps1 test
.\n1x.ps1 stop
.\n1x.ps1 restart
```

`start` creates the container and returns while weights load, or starts the
existing managed container. `restart` reuses an existing container, including a
stopped one. These commands refuse to change a container without this project's
ownership label. Configuration is in `config.psd1`; changing it requires recreating
the container, since restarting preserves its original arguments.

Preview the launch with:

```powershell
.\n1x.ps1 start -PrintOnly
```

`test` runs three short text correctness checks and writes
`results/smoke-baseline.json`. Additional correctness suites are available:

```powershell
.\n1x.ps1 test -Suite features
.\n1x.ps1 test -Suite context
# Explicit context sizes and a separate result file:
.\test.ps1 -Suite context -ContextTokens 4096,16384,31744 -ResultName context-check
```

The feature suite covers streaming, JSON, tool calling with a simulated tool
result, reasoning, and two image requests. The context suite places access codes
near 10%, 50%, and 90% of a generated archive and checks retrieval. It records
actual input token counts. Test artifacts are written under `results/`; no
external tools are executed and no performance benchmark is run.

## Optional profiles

The default remains `baseline`. `mtp` enables the checkpoint's own MTP layer
with one speculative token and Triton draft-expert kernels; it does not
download a DFlash drafter. The main model retains its existing kernels.
`long-context` requests the model's native 262,144-token limit and a 10 GB KV
cache. Profile definitions live in `profiles/`. Qualification results below
determine which capabilities have actually worked on this system.
`mtp-long-context` combines the same 262K limit and 10 GB cache with the
Triton MTP configuration.

Only one project profile may run at a time. Switch explicitly:

```powershell
.\n1x.ps1 stop
.\n1x.ps1 start -Profile mtp
.\n1x.ps1 wait -Profile mtp -TimeoutSeconds 7200
.\n1x.ps1 status -Profile mtp
.\n1x.ps1 logs -Profile mtp
.\n1x.ps1 test -Profile mtp
.\n1x.ps1 stop -Profile mtp
.\n1x.ps1 start
```

Use `-Profile long-context` in the same way for the context trial. The standalone
`test.ps1` targets whichever profile currently serves port 8000; `n1x.ps1 test`
also checks that the selected profile is running. Cold weight loading takes
several minutes. All profiles share the downloaded models and Linux kernel cache.

With `long-context` running and ready, reproduce the larger retrieval checks:

```powershell
.\test.ps1 -Suite context -ContextTokens 64512,130048,261120 -ResultName context-long
```

The context limit includes both the input and generated reply, including chat
template and image tokens. Reserve output space rather than filling the entire
limit with input.

To switch from the baseline to the combined configuration:

```powershell
.\n1x.ps1 stop
.\n1x.ps1 start -Profile mtp-long-context
.\n1x.ps1 wait -Profile mtp-long-context -TimeoutSeconds 7200
.\n1x.ps1 test -Profile mtp-long-context -Suite features
.\test-mtp-long.ps1
```

`test-mtp-long.ps1` checks retrieval near the context limit and records the
change in MTP draft/accept counters around that request. Run it without other
clients so those counters describe the test request. Use
`.\n1x.ps1 status -Profile mtp-long-context` for the combined server's status.

`wait` allows 60 minutes by default and retries transient WSLC connection
failures. For a longer first kernel compilation, use
`.\n1x.ps1 wait -Profile mtp -TimeoutSeconds 7200`. A timeout leaves the container
running. This extends the readiness polling budget; it does not alter WSLC's
internal socket timeout. New containers limit kernel compilation to one Ninja
job and one NVCC thread to fit the roughly 15 GiB WSLC host-memory budget.
The initial automatic MTP backend selected FlashInfer; its unrestricted build
exhausted host RAM, Linux killed Python, and the container exited with code 137.
Increasing the readiness timeout alone cannot fix an out-of-memory kill.
The current MTP profile explicitly selects Triton for the draft experts to
avoid that large compilation. `prepare-mtp.ps1` remains available for a future
FlashInfer trial: it compiles that kernel into the shared cache without model
weights loaded. It is not required for the Triton MTP profile.

Example request from PowerShell:

```powershell
$body = @{
    model = 'qwen'
    messages = @(@{ role = 'user'; content = 'Explain what a CUDA kernel does.' })
    max_tokens = 256
    chat_template_kwargs = @{ enable_thinking = $false }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:8000/v1/chat/completions `
    -Method Post -ContentType application/json -Body $body
```

To apply a changed configuration, stop and remove only this project's
container, then create it again. This keeps the model files and cache volume:

```powershell
.\n1x.ps1 stop
wslc remove n1x-qwen38
.\n1x.ps1 start
```

## Qualification results and remaining scope

The initial correctness qualification was collected on October 22, 2026 in the
user-reported lowest power mode. The October 23 performance runs and candidate
qualification use user-reported Windows Performance and MSI Performance modes;
Boost was enabled during candidate startup and is recorded separately.
The user's screenshot confirms MSI Center S, User Scenario, Performance Boost
selected with the Performance Boost toggle on. Windows Performance mode is
also user-reported. This is the condition retained for the 16-sequence trial.
The underlying Windows power plan can still show Balanced independently of
the Settings power mode. These scripts do not change either setting.

| Capability | Tested scope | Follow-up evidence needed |
| --- | --- | --- |
| Text chat | Three basic correctness checks | Longer varied conversations and sustained use |
| MTP | Triton draft experts, one speculative token: feature checks and retrieval through 261,002 input tokens passed in eager and candidate graph profiles; counters confirmed drafts accepted at the context limit | Sustained use and broader tasks; isolate MTP's effect with identical power and runtime settings |
| DFlash2 | Disabled; no drafter downloaded | Qualify the public drafter and target-feature capture with this checkpoint |
| Vision | Shape/color recognition and printed-code OCR passed | Diverse images, multiple images, video, and larger resolutions |
| Tool calling | Correct tool name/arguments and simulated tool-result round trip passed | More schemas, parallel calls, and multi-turn workflows |
| Context length | Baseline: 3,977 / 16,252 / 31,627 input tokens; 262K profiles with and without MTP: 64,402 / 129,927 / 261,002 input tokens, all retrieval checks passed | Broader long-context tasks and longer replies |
| Throughput | Eager MTP and candidate graph MTP each passed all 64 requests in native vLLM concurrency 1/2/4/8 sweeps. Candidate also passed features, eight label checks, and near-262K retrieval | Sustained arrivals, longer mixed contexts, and deferred Balanced-mode comparison |

The conservative default remains 32K. The optional 262K profile uses a 10 GB
BF16 KV cache and passed actual retrieval requests near its native limit, with
API health checked after each request. This qualifies the tested retrieval
cases; it does not establish exhaustive long-context quality or support beyond
262,144 total tokens. Both `long-context` (MTP disabled) and `mtp-long-context`
(Triton MTP enabled) passed those cases. A sample during the combined profile's
longest request showed 84,951 MiB of 98,304 MiB dedicated GPU memory in use
(about 83 GiB), and 7.146 GiB of 14.85 GiB WSLC host RAM. This was a sample,
not a peak-memory measurement. Short text checks also passed after the long run.

MTP uses the checkpoint's existing 1,565 BF16 draft tensors. vLLM warns that
this drafter cannot receive external image embeddings; it drafts from text
inputs while the target model processes the image. Both synthetic image checks
passed with MTP enabled. This does not qualify video or arbitrary multimodal
workloads. The default profile keeps MTP disabled; select `-Profile mtp` for
MTP at 32K or `-Profile mtp-long-context` for MTP at 262K. Each serves one
sequence at a time. The combined profile was left running after qualification;
use its profile name for status, logs, test, stop, and restart commands.
Subsequent performance work switches between profiles; check `wslc list` for
the currently running container instead of relying on that historical state.

## Repeatable performance measurements

Run benchmarks with other inference clients idle. The single-request benchmark
requires the selected 262K profile to be running:

```powershell
.\benchmark.ps1 -Profile mtp-long-context -RunName performance-mtp-on
# Stop that profile and start/wait for long-context before this comparison:
.\benchmark.ps1 -Profile long-context -RunName performance-mtp-off
```

Each run excludes an initial warmup and measures three requests each at roughly
1K, 8K, and 32K input tokens, with exactly 256 generated tokens. A unique vLLM
`cache_salt` prevents prefix-cache reuse without changing the prompt text.
The script verifies zero prefix-cache hits and one completed server request per
measurement. Results include streaming time to first content, request duration,
server decode rate, draft acceptance counters, answers, and five-second memory
samples. Forced-length synthetic answers measure speed, not answer quality.
Kernel and filesystem caches remain warm; model startup is excluded.

The optional `throughput` and `mtp-throughput` profiles retain the 262K limit
and 10 GB KV pool but allow eight active sequences. They are benchmark profiles;
the existing serving defaults still allow one sequence. After starting and
waiting for one of them:

```powershell
.\benchmark-concurrency.ps1 -Profile throughput
```

This invokes the installed `vllm bench serve` tool at concurrency 1, 2, 4, and 8,
using eight requests per setting, 1K and 8K synthetic random input tokens, and
128 output tokens. Use `-Requests` and `-OutputTokens` for a larger run. The
client runs inside the same WSLC container and consumes some guest CPU/RAM.
It uses the chat endpoint, thinking disabled, seed 42, zero shared random prefix,
and a new cache salt for each setting. An independent warmup is excluded.
Aggregate tokens/sec includes prefill and decode. Detailed vLLM results and
before/after server metrics are retained. This finite concurrency sweep does
not establish sustained arrival-rate capacity or capacity for eight simultaneous
262K requests. Inspect latency and preemption counters alongside aggregate speed.

Memory telemetry distinguishes Windows available physical RAM, guest
`MemAvailable`, and dedicated GPU usage. These views must not be summed.
Sampled extrema are not instantaneous peaks. Raw data is in each run's
`results/<run-name>/` directory.

The container pins Python 3.12.15 to match the upstream patch layout and the
qualified dependency set. Python 3.14 is a separate optimization candidate;
changing it requires dependency compatibility checks, patch-path updates, and
an A/B test before claiming a serving-speed improvement.

### October 23 single-request results

Both arms completed all nine requests with successful post-request health
checks and zero prefix-cache hits. Medians of three requests per input size:

| Actual input tokens | MTP decode tokens/s | MTP-off decode tokens/s | MTP first token (s) | MTP-off first token (s) |
| ---: | ---: | ---: | ---: | ---: |
| 948 | 5.37 | 4.02 | 0.85 | 1.25 |
| 8,128 | 6.06 | 4.31 | 4.13 | 7.60 |
| 32,736 | 4.19 | 2.92 | 18.27 | 35.20 |

MTP accepted about 77% of drafted tokens. MTP had higher median speed in this
pass, but substantial run-to-run variation and sequential test order prevent
treating these ratios as a controlled acceleration guarantee. GPU clocks,
temperature, and background host activity were not held constant. Each reply
was forced to 256 tokens; these are synthetic speed measurements.

| Memory sampled during run | MTP | MTP off |
| --- | ---: | ---: |
| Maximum dedicated GPU used, of 96 GiB | 83.31 GiB | 78.30 GiB |
| Minimum Windows available RAM | 11.01 GiB | 9.11 GiB |
| Minimum WSLC guest available RAM | 8.65 GiB | 9.25 GiB |
| Guest swap used | 0 GiB | 0 GiB |

Windows availability reflects the whole host at each run's time; it does not
isolate the model's RAM consumption. The MTP run has 125 memory samples and
the MTP-off run has 170, with no telemetry failures. Full ranges and raw-run
references are in `performance-results.json`. Regenerate that file with
`summarize-benchmarks.ps1`; the original correctness record remains in
`validation.json` with its original power-mode conditions.

### Parallel requests and cache effects

The eager `mtp-throughput` profile completed all 64 native `vllm bench serve`
requests with no failed requests, 128 output tokens each:

| Nominal input | Concurrency | Aggregate output tokens/s | Median first token (s) | Median time/output token (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 1,024 | 1 | 4.08 | 7.26 | 176.78 |
| 1,024 | 2 | 9.38 | 1.43 | 209.94 |
| 1,024 | 4 | 15.03 | 1.73 | 239.49 |
| 1,024 | 8 | 27.56 | 2.89 | 252.40 |
| 8,192 | 1 | 2.09 | 49.61 | 189.66 |
| 8,192 | 2 | 9.57 | 6.60 | 159.58 |
| 8,192 | 4 | 15.96 | 5.13 | 177.09 |
| 8,192 | 8 | 17.02 | 19.46 | 253.95 |

These settings ran sequentially. A unique KV-cache salt prevents prefix reuse,
but does not reset the PLE filesystem cache. Repeating concurrency 1 after the
sweep produced 5.05 tokens/s and 0.68 s median first token at 1K, and 4.42
tokens/s and 4.18 s at 8K. Both controls passed all eight requests. Their decode
time per token remained similar to the first sweep. The initially cold
concurrency-1 measurements therefore exaggerate scaling if used as the sole
baseline. Raw controls are in `results/performance-vllm-warm-control`.

For this eager profile and workload, concurrency 4 at 8K is the useful latency/
throughput tradeoff among the tested settings: about 94% of concurrency 8's
aggregate speed with much lower first-token latency. At 1K, aggregate speed
continued improving through concurrency 8. This does not establish a universal
optimum, larger-concurrency capacity, or capacity for simultaneous 262K prompts.

The sweep's sampled maximum dedicated GPU usage was 84.53 GiB; minimum Windows
available RAM was 6.14 GiB and minimum guest available RAM 8.02 GiB, with no
guest swap use (292 samples, no telemetry failures). A separate eight-request
label-copy check passed. These original PowerShell label checks dispatched eight
tasks but inherited a two-connection HTTP limit, so they do not independently
prove eight active server requests. The native Python vLLM benchmark is unaffected.
`test-parallel.ps1` now explicitly sets its connection limit to the requested
concurrency and records that limit with each result. An earlier version calling the labels "private test
codes" had one refusal, preserved in `parallel-smoke-private-wording.json`;
the neutral-wording check is in `parallel-smoke.json`.

### CUDA graphs, CPU placement, and storage probes

Keeping MTP off, 262K context, 10 GB KV, one sequence, 2,048 batched tokens,
and the Windows PLE mount, switching from eager execution to
`FULL_AND_PIECEWISE` CUDA graphs yielded 23.55 / 23.87 / 24.80 server decode
tokens/s for 948 input and 256 output tokens (median 23.87). All three requests
had zero KV-prefix hits and healthy post-request checks; the three basic
correctness checks also passed. The earlier eager median was 4.02 tokens/s.
This sequential comparison is strong evidence that eager execution accounted
for much of the upstream speed gap, but background activity and clocks were
not controlled. It does not establish performance at other contexts or with
MTP. Graph capture itself used about 0.05 GiB according to vLLM's log.
Evidence: `results/performance-graphs-offmtp` and `results/graph-startup.log`.

Two matching short requests on `mtp-throughput` measured 5.68/8.14 decode
tokens/s with the original guest affinity and 4.43/5.80 with API/engine threads
restricted to guest CPUs 5–9 and 15–19. The original affinity was restored.
Host CPU counters still concentrated activity on physical efficiency cores;
the trial did not demonstrate performance-core placement or a speed benefit.
The sample is small and host-wide counters are not process attribution.
`benchmark-affinity.ps1` records and restores affinity for repeatable trials.

With inference stopped, `system-probe.ps1` compared one PLE shard over the
Windows virtiofs bind and a copy in the Linux ext4 cache volume. Sequential
512 MiB reads measured 191/237 MiB/s (first/warm pass) over virtiofs versus
703/3,065 MiB/s in ext4. Warm 4 KiB single-worker reads were much faster in
ext4, but eight-worker results were mixed and first-pass single-worker random
reads were slower in ext4. This bounded Python pread test includes scheduling
overhead, uses one file, and does not control Windows/device caches or reproduce
the full mmap PLE workload. It motivates an inference comparison, not a claimed
SSD or model acceleration factor. Raw data: `results/performance-storage-probe`.

`prepare-native-ple.ps1` copies the PLE files to `n1x-ple-native` and verifies
source/destination SHA256 hashes, retaining the original downloads. Run it with
managed inference containers stopped. The tested `candidate-fast` profile
uses that volume read-only, CUDA graphs, one-token Triton MTP, eight sequences,
8,192 batched tokens, up to 32 PLE gather workers, and the existing 262K/10 GB
KV limits. It passed three text checks, six feature checks, and eight
label-copy requests. It also passed the full concurrency sweep and retrieval
at 261,002 input tokens, with 12 MTP draft tokens and all 12 accepted. The three
post-long-request text checks passed. This qualifies the specific tests; it is
not an exhaustive model-quality or sustained-serving qualification.

During the near-limit request, 23 successful telemetry samples recorded a
maximum 86.55 GiB dedicated GPU use, minimum 5.41 GiB Windows available RAM,
and minimum 8.46 GiB guest available RAM. Guest swap use remained at 88 KiB.
Full evidence is in `candidate-validation.json` and
`results/candidate-fast-long-limit*`.

With the native PLE volume prepared, launch or inspect this profile with:

```powershell
# Stop another active project profile before starting this one.
.\n1x.ps1 start -Profile candidate-fast
.\n1x.ps1 wait -Profile candidate-fast -TimeoutSeconds 7200
.\n1x.ps1 status -Profile candidate-fast
```

With user-reported Boost enabled, its single-request results were:

| Actual input tokens | Median decode tokens/s | Range | Median first token (s) |
| ---: | ---: | ---: | ---: |
| 948 | 34.04 | 32.51-37.33 | 0.66 |
| 8,128 | 31.57 | 31.12-34.89 | 3.60 |

All six requests generated 256 tokens, had zero prefix-cache hits, and passed
post-request health checks. MTP accepted 665 of 867 drafted tokens (76.7%).
Maximum sampled dedicated GPU use was 86.10 GiB; minimum Windows availability
was 6.26 GiB and guest availability 8.66 GiB, with no guest swap use. Model
inference itself reached 53.90 W reported GPU power in these samples.
This is a combined profile/power comparison, not an isolated MTP, storage, or
Boost speedup. Evidence: `results/performance-candidate-fast`.

The candidate's native vLLM sweep completed all 64 requests with no failures:

| Nominal input | Concurrency | Aggregate output tokens/s | Median first token (s) | Median time/output token (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 1,024 | 1 | 25.21 | 1.03 | 31.63 |
| 1,024 | 2 | 42.43 | 0.97 | 37.67 |
| 1,024 | 4 | 58.72 | 1.72 | 55.18 |
| 1,024 | 8 | 81.96 | 3.15 | 71.05 |
| 8,192 | 1 | 14.00 | 5.32 | 31.27 |
| 8,192 | 2 | 18.78 | 7.32 | 42.39 |
| 8,192 | 4 | 25.42 | 7.56 | 94.96 |
| 8,192 | 8 | 27.76 | 22.22 | 111.61 |

For these 8K prompts, concurrency 4 delivered 92% of concurrency 8's throughput
with much lower first-token latency. Short 1K prompts continued scaling through
8. Use lower concurrency for individual response latency, around 4 for mixed
interactive workloads as a starting point, and 8 for short-prompt aggregate
throughput. These are finite synthetic batches with sequential cache warming,
not a universal optimum or a sustained production load test. The server's
eight-sequence limit does not imply capacity for eight simultaneous 262K inputs.

Across the sweep, sampled GPU use peaked at 86.25 GiB, Windows available RAM
fell to 3.87 GiB, and guest availability to 7.73 GiB. Guest swap use peaked at
88 KiB; GPU power reached 56.23 W. All 97 telemetry samples succeeded. Evidence:
`results/performance-candidate-concurrency`. Both benchmark scripts accept
`-WindowsPowerMode`, `-MsiMode`, and `-RuntimeNote` for the deferred Balanced-mode
comparison; retain the same profile and workload and record Boost separately.

### GPU power sanity check

After the user enabled Boost, a separate 30-second dense FP16 GEMM probe
reached 68.09 W reported average GPU power and 72.06 W instantaneous power.
Twenty samples at at least 90% GPU utilization averaged 46.93 W. Power fell
toward 32-35 W late in the run; the software power-cap flag was active in 18
of those samples, while the software/hardware thermal-slowdown flags were
inactive. Sampled GPU temperature reached 65 C. The driver reports no module
power or power-limit value, so this identifies a power-policy limit without
establishing its platform cause. NVIDIA's 45-80 W specification is superchip
TDP, not a minimum expected GPU reading.

The probe completed with finite outputs, approximately 66.39 dense TFLOP/s,
and 768 MiB peak PyTorch allocation. It is a bounded compute-load check, not
vLLM throughput or a numerical accuracy qualification. No clock or power limit
was changed by the script. Evidence: `results/candidate-compute-power-2`.
`probe-gpu-compute.ps1` reproduces it with an idle, healthy serving container.
The initial attempt failed in argument quoting before GPU work; that evidence
is retained in `results/candidate-compute-power`. Boost was enabled after the
earlier eager/graph runs, so subsequent profile comparisons also change power
conditions; see `results/candidate-boost-condition.json`.

## Model files

The default model root is `C:\Users\michael\models`:

| Directory | Hugging Face repository | Revision |
| --- | --- | --- |
| `Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid` | `Saren/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid` | `8b82f0b7abe3d1150a7827d298c75e86267636ae` |
| `ple-table-fp8` | `Saren/Qwen3.8-Flash-Next-ple-table-fp8` | `50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14` |

Setup checked all 81 main-model files and all 35 table files against the pinned
Hub manifests for existence and byte length. This was not a full cryptographic
hash verification. The downloaded files occupy approximately 127.6 GB.

## Host constraints

### N1X platform documentation

The local board identifies as MSI MS-2621 / Prestige N16 Flip AI+ C1XMT.
NVIDIA's [RTX Spark specifications](https://www.nvidia.com/en-us/products/rtx-spark/specifications/)
list a 6,144-core Blackwell GPU, 20-core CPU, laptop NPU, 256-bit LPDDR5X
memory interface, CUDA capability 12.1, and 45–80 W laptop TDP. The desktop
variant has a different power envelope; shared architecture does not establish
equal sustained performance.

The [CPU guide](https://docs.nvidia.com/rtx-spark/rtx-spark-porting-guide/latest/portingandemulation/cpuspecific.html)
documents ten Cortex-X925 performance cores and ten Cortex-A725 efficiency
cores. Windows performance-core indices are 5–9 and 15–19, matching our CPU-set
enumeration. These indices must not be assumed to map directly to WSLC vCPUs.
The [system overview](https://docs.nvidia.com/rtx-spark/rtx-spark-porting-guide/latest/overview.html)
specifies 300 GB/s memory bandwidth; this is a specification, not a measured result.
Windows SMBIOS reports SK Hynix memory with configured speed 9400, consistent
with MSI's LPDDR5X-9400 specification. Interpreted as 9,400 MT/s across 256 bits,
this gives 300.8 GB/s theoretical bandwidth. The
[DGX Spark hardware guide](https://docs.nvidia.com/dgx/dgx-spark/hardware.html)
specifies LPDDR5X-8533 and 273 GB/s: roughly 10% less theoretical bandwidth.
This could benefit memory-bound decoding but does not predict a 10% token-rate
gain. SMBIOS is configured-speed metadata, not a live clock measurement;
NVML returns N/A for current and maximum memory clocks on this system.

NVIDIA's [memory architecture guide](https://docs.nvidia.com/rtx-spark/rtx-spark-porting-guide/latest/uma/index.html)
explains that dedicated GPU memory is carved out of physical system DRAM.
Shared GPU memory overlaps the remaining Windows-managed RAM. Our DXGI query
reports approximately 96 GiB dedicated and 15.25 GiB shared; Windows reports
30.50 GiB CPU-visible RAM. These quantities are overlapping views, not separate
memory banks to add together. DXGI omits the NPU; a separate read-only DXCore
query (`inspect-dxcore.ps1`) confirms its dedicated adapter and dedicated system
memory are both zero, while shared system memory is 16,373,442,560 bytes (15.25
GiB), identical to the GPU's shared allowance. This is not an additional memory
bank or a measurement of currently free RAM. The NPU advertises D3D12 generic ML
support but not D3D12 core compute support. These capability flags do not establish
operator coverage, an available model runtime, or vLLM compatibility. Raw output:
`results/windows-dxcore-memory.json`.

The [CUDA allocation guide](https://docs.nvidia.com/rtx-spark/rtx-spark-porting-guide/latest/uma/umacuda.html)
documents smaller pages and potentially slower access after dedicated allocations
spill into shared memory. It discourages cudaMallocManaged on native Windows
RTX Spark. Native Windows allocation recommendations do not automatically
describe every WSLC CUDA path; no allocator changes have been made here.

The [MSI US specification](https://us.msi.com/Business-Productivity/Prestige-N16-Flip-AI-Plus-C1XMX/Specification)
confirms 128 GB unified memory and a 140 W adapter for C1XMT-062USY. The
[MSI MS-2621 user guide, revision 1.0 June 2026, mirrored PDF](https://gzhls.at/blob/ldb/3/c/f/c/27ae3126a3a1bebc92d90fd6af8f483fba1d.pdf)
has no NPU programming interface, throughput specification, or NPU memory
allocation controls. An NPU is detected locally as ACPI NVDA200A, but no
compatible NPU backend has been qualified for this vLLM project. The advertised
FP4 AI performance must not be treated as an NPU-specific rating.
The installed NVIDIA driver INF (`oem74.inf`, version 32.0.16.1742) maps this
device to `NVIDIA_DEV.DLA_REV_0034`. This driver label alone does not establish
compatibility with Jetson DLA runtimes or provide an NPU throughput rating.

There is now a documented native Windows runtime path:
[Enterprise TensorRT 11.4.0](https://docs.nvidia.com/deeplearning/tensorrt/11.4.0/getting-started/release-notes-11/11.4.0.html)
introduces beta Windows on Arm DLA support. This package executes on DLA only;
it has no GPU fallback, and the 11.4 DLA backend is not supported on Linux SBSA.
The [Windows DLA layer guide](https://docs.nvidia.com/deeplearning/tensorrt/11.4.0/inference-library/dla-windows-on-arm.html)
requires fixed shapes, batch size one, and a fully supported operator graph.
Compute defaults to FP16; quantization support does not imply native INT8 compute.
The release notes document intermittent accuracy failures and require rebuilding
beta engines at general availability. This SDK has not been installed or tested
here. A separate fixed-shape vision workload is a plausible experiment, subject
to operator and accuracy validation; this does not establish support for Qwen's
vision encoder, MTP, or automatic offload from our WSLC vLLM process.

N1X under Windows/WSLC is not the same memory environment as a native Linux DGX
Spark. At setup, Windows reported 96 GiB dedicated GPU memory and WSLC exposed
about 15 GiB host RAM. The runtime does not reserve Windows' reported shared
GPU memory or assume it is dedicated VRAM. The table is demand-paged from SSD,
and the baseline leaves GPU headroom rather than using upstream's 20 GiB KV pool.

The container retains the CUDA compiler for runtime kernels. The vLLM wheel's
CUDA dependencies can differ from the base toolkit version; the installed
driver must support both. No host driver, kernel, memory partition, or firewall
changes are made by these scripts.

Upstream code and models retain their respective licenses. The upstream
checkout is kept in `upstream/` and is not modified by this project's build.
