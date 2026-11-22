# Serving profiles

Start with **`qwen38fn-best`** for the standard 96 GiB installation. It uses the 4-bit AutoRound target (W4), DFlash2 with three draft tokens, a 15 GiB key/value (KV) cache, and an 8,192-token prefill batch. It completed 48/48 near-full tool tasks with two and four clients. At four clients, it processed about 31% more correct tasks per second than the 11 GiB control. The two-client control was incomplete. [Default profile comparison](96GiB-comparison-campaign.md)

## NVFP4-GDN-MSE comparison trial

Select `qwen38fn-nvfp4-gdn-mse` to try the mixed-precision checkpoint at revision `03f4a0570496bbe741189f4a2a7d611679e85406` on the 96 GiB partition. It uses the existing checkpoint-PLE MyLLMBox recipe, Marlin experts, MXFP8 b12x dispatch and DFlash2 K3. Its runtime cache and LMCache volume are private to this profile. The 36 shards contain 98.53 GiB of tensor data. GPU fit depends in part on how the loader maps the embedded PLE table. Successful startup, accuracy and throughput still require measurement.

With the serving port and GPU available, run the following from this checkout. Setup resumes missing pinned target files under the configured model root. Use `-SkipDownload` for offline setup. The separate upstream prefill companion is retained for the alternate loader experiment. This profile mounts the target and DFlash2.

```powershell
$trial = 'qwen38fn-nvfp4-gdn-mse'
.\n1x.ps1 setup -Profile $trial
.\n1x.ps1 start -Profile $trial
.\n1x.ps1 test -Profile $trial
.\benchmark.ps1 -Profile $trial -Suite recovery
.\benchmark.ps1 -Profile $trial -Suite speed -SpeedDepths 4096,250000 -SpeedConcurrency 1,4 -SpeedMode cold
.\n1x.ps1 stop -Profile $trial
```

Repeat the same workloads with `qwen38fn-best` and compare task success before comparing speed. These runs compare serving profiles, including their PLE and kernel settings.

## Choose by workload

| When to use it | Profile | What was measured |
| --- | --- | --- |
| Host or SSD prefix-cache capacity pressure | `qwen38fn-w4-kv15-bf16` | 19.9% smaller LMCache occupancy at the same GPU capacity on two 16–17K prompts. [Compression trial](Compression.md) |
| Standard 96 GiB deployment | `qwen38fn-best` | First-attempt tool selection and continuation at about 250K input tokens. Restart coverage was outside this comparison. |
| Fastest of the two K5 profiles on four concurrent near-full tool histories | `qwen38fn-w4-kv20-8k-k5` | 384.60 s mean across three runs. After restart it restored 30 of 31 complete chunks per prompt. |
| Full cacheable-prefix recovery after restart | `qwen38fn-w4-kv20-4k-k5` | 406.03 s mean on the same workload. Restored all 31 complete chunks in each of three checks, with more GPU headroom. |
| Keep three draft tokens with a larger KV pool | `qwen38fn-w4-kv19` or `qwen38fn-w4-kv19-4k` | The 8K batch was faster on the C4 tool workload. The 4K batch also passed strict restart recovery. |
| Use the 88 GiB MyLLMBox configuration | `qwen38fn-lmcache-4k` | Uses the W4 bundle with a separately pinned image and an 11 GiB KV pool. The 88 and 96 GiB partitions lack a matched speed comparison. |

**How to read the K5 result.** K5 means five speculative draft tokens. Both profiles completed 36/36 long tool tasks. On the short screen, batch8K scored 96/96 and batch4K scored 95/96. All restart answers were correct for both profiles. The restore test also counts how many complete chunks came back from SSD, since the model can recompute missing tokens. The 4K batch recovered 97.02% of all prompt tokens, including every complete chunk. [Paired measurements, headroom, and test conditions](FP4-Local-AZ-trial.md#three-run-kv20k5-averages)

## Other runtimes and weights

- **FP4-Local-AZ.** The AZ profiles require a separate checkpoint with its own PLE data. The KV19 comparison found similar C4 times for W4 and AZ in a single run. [Weights, settings, and results](FP4-Local-AZ-trial.md#configuration)
- **Original WSLC reference.** Use the baseline, MTP, and cache profiles to reproduce the original runtime or compare drafting methods. [Reference setup](Installation.md#original-wslc-reference) · [Profile settings](Configuration.md#profiles)
- **Native Windows.** `qwen38fn-myllmbox` uses a separate ARM64 Python installation and FP4 model with dynamic MTP. [Native installation](Native-vLLM.md#installation-and-configuration)

Run `.\n1x.ps1 list profiles` to see effective settings, including local overrides. Stop the active profile before switching. Pass the selected name with `-Profile` on subsequent commands, or set `DefaultProfile` in `config.local.psd1`. The HTTP model ID stays `qwen/qwen38fn-best`. [Service commands](Configuration.md#lifecycle)

For original rankings, including configurations without a selectable profile, see the [historical component comparison](Historical-profile-comparison.md). For the scope of each result, see [test coverage](Test-plan.md).
