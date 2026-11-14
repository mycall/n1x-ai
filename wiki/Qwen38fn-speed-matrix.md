# qwen38fn-best read/write speed matrix

These November 8 results describe the historical 88 GiB/KV11 profile. The [current best](Profile-review.md) uses 96 GiB/KV15 and a different runtime image; this matrix has not been rerun for it.

Completed all **32 cells** with **96 measured bursts / 432 requests**, three independent cold bursts per cell. Every request produced exactly 512 tokens; all streams finished with zero cached tokens. Existing model weights were reused.

[Interactive charts](data/qwen38fn-speed-matrix-20261108.html) · [Full numbers and per-request evidence](data/qwen38fn-speed-matrix-20261108.json).

C1–C8 counts submitted clients; requests may wait for capacity. Compare read rates including and excluding waiting before drawing conclusions about responsiveness.

Read including waiting (tokens/s per request; input / client time to first token):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 2,080.4 | 1,897.7 | 1,878.4 | 1,899.5 |
| C2 | 999.3 | 1,598.5 | 1,106.2 | 991.9 |
| C3 | 768.2 | 1,064.4 | 896.2 | 968.3 |
| C4 | 722.2 | 772.4 | 935.0 | 705.1 |
| C5 | 606.4 | 655.6 | 581.0 | 512.0 |
| C6 | 536.7 | 539.6 | 431.5 | 458.0 |
| C7 | 491.3 | 434.4 | 462.3 | 521.3 |
| C8 | 459.9 | 440.7 | 436.7 | 374.9 |

Read excluding queue time (tokens/s per request; input / scheduled-to-first-token time):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 2,111.6 | 1,912.6 | 1,885.7 | 1,906.8 |
| C2 | 1,205.1 | 2,255.0 | 1,485.2 | 1,379.4 |
| C3 | 983.8 | 1,508.3 | 1,550.5 | 1,866.5 |
| C4 | 914.7 | 1,147.7 | 1,957.0 | 1,754.5 |
| C5 | 777.1 | 984.4 | 1,410.6 | 1,474.4 |
| C6 | 756.8 | 863.1 | 1,298.2 | 1,650.1 |
| C7 | 693.6 | 730.8 | 1,599.2 | 1,908.2 |
| C8 | 701.0 | 810.4 | 1,840.6 | 1,597.9 |

Write (tokens/s per request; 511 / first-to-last-token time):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 45.79 | 34.57 | 30.74 | 48.34 |
| C2 | 26.06 | 27.52 | 12.62 | 4.07 |
| C3 | 18.45 | 22.88 | 9.28 | 5.14 |
| C4 | 18.08 | 16.37 | 8.32 | 4.81 |
| C5 | 17.38 | 16.59 | 4.73 | 3.08 |
| C6 | 20.41 | 14.97 | 4.19 | 3.75 |
| C7 | 19.14 | 12.89 | 4.35 | 4.33 |
| C8 | 17.30 | 12.25 | 5.97 | 3.46 |

Aggregate output throughput (tokens/s across the complete burst, including prefill/queue):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 39.01 | 26.81 | 9.94 | 3.45 |
| C2 | 42.63 | 42.35 | 10.22 | 2.62 |
| C3 | 44.77 | 50.62 | 11.90 | 3.52 |
| C4 | 58.11 | 47.73 | 15.45 | 3.38 |
| C5 | 68.58 | 58.37 | 11.48 | 2.76 |
| C6 | 91.91 | 60.71 | 10.30 | 3.13 |
| C7 | 100.13 | 59.90 | 12.19 | 3.60 |
| C8 | 104.30 | 66.25 | 14.68 | 3.04 |

Mean client time to first token (seconds, including queue):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 1.97 | 4.32 | 34.89 | 137.73 |
| C2 | 4.10 | 5.12 | 59.24 | 263.77 |
| C3 | 5.33 | 7.70 | 73.13 | 270.20 |
| C4 | 5.67 | 10.61 | 70.09 | 371.07 |
| C5 | 6.75 | 12.50 | 112.79 | 510.96 |
| C6 | 7.63 | 15.18 | 151.87 | 571.24 |
| C7 | 8.34 | 18.86 | 141.75 | 501.88 |
| C8 | 8.91 | 18.59 | 150.06 | 697.78 |

Mean server queue time (seconds):

| Concurrency | 4K | 8K | 64K | 262K window |
| --- | ---: | ---: | ---: | ---: |
| C1 | 0.01 | 0.02 | 0.03 | 0.06 |
| C2 | 0.68 | 1.46 | 13.62 | 72.23 |
| C3 | 1.14 | 2.23 | 28.62 | 127.75 |
| C4 | 1.17 | 3.22 | 34.48 | 218.97 |
| C5 | 1.46 | 3.43 | 64.03 | 330.81 |
| C6 | 1.81 | 4.29 | 99.09 | 409.86 |
| C7 | 2.01 | 5.97 | 98.30 | 362.00 |
| C8 | 2.50 | 6.82 | 112.04 | 530.89 |

## Concurrency effect on aggregate throughput

| Input/window | C8 / C1 output throughput | Highest measured aggregate output throughput |
| --- | ---: | --- |
| 4K | 2.67× | C8 (104.30 tok/s) |
| 8K | 2.47× | C8 (66.25 tok/s) |
| 64K | 1.48× | C4 (15.45 tok/s) |
| 262K | 0.88× | C7 (3.60 tok/s) |

