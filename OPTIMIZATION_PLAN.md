# Optimization experiments after the capacity baseline

Baseline local commit: `b1cb162`. No push requested or performed.

Preserve 88 GiB dedicated GPU, 8 GiB GPU KV, 8 GiB LMCache host L1, MTP1,
FP8 KV, BF16 recurrent state, max sequences 16, native SSD PLE, and outbound
telemetry disabled. Windows availability floor remains 4 GiB, target 6 GiB.
Battery operation is authorized; record timings as observational unless power
conditions are controlled. Do not claim a global performance optimum.
GPU busy percentage is not arithmetic efficiency: NVIDIA's advertised 1 PFLOP
uses FP4 with sparsity, whereas this model uses W4A16 and mixed kernel types.
Any future percent-of-peak report needs a matching arithmetic denominator or
measured DRAM bandwidth against the published 300 GB/s ceiling.

## Required experiments and evidence

1. **Two near-262K simultaneous restores.** Run cold/warm/reset at the new
   partition. Require both answers correct; distinguish restored prefixes from
   recomputation with global cache counters and allocation-failure logs.
   First run `cache-two-262k-gpu88-l1-8g-20261024` stopped at preliminary OCR:
   it produced HTML and hit the generation limit. No long requests ran.
   Unchanged retry `cache-two-262k-gpu88-l1-8g-retry-20261024` passed all six
   feature checks and 18 requests. Both 260,988-token sessions were correct in
   cold/warm/reset stages; reset loaded 254 chunks with 516,096 external-hit
   tokens and zero measured preemptions. Peak sampled GPU use was 85.53/88 GiB;
   paired serving Windows minimum was 10.57 GiB. Evidence:
   `results/two-262k-gpu88-verification.json`. Cold prefills were observed being
   scheduled one at a time, so this is not simultaneous-GPU-prefill evidence.
2. **Repeated agent turns.** Four near-131K archives, growing actual tool-call
   histories, changing inventory results, stable per-session salts, forced GPU
   reset midway. Require tool argument, returned count, archive-code correctness
   and actual external loads on resume. Completed in `opt-20261024-agents`:
   all four agents passed four turns (32 tool/answer calls), including forced
   restore. Group wall times were 184.54 / 14.78 / 15.12 / 15.72 seconds. The
   reset turn loaded 512 chunks across tool and answer requests; no preemptions.
   Observational timings; external power changed during startup. Sampled peak
   GPU use was 85.70/88 GiB; paired Windows availability stayed above 10.63 GiB.
3. **Stable prompt prefixes.** Controlled four-turn comparison putting a
   changing identifier early versus late in otherwise identical 32K content.
   Completed in the same run: changing the early identifier gave TTFTs around
   10.3–10.4 seconds on every turn. With the identifier at the end, the initial
   TTFT was 10.49 seconds and subsequent TTFTs were 1.27–1.29 seconds. All answers
   were correct. Real harness should preserve tool definitions and
   history prefixes rather than regenerate or reorder them each turn.
4. **Eager prefetch.** Installed connector confirmed to implement the setting.
   Repeat the same agent workload with only `-EagerPrefetch` changed. Check
   correctness, memory pressure, cache loads and latency; queued prefetch can
   increase occupied host staging. `opt-20261024-eager` was interrupted when its
   parent tool-session process disappeared and the host monitor became stale.
   This was not a CUDA/host OOM. Identical retry `opt-20261024-eager-retry` passed
   all four agents/turns and 44 tracked requests. Group wall times were 186.43 /
   13.86 / 14.16 / 14.40 seconds; no preemptions. Peak sampled GPU use was 85.74
   GiB; paired Windows availability stayed above 10.09 GiB. Eager prefetch loaded
   1,606 chunks versus 1,472 for the baseline, with fewer generated tokens
   (1,284 versus 1,312). MTP accepted 640/640 versus 656/656 draft tokens. The small
   observed latency difference is not enough to establish a general speed win.
