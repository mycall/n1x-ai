# Troubleshooting

## API is not ready

```powershell
.\n1x.ps1 status
.\n1x.ps1 logs
.\n1x.ps1 wait -TimeoutSeconds 7200
```

Cold loading and compilation can take minutes. A WSLC transport timeout alone does not show that the container stopped. The wait command retries temporary failures and leaves the container available for inspection on timeout.

If settings differ from the existing container, run `recreate`, then `wait`. Check that another profile is stopped and that your selected Windows port is free.

After a cache container exits unsuccessfully, `start` and `restart` replace it while preserving the model and named volumes. Use `recreate` explicitly if a startup allocation failure persists.

## LAN or agent client connection fails

First confirm `n1x.ps1 wait` succeeds locally. Then follow [LAN access](Configuration.md#lan-access) for the remote health check, firewall UAC handling, and container binding, or [agent clients](Configuration.md#agent-clients) for model selection, reload behavior, and configuration conflict warnings. A registered model is not proof of a working API or tool-call workflow.

## Missing models or PLE table

Check `ModelRoot` against the [asset inventory](Model-assets.md). The recovery path depends on the runtime:

| Runtime | Recovery |
| --- | --- |
| Best / 4K alternate | Restore missing weights or prepared PLE first. Best's setup validates them; it only creates missing LMCache storage. See [prerequisites](MyLLMBox.md#existing-installation). |
| Original WSLC reference | Rerun [reference setup](Installation.md#original-wslc-reference) to resume downloads and prepare missing native PLE. |
| Native Windows reference | Restore the external FP4 model/runtime using [native installation guidance](Native-vLLM.md#installation-and-configuration). |

To rebuild the original native PLE copy from an available host source:

```powershell
.\prepare-native-ple.ps1
```

This does not generate the MyLLMBox prepared PLE map. Launch validation does not automatically restore large assets removed during cleanup.

## Memory or cache failures

Check Windows available memory, the GPU partition, and container logs. Adjust the [memory budget](LMCache.md#memory-budget), then recreate. For a stale or missing memory-monitor message, restart the profile to refresh the monitor; do not disable the guard as a memory fix.

For `invalid resource handle` during cache sharing, verify that the selected image includes the project's [compatibility patches](LMCache.md#compatibility). Best uses the [MyLLMBox build path](MyLLMBox.md#rebuild-lmcache-and-the-runtime); the original reference uses `build.ps1 -CacheOnly`. An unpatched upstream image does not include these adaptations.

## Disk usage remains high after cleanup

Cache limits apply per volume; old trial volumes can accumulate separately. Deleting data inside WSLC does not necessarily shrink its backing VHDX. Follow [cleanup and offline compaction](Configuration.md#cleanup-and-disk-reclamation), preserving the assets listed in [Model assets](Model-assets.md).

## Unexpected responses

Run the [service validation checks](Development.md#service-validation), then review the [API guidance](../AGENTS.md) for output budgets, tool calls, and vision responses.

## Diagnostics

`n1x.ps1 doctor` reports WSLC, images, GPU status, and the configured model path. Do not publish model requests or cache contents when sharing diagnostics.
