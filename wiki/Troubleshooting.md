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

Verify ModelRoot and directory names in [Installation](Installation.md). Rerun setup to download missing files. To rebuild only the native PLE copy:

```powershell
.\prepare-native-ple.ps1
```

The launch validates a pinned-revision native-volume manifest. It does not automatically recopy a large table.

## Memory or cache failures

Check Windows available memory, the GPU partition, and container logs. Adjust the [memory budget](LMCache.md#memory-budget), then recreate. For a stale or missing memory-monitor message, restart the profile to refresh the monitor; do not disable the guard as a memory fix.

For `invalid resource handle` during cache sharing, verify that the cache profile uses the project's patched `n1x-ai:lmcache` image. Rebuild it with `build.ps1 -CacheOnly`. An unpatched upstream image does not include this platform's VMM adaptations.

## Unexpected responses

Run the [service validation checks](Development.md#service-validation), then review the [API guidance](../AGENTS.md) for output budgets, tool calls, and vision responses.

## Diagnostics

`n1x.ps1 doctor` reports WSLC, images, GPU status, and the configured model path. Do not publish model requests or cache contents when sharing diagnostics.