5. **Bounded restore admission.** Experimental nonblocking queue checks whether
   missing objects can fit in free plus evictable L1 memory. Wait at most the
   configured deadline, then use existing bounded admission/fallback. Only the
   single-L1 topology is covered. Metadata snapshot uses private manager fields;
   test-image source guards and probes are required on upgrades. Unit tests and
   actual 64 MiB L1 probe pass; full controller/model comparison pending. Initial
   probe caught misuse of unsafe_read as a residency query; fixed with a locked
   metadata snapshot. Evidence: `results/restore-queue-probe.log`.
   Matched pressure baseline `opt-20261024-pressure-immediate` completed all
   answers correctly with a 4 GiB L1 pool. GPU-reset restored one prefix
   (127 chunks / 258,048 external-hit tokens) and recomputed the other after
   126 staging reservations were declined; both reset requests took about 92.3
   seconds. Zero preemptions; paired Windows availability stayed above 12.88
   GiB. `opt-20261024-pressure-wait` passed all answers but did not exercise the
   queue: it again restored 127 chunks and declined 126 staging reservations.
   The pre-lookup estimate counts logical cache groups before sparse selection,
   so it is unsuitable for this hybrid model's actual load plan.

   Revision 2 moves admission after lookup and sparse load planning, deferring
   reservation without completing the request or blocking the controller loop.
   Four new unit tests and an actual L1/native-bitmap probe pass: 192 MiB logical
   demand becomes 32 MiB selected demand in a 64 MiB pool; locked buffers cause
   deferral and release permits admission. Evidence:
   `results/restore-queue-v2-probe.log`. Full-model follow-up pending after the
   original matrix. Use `run-optimization-worker.ps1 -RunPrefix opt-20261024
   -CaseList pressure-wait-v2 -AllowBattery -SkipBuild` once the current worker
   finishes. The separate queue child image records the original comparison
   image as its parent; it does not replace the frozen batching/MTP image.
   That case first runs `probe_mp_restore_queue_v2.py` with no full model loaded:
   two real MP/SSD restores must wait/release correctly in a 64 MiB L1, and both
   GPU destinations must match their original bytes. This preflight is pending.
6. **Prefill batches at concurrency 1/2/4.** Run 8192, 2048 and 4096 batched
   tokens with the same 32K agent-loop sweep. Compare throughput and per-session
   latency, including cache restore, and record peak memory. One model load per
   batch setting, all three concurrency levels within that load. The 8192-token
   case completed 68 tracked requests: all four turns at concurrency 1/2/4
   passed, including external restore. Cold HTTP spans were 13.97 / 26.13 / 50.79
   seconds; warm/resume spans were approximately 4.22–4.67 / 7.03–7.99 /
   11.38–14.49 seconds. These span both tool call and answer per client and
   exclude the harness's one-second metric-publication pause. Original harness
   timings remain recorded. The 2048 case also completed all 68 tracked requests
   at concurrency 1/2/4 with restore checks. Four-client harness turn times were
   56.22 / 10.06 / 10.72 / 9.75 seconds: slower cold prefill, faster repeated
   turns than 8192. The 4096 case completed all 68 requests as well.
   Mean GPU-warm HTTP group spans at concurrency 1/2/4 were 3.17 / 5.27 / 8.86
   seconds for 2048, 4.40 / 7.40 / 13.40 for 4096, and 4.39 / 7.44 / 12.41 for
   8192. Peak sampled GPU memory was 82.37 / 83.20 / 85.60 GiB respectively.
   Evidence: `results/prefill-comparison.json`. The warm-heavy preference favors
   2048 in these measurements; long-context requalification is still pending.
   The same 31,983-token retrieval at 2048 restored 30,720 tokens,
   versus 28,672 at batch 8192. Its GPU-warm path reused 28,672 GPU tokens plus
   2,048 external tokens. The extra reusable checkpoint leaves one fewer block
   to recompute. Single-client agent warm/resume harness times were 4.09–4.46
   seconds versus 5.27–5.73 at 8192. Final profile conclusions await the controlled
   long-context comparisons. If the selected profile changes the reference
   settings, requalify it with two near-262K clients and growing near-131K
   agent histories before recommending it for those capacities.
   User preference: optimize the warm-heavy agent workflow. In the four-client
   2048-versus-8192 measurements, roughly 4.4 seconds of extra cold-turn cost is
   offset by about 3.5 seconds saved per GPU-warm turn, so two warm turns already
   amortize the cold penalty. The 2048 case also reduced sampled peak GPU use
   to 82.37 GiB, leaving 5.63 GiB in the 88 GiB partition. Keep the 8 GiB KV pool
   fixed while selecting/qualifying the batch profile; extra headroom is not an
   obligation to allocate more memory.
7. **MTP on/off on coding and tool calls.** Run identical executable Python
   fixtures and repeated tool calls with MTP1 and with its config removed.
   Compare answer correctness, output tokens, total latency and global draft
   acceptance counters. Small coding fixtures are not a general coding score.
   Both hardware runs completed. All twelve saved Python programs in each run
   passed the corrected executable validator. At coding concurrency 1/2/4,
   group spans were 5.46 / 3.49 / 3.40 seconds with MTP and 7.54 / 4.83 / 3.95
   without it. Conversely, the two-agent inventory warm turns were 7.87 / 7.16
   seconds with MTP versus 5.87 / 5.21 without. These observational results
   motivate a task-specific long-context comparison rather than a blanket MTP
   recommendation. Evidence: `results/mtp-comparison.json` and both runs'
   `coding-validation.json` files. The frozen image's program validator
   excludes some harmless Python idioms (confirmed with `dict.fromkeys`), so both
   MTP runs' exact saved programs must also pass through
   `cache-tests/validate_coding_results.py` with the corrected validator. The
   post-check preserves source hashes and original inference timings/scores;
   it does not regenerate answers. New regression tests cover `dict.fromkeys`
   and `filter`; the inference image remains unchanged across the matrix.