These ratios cover the complete fixed-work burst, including prefill, waiting and decode. Per-request read/write rates above answer a different question: how quickly an individual stream progresses during its scheduled phases. Concurrent decode intervals include stalls while other requests prefill. Use the client TTFT table when estimating user-visible waiting.

Clocks varied during the sweep. At 07:43 UTC the driver reported the **Reliability** clock-limiting policy active, with hardware thermal slowdown inactive; subsequent clock-event samples and per-cell clock/power ranges are retained. NVIDIA's [NVML reference](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlClocksEventReasons.html) identifies that policy as limiting clocks but does not establish the underlying cause on this host. Compare burst ranges when assessing small differences; the observations include this changing host condition. No clock, power, GPU sharing or partition settings were changed.

## Protocol and reproduction

The common load generator is the installed **vLLM 0.32.0 `vllm bench serve`**, using its `openai` completions backend and custom JSONL dataset. See the [official CLI reference](https://docs.vllm.ai/en/latest/cli/bench/serve/). Each burst sends C independent requests immediately (`--request-rate inf`, `--num-prompts C`, `--max-concurrency C`). Every request uses greedy decoding (temperature 0), `--ignore-eos` and `--custom-output-len 512`. The benchmark/data-order seed is 42; an API generation seed is not explicitly supplied. Endpoint ready checks and benchmark warmups are disabled within measured bursts. Separate C8/8K and C1/near-full warmups are excluded.

The local harness renders the installed chat template explicitly with thinking enabled and `reasoning_effort=xhigh`, then passes that prompt through completions with `--skip-chat-template`. Input lengths are calibrated with the local tokenizer, with at most four tokens below the target; actual counts are retained for every request. The 4K/8K/64K targets are 4,096/8,192/65,536 input tokens. **262K means the 262,144-token total window:** target input is 261,632, reserving 512 tokens for generation. Long scratch candidates generated during calibration are never submitted to inference.

The custom corpus is deterministic technical reference prose with varied record numbers and operations. Every request has an independent early prefix and cache salt. The three bursts per cell are shuffled using seed 42 to reduce test-order bias; request content can be reconstructed from the retained run ID and source. Cold means zero reused prompt/KV tokens, with model weights resident and normal model/PLE/OS caching active. This workload measures fixed-window speed, including reasoning tokens; it does not score completed answers or long-context correctness.

A local aiohttp forwarding proxy leaves response bytes unchanged while retaining each response's usage, finish reason and server timing metrics. The unmodified common benchmark retains client TTFT, TPOT, latency, throughput and speculative-decode statistics. Read = summed input tokens / summed scheduled-to-first-token seconds; write = summed `(output_tokens - 1)` / summed first-to-last-token seconds. Server queue time is excluded from these phase rates and shown separately. Aggregate throughput = summed tokens / summed common benchmark burst durations. Benchmark CLI startup and dataset construction are excluded from burst durations.

The measured historical profile used DFlash2 **K3**, standard FP32 SSM, BF16 indexer, FP8 target KV, 11 GiB KV, eight server slots, 8K prefill batch, and LMCache RAM4/SSD160. Image and configuration identities, exact commands, request timings, wave ranges, GPU telemetry summaries and source hashes are retained in the JSON. Eight clients do not imply eight resident near-full histories. Results describe this host, corpus, fixed output window and recorded clock/power conditions.

The missing pandas benchmark-client dependency was installed in a separate `/cache/n1x-bench-deps` directory (about 12 MB plus small date/time dependencies). No serving packages or model weights changed. The service was initially stopped and is stopped again after successful completion.

The user paused the sweep after 92 of 96 measured bursts on November 9. The host restarted during the pause; the last four bursts ran after reloading the same image, configuration and existing weights. The original checkpoint and run ID were preserved. Burst timings exclude the pause and service startup. The resumed C1/262K cell includes the first measured request after reload, so normal model/OS caching can differ from earlier rounds. Pause/resume timestamps and the resumed burst names are retained in the JSON.

To reproduce against the running best container with the same client dependencies available:

```powershell
Copy-Item benchmarks/vllm_speed_matrix.py .state/n1x-qwen38fn-best/vllm_speed_matrix.py
wslc exec n1x-qwen38fn-best env PYTHONPATH=/cache/n1x-bench-deps python3 /state/vllm_speed_matrix.py --out /cache/my-fresh-speed-matrix
# Copy the completed directory out; the destination needs a trailing separator.
wslc cp n1x-qwen38fn-best:/cache/my-fresh-speed-matrix results/benchmarks/
python benchmarks/vllm_speed_matrix_report.py results/benchmarks/my-fresh-speed-matrix --output results/benchmarks/my-speed-report
```

The harness checks `/health` before submitting work, checkpoints each burst, and stops on invalid responses. The reporter rejects missing bursts, wrong output lengths, cache hits and missing server timings. Raw common benchmark JSON/logs, response records, before/after Prometheus snapshots and host telemetry remain under `results/benchmarks/qwen38fn-best-matrix-20261108/` locally; compact evidence is published above. No failed measured request is silently replaced.
