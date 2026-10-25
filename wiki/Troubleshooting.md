# Troubleshooting

## API is not ready

```powershell
.\n1x.ps1 status
.\n1x.ps1 logs
.\n1x.ps1 wait -TimeoutSeconds 7200
```

Cold loading and compilation can take minutes. A WSLC transport timeout alone does not show that the container stopped. The wait command retries temporary failures and leaves the container available for inspection on timeout.

If settings differ from the existing container, run `recreate`, then `wait`. Check that another profile is stopped and that your selected Windows port is free.

After a cache container exits unsuccessfully, `start` and `restart` replace it while preserving the model and named volumes. Use `recreate` explicitly if a startup allocation failure persists. The memory monitor must remain active throughout loading; a stale snapshot stops the services.

## Missing models or PLE table

Verify ModelRoot and directory names in [Installation](Installation.md). Rerun setup to download missing files. To rebuild only the native PLE copy:

```powershell
.\prepare-native-ple.ps1
```

The launch validates a pinned-revision native-volume manifest. It does not automatically recopy a large table.

## Memory or cache failures

Check Windows available memory, the GPU partition, and container logs. Close unnecessary applications, reduce `LmcacheL1GiB`, concurrency, or context demand, then recreate. The memory guard message distinguishes low host memory from a stale/missing monitor. Restart the profile to refresh the monitor; do not disable the guard as a memory fix.

For `invalid resource handle` during cache sharing, verify that the cache profile uses the project's patched `n1x-ai:lmcache` image. Rebuild it with `build.ps1 -CacheOnly`. An unpatched upstream image does not include this platform's VMM adaptations.

## Unexpected responses

Run `n1x.ps1 test` and `n1x.ps1 test -Suite features`. Focused checks cover streaming, JSON, tools, reasoning, and vision; they do not establish general accuracy. Inspect `finish_reason`, give reasoning enough output budget, and validate tool arguments. OCR may emit HTML or truncate. Validate long-context vision separately.

## Diagnostics

`n1x.ps1 doctor` reports WSLC, images, GPU status, and the configured model path. Local checks write their current output under ignored `.state/checks`. Do not publish model requests or cache contents when sharing diagnostics.