## Experimental controls

The primary efficiency objective is **correct warm agent turns per second**
(user selected). The follow-up in `efficiency-protocol.json` fixes request seed
0, requires external power, and checks twelve growing near-131K tool/answer
turns. Cold turn 0 and forced restore turn 6 are reported separately; two
five-turn warm cohorts measure behavior before and after resume, with cache
paths classified from counters. They are not automatically equivalent GPU-warm
states. The cost of any KV preemption or bounded cache fallback remains in the
measured throughput. Those counters are reported as warnings rather than
automatic correctness failures; do not discard a faster correct configuration
solely because it schedules through LMCache. Explicit concurrency
1/2/3/4 is tested at batch 2048, with batch 8192 and MTP-off comparisons at
concurrency 4. `run-efficiency-tests.ps1` uses a distinct image descended from
the frozen comparison image; only the client controls/validator change.
This bounded search does not establish theoretical FLOP utilization or a
global optimum. Four simultaneous near-131K sessions and two near-262K
sessions must still qualify at the candidate batch before promotion.

Controlled candidate `eff-20261024-batch2048-mtp` has passed the two near-262K
cold/warm/reset check: both restored answers were correct, with 256 loaded
chunks, 520,192 external-hit tokens, no prefetch failures, and no preemptions.
Restored total latencies were 2.51 and 3.75 seconds. The growing near-131K
concurrency sweep is still running; these partial results do not promote a
serving default.

The completed single-agent candidate loop shows a useful distinction: turns
1–5 reuse 258,048 GPU tokens plus 4,096 external tokens across each tool/answer
pair; turns 7–11 reuse 262,144 external tokens and zero GPU tokens. All answers
are correct. Therefore the post-resume cohort is externally warm, not GPU-warm.
This is recorded in the scorer; the cause of the missing local reuse is not
yet established. The installed vLLM cache-manager source differs from the clean
local checkout, so source diagnosis must use the installed image's code.
Within each cohort, aggregate prompt-cache queries grow by about 294 tokens
per turn while hit-token counts remain fixed. That supports growing suffix
recomputation as a contributor to the gradual latency increase; the change in
cache path after reset adds a separate cost. Do not attribute the whole change
to thermals or treat host-cache hits as local GPU hits.

The original nine-case screening matrix completed. Exact saved programs from
both MTP runs passed all twelve corrected executable checks. The initial
pressure-wait prototype did not actually wait, so it remains an unqualified
optimization. Its replacement must pass a real MP/SSD byte-correctness
preflight before another full-model trial.

The first MP/SSD queue preflights timed out waiting for two stored chunks:
the fixture used GPU block zero, which the installed LMCache treats as a null
sentinel. Only one chunk was committed. The corrected fixture uses nonzero
source and destination blocks; it still needs to pass on an idle GPU. These
failures did not exercise or validate the replacement queue. The controlled
warm-throughput runs use the ordinary bounded cache path with restore waiting
disabled.

`run-cache-tests.ps1 -Optimizations -Segmented -Admission -Vmm` selects the
separate `n1x-ai:lmcache-optimization-test` image. Other controls:

- `-AgentLoops -AgentTurns 4 -AgentContextTokens 131000 -ParallelSessions 4`
- `-AgentConcurrencySweep` runs 1/2/4 clients within the same model load.
- `-PrefixExperiment -CodingWorkload`
- `-EagerPrefetch`, `-RestoreWaitMs 1000`, `-PrefillBatchTokens 4096`, `-DisableMtp`
- `-SkipConcurrency` skips the older fixed parallel workload; agent loops still run.

All experimental defaults are off. Keep the qualified serving defaults unchanged
until these comparisons and sustained-use checks provide evidence for promotion.

The matrix paused after its first successful run because memory postprocessing
accessed an absent `server` property under inherited PowerShell strict mode.
The reporter now tolerates startup/shutdown samples and optional guest data;
`cache-tests/test_summarize_memory.ps1` covers that regression. The completed
model run was preserved, and the remaining cases resumed with the same image
digest and run prefix. Full-matrix audit: `results/optimization-audit.json`.

`run-optimization-worker.ps1` can run detached with `Start-Process -WindowStyle
Hidden`; its status JSON records the PID, start time, and terminal error. Verify
that PID's command line/creation time or the live container before deciding a
run has stopped. The matrix accepts explicit per-case run-directory overrides
from `results/<prefix>-overrides.json`, so failed attempts need not be overwritten.
