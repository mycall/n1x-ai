# Remaining work and test matrix

Updated November 1, 2026. Working branch: `qwen38fn-myllmbox`.

After the budget experiments, the user selected **8,192 as the serving output default/cap**. `MaxOutputTokens` now controls native/WSLC launches and managed OpenCode/Pi limits; it applies on the next launch/recreation. Explicit benchmark limits remain unchanged. Earlier statements below about unchanged defaults describe the experiment conditions. The selected serving profile remains `qwen38fn-cache-dflash`.

The hybrid approach remains in scope. A full rerun is deferred until later today and must not start automatically. The initial qualification is complete; review its archived evidence, then execute the matrix when requested. No scheduled automation or GPU-partition change is implied by this plan.

Benchmark scope remains serving performance, tool reliability, caching, concurrency and stability. Project-specific coding evaluation and practice optimization are out of scope; each consuming project owns those checks. The completed LRU experiment is retained as evidence about output-budget exhaustion, not a plan for a repository-coding benchmark suite.

## 1. Review qualification and freeze the evidence — complete

Completed implementation:

- Native Windows lifecycle support for `qwen38fn-myllmbox`, using devjeonghwan's MyLLMBox-derived runtime and the tested 90 GB recipe.
- All selectable profiles use the `qwen38fn-` prefix; old names are rejected. The default is `qwen38fn-cache-dflash`. Existing containers need recreation after the rename; model files and cache volumes are retained.
- Windows clients for agent, recovery, scheduling, short-generation and mixed-workload probes; LMCache metrics are omitted when that service is absent.

Completed native checks: three smoke checks, six feature checks including vision/OCR, 72/72 agent tasks, 24/24 tool-recovery tasks, overlapping generation at concurrency four, and seven archive-retrieval checks through 407,877 input tokens. The short-generation probe completed, but both code responses and one explanation reached its 2,048-token limit; these are throughput samples, not complete-answer quality passes.

The final bounded mixed workload completed all 12 cycles: **49/50 correct in 1,034.79 seconds**, with zero preemptions. Its final 130,917-token archive request exhausted all 1,024 output tokens on reasoning and returned no final content. One retry with the unchanged request succeeded in 4.98 seconds with a warm prefix; the original score remains 49/50. Diagnose this failure before accepting the profile as fully qualified. Retain this case in the later output-budget experiment, without assuming a larger budget alone fixes it.

Raw requests/responses, actual token counts, finish reasons, timings, metrics, runtime versions, configuration and memory partition are archived in [Native Windows vLLM](Native-vLLM.md). Existing artifacts retain the profile name used when they were recorded. Preserve first-attempt failures and score retry recovery separately in future runs.

