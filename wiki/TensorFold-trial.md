# TensorFold feasibility trial

`qwen38-cache-tensorfold-dflash` records the requested engine replacement for
`qwen38fn-best`. It is a feasibility profile, not a working serving profile.
The default remains `qwen38fn-best`.

The profile preserves the requested W4 AutoRound target, external DFlash2, 262,144
context, eight slots, 8,192 output cap, FP8 KV allocation, and LMCache budgets.
TensorFold cannot yet apply all those settings. Listing profiles marks DFlash2 as
blocked and LMCache as unwired; neither is silently replaced with MTP or native caching.
Local configuration still overrides profile values under the normal configuration rules.

## Repeat the attempt

```powershell
.\n1x.ps1 setup -Profile qwen38-cache-tensorfold-dflash
.\n1x.ps1 test -Profile qwen38-cache-tensorfold-dflash -PrintOnly
.\n1x.ps1 test -Profile qwen38-cache-tensorfold-dflash
```

Setup downloads the 1.2.9 Linux aarch64 release into ignored `.build/` and verifies
its pinned SHA-256. Test uses the existing immutable MyLLMBox image for CUDA
userspace, overrides the entrypoint with TensorFold, and launches no vLLM process.
The model, drafter and release directory are mounted read-only. No port is published,
network access is disabled, and no production cache volume is mounted or modified.
An occupied GPU (>8 GiB used) refuses the trial without stopping another service.
Each command is bounded to 120 seconds plus ten seconds for forced termination.

Test records version, capabilities, checkpoint info, an external-drafter launch,
and a separate target-only diagnostic with `--no-drafts`. It saves arguments, exit
codes, effective requested settings, metadata hashes and raw logs under
`results/tensorfold-trial-*`. A failure returns an error after recording evidence.
A timeout does not establish loading success. `info` is metadata inspection, not
loader validation: it described this quantized checkpoint as full precision.

The probes do not apply LMCache, prepared PLE maps, vLLM scheduler settings, KV
precision/allocation or draft depth. Those omissions are recorded in `result.json`.
They test the earlier loader/drafter prerequisites only. `start`, full lifecycle
actions and benchmarking refuse this experimental backend until it is integrated.

## Observed on 2026-11-15

TensorFold **1.2.9**, NVIDIA RTX Spark N1X, 96 GiB GPU partition. Archive SHA-256:
`91e90c489bef3d217c2d3d51ce34d2a9a160ffc46b36e8b25026016b90f32f04`.
Base image: `sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc`.

| Probe | Result |
| --- | --- |
| Version / capabilities / info | Exit 0; CUDA `nvidia-sm121` detected |
| W4 target + external DFlash2 | Exit 1: `--drafter loads a separate drafter, and this CUDA family drafts with its own MTP head: serve without --drafter` |
| Same W4 target, `--no-drafts` | Exit 1: `config.json's quantization_config.quant_method differs from the supported Flash Next CUDA layout`, then `UnsupportedCheckpoint` |

The binary advertises `qwen4_exp` formats `mlx-q4g32` and `modelopt-mixed`.
The installed checkpoint declares AutoRound integer 4-bit, group 128, symmetric,
with `auto_round:auto_gptq` packing. These are observed loader refusals, not just
an inference from documentation. Neither attempt reached API readiness; no
generation, task-quality, cache or throughput benchmark ran.

Original scripted evidence: `results/tensorfold-trial-20261115-130203-fcba3558/`.

## What would make the exact replacement feasible?

1. Implement and validate loading of the existing AutoRound/GPTQ layout, potentially
   through a lossless repacking adapter. Renaming configuration fields is insufficient.
2. Integrate the existing external DFlash2 checkpoint with Flash Next CUDA verification.
3. Integrate LMCache and the prepared PLE representation, and map or explicitly
   qualify the requested scheduler/KV settings.

These are separate engineering tasks; this trial does not establish that each is
feasible or that their combined performance would improve. After loading succeeds,
the next gate is a short content/tool smoke test and a small C1/C2 timing comparison,
not a full baseline suite.

Upstream: [release 1.2.9](https://github.com/ashhart/TensorFold/releases/tag/v1.2.9),
[Flash Next CUDA recipe](https://github.com/ashhart/TensorFold/blob/main/docs/recipes/flash-next-cuda.md).
