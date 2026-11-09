# n1x-ai documentation

Use this guide to install, operate, evaluate, and maintain the local model server. For an overview and first launch, start with the [README](../README.md).

## Setup and operation

| Task | Guide |
| --- | --- |
| Check requirements and choose an installation path | [Installation](Installation.md) |
| Select profiles, change settings, connect clients, or manage storage | [Configuration](Configuration.md) |
| Identify every model file and volume needed by best and the top ten | [Model assets](Model-assets.md) |
| Diagnose startup, memory, or connection problems | [Troubleshooting](Troubleshooting.md) |
| Integrate an application or agent harness | [API guidance](../AGENTS.md) |

## Runtime maintenance

| Task | Guide |
| --- | --- |
| Inspect or rebuild the selected runtime; plan dependency upgrades | [MyLLMBox Linux](MyLLMBox.md) |
| Understand cache budgets, eviction, and restore behavior | [LMCache](LMCache.md) |
| Work with the separate Windows reference runtime | [Native vLLM](Native-vLLM.md) |
| Change code, validate patches, or run local checks | [Development](Development.md) |

## Evaluation

| Task | Guide |
| --- | --- |
| Understand the selected profile and ranked alternatives | [Component review and top ten](Profile-review.md) |
| Inspect measured results and retained evidence | [Benchmarks](Benchmarks.md) |
| Review DFlash2 reasoning and temperature trials using the existing weights | [Request parameter trials](Parameter-trials.md) |
| Compare 20%/50% GPU sharing observations and C2/C8 scaling | [GPU priority repeat](GPU-priority-trial.md) |
| Plan or run speed/depth and near-full quality comparisons | [Speed and capacity benchmarks](Speed-benchmarks.md) |
| See measured coverage and remaining gaps | [Test coverage](Test-plan.md) |