The [offline failure review](Native-vLLM.md#qualification-review-and-mixed-workload-diagnosis) is complete. The failed request found the correct codes but exhausted its reasoning allowance while reconsidering answer formatting; the scorer and forwarded budget were correct. The unchanged-budget retry recovered under different cache/concurrency conditions. The immediate failure mechanism is established; the cause of generation variation and a reliable mitigation still need controlled experiments. Server logs and a reproducible analysis with source hashes are archived. No new inference or full rerun was performed for this review, and the server remains stopped.

## 2. Standardize read/write reporting before the rerun

Every token-rate table must use **(read tk/s, write tk/s)**, with the timing source and aggregation stated.

1. Prefer directly measured prompt-processing duration (PP) and decode duration from attributable server/request telemetry.
2. Only when direct PP is unavailable, derive **PP = e2e - decode**. With streamed responses, decode starts at the first generated token, including reasoning, and ends at completion. This derived PP includes queueing, transport and frontend overhead; label it as derived.
3. Read rate is prompt tokens divided by PP. Report cache hits separately: full-context effective read rate and newly computed-token rate are different measurements.
4. Write rate uses tokens generated during the measured decode interval. For a first-token-to-completion interval, use `completion_tokens - 1` consistently.
5. Record e2e, PP, decode duration, token counts, PP source, cache state and concurrency alongside the tuple. Never subtract token rates to obtain PP.
6. Keep per-request phase rates separate from whole-run aggregate throughput. Overlapping requests cannot be treated as one serial PP/decode interval. Whole-run throughput may be shown as a separately labelled `(input, output)` tuple.
7. Backfill existing artifacts only where the needed timings/counts exist. Use `—` for missing measurements; do not relabel historical end-to-end output throughput as pure decode speed. Preserve raw evidence and save derived summaries separately.

The saved native streaming probes contain first-token, completion and usage data, so their phase tuples can be derived now. Direct per-request PP collection is still required for the rerun. Shared Prometheus counter deltas must not be attributed to one request when multiple requests completed in the interval.

## 3. Preserve references and develop a separate hybrid

Keep `qwen38fn-myllmbox` (native MTP) and `qwen38fn-cache-dflash` (WSLC DFlash2 + LMCache) unchanged as reference configurations.

Candidate: **`qwen38fn-myllmbox-dflash2`**, initially using native Windows, FP4-Local weights, native NVMe PLE and DFlash2 **without LMCache**. The installed wheel contains DFlash2 dispatch code; successful integration is not yet established.

Implementation gates:

1. Verify target/drafter architecture, hidden-state interfaces, vocabulary, shared embeddings/head, checkpoint revisions and position/YaRN settings.
2. Replace the MTP speculation configuration with DFlash2 and disable or adapt MTP-specific dynamic-depth, FP8-drafter and HEAD2 hooks. Do not run both draft paths together.
3. Validate Windows kernels, RecoverSSM/state handling, attention/KV layout and CUDA graph capture. Recompute memory and cache-block requirements instead of copying the old profile's geometry blindly.
4. Begin with the common 262,144-token context, three draft tokens and four sequence slots. Preserve enough output room and record actual memory use. Explore 409,600 context or additional slots only after the common configuration passes.
5. Qualify health, smoke/features, tool correctness and draft acceptance before performance comparisons. Reject a speed gain that reduces correctness or introduces empty final answers, truncation or instability.

If the native route has an incompatible kernel/state interface, document the concrete blocker and assess a separate WSLC FP4 + DFlash2 route. Do not silently replace the tested native reference.

## 4. Treat LMCache integration as a separate step

The current **88 GiB GPU partition** supports LMCache's host pool, cache structures and runtime allocations; it is not an inherent DFlash2 requirement. Native MTP is currently qualified at **96 GiB**. See [memory requirements](LMCache.md#memory-budget).

After a hybrid without LMCache passes, assess whether external caching improves the intended agent workloads enough to justify integration. Validate host-pool size, Mamba/cache-block alignment, CUDA VMM allocation/export, IPC/sharing, SSD restore admission and eviction. The current WSLC adaptations are not automatically portable to native Windows.

Compare separately labelled 8 GiB and, if viable, 4 GiB host-pool configurations. Keep the 4 GiB Windows headroom guard. Validate cold and warm reuse, restart restores and concurrent restores with cache-hit/transfer counters; a correct reply alone does not demonstrate a cache hit. Do not present a reduced-cache variant as the unchanged baseline.

## 5. Profile matrix

Run one serving profile at a time. Group runs by memory partition and record the actual partition on every result. Change it only as an explicit setup step before its group.

| Profile | Role | Runtime / draft | Context | LMCache | Partition for comparison |
| --- | --- | --- | ---: | --- | --- |
| `qwen38fn-baseline` | Target-only short-context control | WSLC / none | 32,768 | Off | Use the 88 GiB WSLC group; not an intrinsic requirement |
| `qwen38fn-mtp` | Short-context MTP control | WSLC / one-token MTP | 32,768 | Off | Same WSLC group |
| `qwen38fn-cache` | Cache-only long-context control | WSLC / none | 262,144 | On | 88 GiB for supplied settings |
| `qwen38fn-cache-mtp` | Existing MTP + cache control | WSLC / one-token MTP | 262,144 | On | 88 GiB for supplied settings |
| `qwen38fn-cache-dflash` | Primary recorded reference | WSLC / DFlash2 | 262,144 | On | 88 GiB for supplied settings |
| `qwen38fn-myllmbox` | New tested reference | Native / dynamic MTP | 409,600 | Off | 96 GiB for supplied settings |
| `qwen38fn-myllmbox-dflash2` | Proposed hybrid; not yet implemented | Native / DFlash2 | Start at 262,144 | Off initially | 96 GiB candidate; must qualify |

Prioritize the two references and the hybrid once it passes its implementation gates. Use the other profiles as controls to isolate draft/cache effects. Do not compare an unqualified hybrid as if it were ready.

## 6. Test matrix for the later rerun

| Test | Workload / settings | Applies to | Record / pass condition |
| --- | --- | --- | --- |
| Local checks | PowerShell parsing, configuration/lifecycle and CPU tests | Source tree once per relevant code change | All applicable checks pass; platform skips identified |
| Startup + smoke | Health, model identity, instruction, arithmetic, recall | Every profile | Correct nonempty answers, normal completion, memory recorded |
| Features | Streaming, JSON, tool round trip, reasoning, shapes, OCR | Every profile | Exact checks and `finish_reason`; raw evidence retained |
| Warm agents | 4 conversations × 3 tasks; C1/2/4 then reverse; thinking on, 1,024 output tokens | Every profile | 72 correct tasks, tasks/s, latency, truncation, preemption and acceptance |
| Recovery | 4 concurrent conversations × 6 tasks; thinking on, 1,024 output tokens | Every profile | 24 correct tasks; tool selection, transient retry and SKU correction |
| Scheduling | C1/2/4; fixed 256 generated tokens, EOS ignored | Every profile | Actual overlap and running/queued counts; phase and aggregate rates kept separate |
| Short generation | JSON, code, explanation; two repeats; existing 2,048-token thinking budget | Every profile | `(read, write)` tuples; JSON scoring; capped code/prose identified, not quality passes |
| Serving throughput | Existing 4K/16K input sweep, C1/2/4, 16 requests/point, 128 output tokens | Every profile | Completion count, phase rates, whole-run rates, TTFT and e2e latency; not an accuracy test |
| Multi-turn retrieval | Existing AIPerf workload: 16 sessions × 4 turns, C1/2/4, thinking on | Every profile within context budget | Correct turns, empty answers, initial/follow-up timing and retries |
| Archive retrieval | 4K, 16K, ~32K, 64K, 131K, 262K; native near-limit as a separate extension | Only lengths fitting each profile | All planted values, normal completion, actual rendered input tokens |
| RULER subset | Existing needle and variable-tracking tasks; 2 samples per eligible length | Only lengths fitting each profile | Upstream scores and truncation; distinguish from local archive checks |
| Bounded mixed workload | Existing 12 cycles / 50 checks, concurrent 65K/131K archives, vision, arithmetic and tools; 1,024-token output budget | Qualified long-context profiles | Correct checks, task latency, memory, preemptions and final health |
| Prefix-cache reuse | Cold prompt, identical warm prompt, appended turn; stable salt | Every profile at eligible lengths | Correctness plus measured cache-hit evidence, PP and decode separated |
| External SSD restore | Existing near-limit and concurrent restore procedures, including restart | LMCache profiles only | External hit tokens and completed restores; no false pass from cold recomputation |
| Longer endurance | Define duration and representative workload after bounded qualification | Finalist configurations | No crashes, invalid output, uncontrolled memory growth or cache-budget violations |

Client concurrency is not the number of server sequence slots. The short-context baseline/MTP profiles currently have one slot; requests at higher client concurrency may queue. Report that behavior instead of claiming concurrent decode. All context limits include input, tools, images, history and reserved output.

The Windows client currently supports agents/recovery/scheduling/short generation/mixed workloads. Before the full rerun, enable native access for the existing vLLM, AIPerf and RULER clients while preserving their pinned workloads and scoring. This work is pending; the current local archive check must not be labelled a RULER result.

## 7. Output-budget accuracy experiment

The [isolated replay pilot](Native-vLLM.md#focused-output-budget-replay-november-1-2026) is complete: two cold requests each at 1,024, 2,048 and 8,192 output tokens all passed, using 184–462 tokens. Direct server PP/decode telemetry was attributable for every request. This did not reproduce the original concurrent failure or establish an accuracy improvement; the full-suite rerun remains deferred. No default allowance changed.

The [concurrent replay pilot](Native-vLLM.md#concurrent-output-budget-replay-november-1-2026) is also complete: three batches per allowance passed all 36 task checks, with verified four-way overlap, zero archive cache hits and no retries or preemptions. Only the archive budget changed; the background tasks retained 1,024 tokens. Archive responses used 184–574 tokens, so the extra allowance was not needed in these samples. This replayed the failing cycle's tasks, not the preceding eleven-cycle history, and leaves the original 49/50 score unchanged.

The [code/explanation comparison](Native-vLLM.md#code-and-explanation-budget-comparison-november-1-2026) is complete: first-attempt completion was 0/6 at 1,024, 2/6 at 2,048 and 6/6 at 8,192. All four completed LRU implementations passed executable checks, but one 8K example had an incorrect expected-output comment; prose review also found qualifications. Three of the six 8K responses used more than 2,048 tokens. This supports 8,192 as the candidate for longer thinking-enabled tasks, not an automatic universal default change.

Continue the controlled comparison of **1,024, 2,048 and approximately 8K output tokens** on harder objectively scored multi-turn/tool, arithmetic, retrieval and structured-output tasks, then compare profiles with the same selected allowance. Replay the full mixed sequence during the deferred rerun. Use 8,192 as the standard 8K point, or 8,196 if reproducing evidence that specifies that exact value. Keep the chosen value explicit in every artifact.

The 1,024-token value is the current agent benchmark allowance, not a universal server or client default. Record benchmark limits and client settings separately.

Use identical prompts, histories, tools, seeds/sampling settings and concurrency. Preserve tool-call reasoning and completed tool results. Reserve input space for the larger allowance rather than silently overflowing the context window.

For the recorded mixed failure, first repeat the exact saved request at 1,024 tokens in cold/warm and isolated/concurrent conditions. Then change only the output budget. Keep optional MTP-off and explicit-format controls separately labelled; validate runtime support before using the former. This separates budget effects from cache/concurrency and workload changes. Both original archive revisits reported zero cached tokens, so add an explicit prefix-reuse check rather than assuming those passes demonstrated cache hits.

The existing 72-task agent test already scores 100%, so it alone cannot demonstrate an accuracy improvement. Include the capped code/explanation cases and harder, objectively scored multi-turn/tool, arithmetic, retrieval and structured-output tasks. For code, assess executable correctness in a bounded isolated test harness, not merely whether a code block was returned.

Report first-attempt correctness, truncation, empty final answers, reasoning/output token counts, `(read, write)` rates, e2e latency and correct tasks/s. Retry an empty required final answer once with unchanged history and preserve the original failure in the score; report retry recovery separately. A larger token allowance is not automatically more accurate or faster. Select a new default only when the measured correctness/latency tradeoff supports it.

## 8. Review and choose defaults

Produce one comparison with immutable run IDs and an explicit distinction between fresh and historical results. Compare common workloads first, then each profile's capacity extensions. Keep the different GPU partitions, weights, cache budgets, runtime versions and measurement sources visible.

Choose the serving profile, cache configuration and output allowance using correct work completed, latency, memory and stability. Keep working references available until the candidate passes. Update the default only after reviewing those results; do not change it merely because a candidate has a higher token rate.
