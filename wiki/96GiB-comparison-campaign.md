# 96 GiB comparison campaign

This campaign tests speed opportunities after the [initial 96 GiB tool qualification](Near-full-tools-96GiB.md). It is a screening comparison on the existing local runtime image, with no matched 88 GiB control. Results must be read from the output artifacts; launching the campaign does not establish a speed improvement.

## Completed campaign and deployment selection

[Compact comparison results and source hashes](data/campaign96-summary.json) retain the completed and partial controls, cache-hit evidence, and comparison limits without requiring the local raw archive.

On November 13, 2026, `qwen38fn-best` was promoted to the tested 96 GiB runtime, batch8K/KV15, slots8, and LMCache RAM4/SSD160. The retained KV15 report (`results/benchmarks/campaign96-20261112-105009/kv15-on-8k-attempt1-report.json`) records 24/24 correct tasks at C2 in 1,046.20 seconds and 24/24 at C4 in 2,484.56 seconds. KV11/batch8K C4 completed 24/24 in 3,249.41 seconds, giving KV15 about 31% higher correct-work throughput. Its C2 control was incomplete, so that comparison does not establish a C2 speed winner.

The final controller receipt is `results/benchmarks/campaign96-finish-20261113-164038/status.json`; its comparison retains completed earlier stages. Completion does not make incomplete controls valid. The cache-off batch8K control remained partial; displaced replay showed external hits for only one of two replay selections per repeat, and restart restore was not measured. Earlier runtime and transport failures remain part of the evidence. Promotion is a practical deployment decision, not proof that 96 GiB beats 88 GiB or that LMCache always improves speed. This campaign is closed; the gaps remain documented rather than scheduled for another round.

## Workload and order

Four independent histories start at 250,000 rendered tokens (±8), retain an 8,192-token output allowance, and perform three inventory/price tool round trips. Each configuration runs C2→C4 then C4→C2, giving 48 planned first-attempt tasks. Correctness, actual cache usage, phase timing, scheduler samples, effective configuration, memory headroom and server logs are retained. Configuration order itself is not counterbalanced, so small differences require a follow-up confirmation.

1. Batch8K, LMCache on: compare KV11 with KV15.
2. Choose KV15 for follow-up tests only if all tasks pass and combined correct-work throughput improves by at least 5%; otherwise retain KV11. Report both concurrency points separately even if they disagree.
3. At that KV allocation, compare LMCache off with the measured LMCache-on batch8K configuration. Native prefix caching remains enabled in both.
4. Run displaced replay with cache off and on. Each of two repeats primes two near-full tool prompts, verifies native residency using immediate same-prompt repeats, sends four fresh near-full pressure histories, then replays the original two prompts at C2 and completes their tool continuations. Replay-selection counter snapshots exclude subsequent continuation hits. External restoration requires demonstrated prior native residency, zero native replay hits, positive external replay hits and positive cache coverage for both replay selections. Otherwise the evidence remains partial or unverified.
5. Compare batch4K with the measured batch8K LMCache-on configuration at the chosen KV allocation.

All stages keep the model, drafter, thinking/xhigh, seed, temperature, context, output allowance, slots, and cache pool settings fixed except the named comparison variables. New salts make initial prompts cold; salts remain stable within reused histories. No generation retries replace first scores. Only read-only tokenization transport failures get bounded retries. Empty-final diagnostic retries remain separate.

## Running and inspecting

The runner owns the model service during the campaign and can take several hours. Start only one campaign and avoid unrelated API traffic:

```powershell
python benchmarks/campaign96.py --out results/benchmarks/<new-campaign>
```

`status.json` identifies the current stage and process IDs; `heartbeat.json` records command progress. Each stage has its own log, host record and raw probe directory. `decisions.json` records provisional comparison choices. `summary.json` and `comparison.md` are written when the campaign finishes or fails. A lock at `.state/campaign96.lock` prevents concurrent campaigns.

The controller now checks API health during probes. Three consecutive failures terminate the interrupted probe. When the server is unhealthy, it can recreate the same configuration and restart the whole stage in a fresh `attemptN` directory, with at most two recovery retries. Healthy-server correctness failures are not retried this way. Failure records remain separate and are listed in the campaign summary; a recovered speed measurement does not establish failure-free reliability. On November 12, a retained failure showed a vLLM scheduler assertion while processing completed external KV transfers (`assert req_id in self.requests`). Controller recovery does not repair that runtime defect.

Create an empty `STOP` file in the campaign output directory to stop after the current command and restore settings. Do not kill the controller if normal restoration is desired. The runner saves the exact original `config.local.psd1`, changes only `KvCacheBytes`, `UseLMCache` and `BatchedTokens`, and restores the original bytes and running profile in its finalization path. It refuses to overwrite configuration edited externally while it owns the service. Existing cache volumes are retained.

The campaign verifies the 96 GiB partition, runtime identity, at least 4 GiB host physical/commit headroom and 2 GiB GPU headroom before each workload. The existing runtime memory monitor remains active. These checks do not guarantee that every later workload peak will fit; failures remain recorded and can stop the campaign.

On November 11, the first setup attempt in `results/benchmarks/campaign96-20261111/kv11-on-8k` hit a localhost timeout during token calibration, before scored generation. The server remained healthy. That attempt is preserved separately from the fresh campaign run.
