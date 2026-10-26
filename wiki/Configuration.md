# Configuration

Settings merge in this order: `config.psd1`, the selected profile in `profiles/`, ignored `config.local.psd1`, then `-ModelRoot` and `-Port` command arguments. Local values therefore override profile settings. Copy `config.local.example.psd1` when configuring manually.

```powershell
@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'cache-dflash'
    Port = 8000
}
```

## Profiles

| Profile | Context | Speculation | LMCache | KV allocation |
| --- | --- | --- | --- | --- |
| baseline | 32,768 | Off | Off | 4 GiB |
| mtp | 32,768 | One draft token, Triton | Off | 4 GiB |
| cache | 262,144 | Off | On | 8 GiB FP8 |
| cache-mtp | 262,144 | One draft token, Triton | On | 8 GiB FP8 |
| cache-dflash (default) | 262,144 | Three DFlash2 draft tokens | On | 8 GiB FP8 |

Context includes input and output. DFlash2 allows four scheduled sequences; the other cache profiles allow up to 16, but concurrent requests share the KV pool. Output length, simultaneous prefill, vision, and host applications affect capacity. See [LMCache](LMCache.md#memory-budget) for memory controls and [Benchmarks](Benchmarks.md) for measured workloads.

MTP changes acceptance and throughput with workload. Choose the profile using representative application requests rather than assuming more draft tokens are faster.

## Scheduling

`BatchedTokens` is the scheduler's per-step token budget, not the number of sessions. DFlash2 and MTP use 4,096; their cache blocks are 1,664 and 2,048 tokens respectively. A budget of one block can serialize admission. The target-only `cache` profile uses 2,048.

Set `BatchedTokens` in `config.local.psd1` and recreate the service to apply an override. Larger budgets require memory validation. `CacheBlockTokens` and `LmcacheChunkTokens` must be compatible: the chunk size must be a positive multiple of the block size, and the runtime validates each attention group's layout. Keep the supplied per-profile values unless testing a new layout. See [agent concurrency measurements](Benchmarks.md#agent-and-restore-qualification) for the benchmark reference profile.

## Lifecycle

```powershell
.\n1x.ps1 start
.\n1x.ps1 wait
.\n1x.ps1 status
.\n1x.ps1 stop
```

Use the same profile argument across commands, or set `DefaultProfile`. Only one project profile should run at a time. Commands refuse to modify containers without the project's ownership label.

Changing only `DefaultProfile` changes which profile commands select; it does not change an existing profile's runtime settings or require recreating that profile.

Existing containers retain their creation settings. After configuration changes:

```powershell
.\n1x.ps1 recreate
.\n1x.ps1 wait
```

This replaces the selected container and preserves named volumes. Also recreate after rebuilding an image to use the new image. `start -PrintOnly` previews the launch without requiring downloaded models or WSLC access. `restart` reuses a matching configuration.

## LAN access

Use `n1x.ps1 start -DenyFirewall` to start without adding a firewall allowance and remove any existing N1X allowance for this checkout. The switch also works with `restart` and `recreate`. Removing an existing rule requires UAC; when no rule exists, no firewall elevation is needed. This is a per-command choice: a subsequent plain `start` enables the allowance again. It does not change the container's listening address or override other firewall rules; use `LanAccess = $false` and recreate for localhost-only serving.

`start` and `restart` publish the API on all IPv4 interfaces and add a Windows Firewall rule for the configured TCP port (8000 by default), restricted to `LocalSubnet`. The rule applies to all Windows network profiles, including Public Wi-Fi. Other computers on that subnet can use `http://<Windows-LAN-IP>:8000/v1`, model `qwen`, after the API is ready. The API has no authentication; computers on the allowed subnet can submit requests.

`stop`, online `clean`, and `uninstall` remove this checkout's rule. Firewall changes request Windows UAC elevation separately; keep running the main commands from your normal terminal so WSLC uses the same session. A failed or cancelled firewall update is reported as an error, even if the container started successfully. Other applications' firewall rules are not changed. This does not configure router forwarding or guarantee access through organizational firewall policy or Wi-Fi client isolation.

Existing localhost-only containers need `n1x.ps1 recreate` once to apply the new binding. Set `LanAccess = $false` in `config.local.psd1` and recreate to keep serving only on localhost. Client registrations continue to use localhost on this computer. From another LAN computer, verify with `Invoke-RestMethod http://<Windows-LAN-IP>:8000/health`; after stop the connection should fail.

Find the serving computer's LAN address with `Get-NetIPConfiguration` and use the IPv4 address on its connected Ethernet or Wi-Fi adapter. Substitute your configured port if it differs from 8000. Only the model API is exposed; these commands do not publish LMCache's internal ports. Closing N1X's rule does not remove allowances created by other software.

## Agent clients

Successful `start` and `restart` register the local model for clients whose user configuration directories exist. `stop`, online `clean`, and `uninstall` remove only the registrations owned by this checkout. Existing defaults and unrelated providers remain unchanged; `-PrintOnly` does not modify client files.

| Client | User configuration | Select the local model |
| --- | --- | --- |
| OpenCode 2 | `~/.config/opencode/opencode.jsonc` when present, otherwise `opencode.json`; provider `n1x` | Reload/reopen OpenCode, then select `n1x/qwen` in `/models` |
| Codex 0.134+ | `~/.codex/n1x.config.toml` | `codex --profile n1x` |
| Pi | `~/.pi/agent/models.json`, provider `n1x` | Open `/model`, or `pi --provider n1x --model qwen` |

The entries follow the active port and context limit. OpenCode and Pi advertise image input and reasoning, with thinking enabled and an 8,192-token output cap (less for small contexts). Codex uses the Responses API and a compaction threshold at 85% of context. Configuration registration does not establish end-to-end client/tool compatibility; Codex specifically requires the server's `/v1/responses` support.

`XDG_CONFIG_HOME`, `CODEX_HOME`, and `PI_CODING_AGENT_DIR` override the corresponding user locations. Set `$env:N1X_CLIENT_CONFIG='off'` to disable automatic changes. OpenCode JSONC is patched with a managed provider block: comments, formatting, trailing commas, and unrelated settings are preserved. Stop removes that block. Invalid configuration, name collisions, or manually edited N1X entries are preserved with a warning. Ownership sidecars stay alongside the client configs so repository cleanup cannot lose them. Existing sessions may need a client reload after start/stop; the service must be ready before sending requests. Select `n1x/qwen` for the explicit reasoning and vision metadata; OpenCode's auto-discovered `vLLM/qwen` entry is separate.

Install and launch a client once to create its user configuration directory, then run `n1x.ps1 start` again to register it; an already-running matching container is reused. These are configuration entries, not executable patches or client installations. Configuration is updated only on this Windows user account; configure clients on other computers with the LAN endpoint separately.

OpenCode exposes an explicit `thinking` variant for `n1x/qwen`, with thinking also enabled in the base request. Desktop may still display "No reasoning" because of its [v2 model tooltip bug](https://github.com/anomalyco/opencode/issues/50257). The label does not establish whether the model is reasoning; check the response's reasoning field. This limitation affects the desktop display even when the CLI and service load the correct request settings.

The opt-out affects both registration and removal. To remove existing managed entries before opting out, run `n1x.ps1 stop` first. To re-enable automatic updates in the current terminal, run `Remove-Item Env:N1X_CLIENT_CONFIG`. Keep each `*.n1x-managed.json` sidecar so stop can identify its own entries safely.

## DFlash2

The default `cache-dflash` profile uses the DFlash2 drafter with three draft tokens, 262,144-token context, four sequence slots, and an 8 GiB FP8 KV pool. Sliding-attention KV stays BF16; the compressed indexer uses FP8. Matching 1,664-token cache blocks and LMCache chunks reduce Mamba page padding to 0.48%. Its LMCache namespace includes the speculative method, indexer precision, and cache geometry to separate incompatible entries. `cache-mtp` remains available as an alternative; see [qualification results](Benchmarks.md#dflash2-comparison).

At this context limit, vLLM reports approximately 520K tokens of capacity (1.99 maximum-length requests). This is a scheduler estimate, not a guarantee of two simultaneous 262K sessions. Capacity depends on context length because sliding-attention and recurrent-state overhead are included. Four sequence slots do not imply four maximum-length contexts fit together.

Both DFlash2 and MTP pass the synthetic multi-turn agent check with thinking enabled and fail it with thinking disabled; see [agent qualification](Benchmarks.md#agent-and-restore-qualification). DFlash2 at concurrency 4 has the highest measured correct-work throughput in that check. Validate your application's tasks; this narrow qualification does not establish general agent reliability.

```powershell
# Setup already prepares DFlash2. To switch an existing MTP service:
.\n1x.ps1 stop -Profile cache-mtp
.\n1x.ps1 start -Profile cache-dflash
.\n1x.ps1 wait -Profile cache-dflash -TimeoutSeconds 1800
.\n1x.ps1 test -Profile cache-dflash
```

The first start compiles additional FlashInfer kernels. Use `-Profile cache-dflash` for lifecycle commands when selecting it explicitly. Stop it before returning to `cache-mtp`.

## Storage

- Main weights: read-only mount from ModelRoot.
- Native PLE volume: verified copy created by `prepare-native-ple.ps1`.
- Runtime cache volume: compilation and library caches.
- LMCache volume: local SSD cache, separated by runtime/model and speculative method.
- `.state/`: ignored current host-memory snapshot, monitor identity, and local test output.

Named volumes survive stop and recreate. The [SSD cache budget](LMCache.md#ssd-budget) bounds stored KV files; model weights, images, and compilation caches are separate. Cache reuse across engine restarts is not guaranteed by this project.

## Cleanup and disk reclamation

```powershell
.\n1x.ps1 clean -PrintOnly
.\n1x.ps1 stop
.\n1x.ps1 clean
```

| Command | Removes | Preserves |
| --- | --- | --- |
| `clean` | Stopped project containers, obsolete project images, kernel/KV/test cache volumes, ignored build sources, environments, logs and raw test results | Models (including `.cache`), settings, current runtime/build/benchmark images, native PLE, tracked and ordinary untracked files |
| `uninstall` | Project containers (stopping them first), project images and volumes including native PLE, and the same ignored files | Models, settings, repository source, unrelated/shared resources |

`clean` keeps what is needed to start offline; it does not require large downloads afterward. The next start recreates empty caches and recompiles kernels, so it can be slower and previous warm KV entries are lost. Stop all project profiles first. `uninstall` requires setup before serving again and may need large downloads/builds. Preview either command with `-PrintOnly`.

Export raw results you want to keep before cleaning. Resource removal is scoped to project labels, legacy `n1x-*` containers using project images, configured cache volumes, and the `n1x-ai` image repositories. Resources referenced by unrelated containers are preserved. No global image, volume, or build-cache prune is performed. Repository cleanup refuses linked paths and preserves local configuration. Normal cleanup removes stale `.state` files and empty generated directory trees, including `.build` and `results`. Offline `clean -VhdPath` preserves `.state` so an active compaction log is not deleted.

The command then runs `fstrim -av` in the default WSLC session to release unused Linux blocks. Run from an interactive terminal if WSLC reports an invalid handle. TRIM does not guarantee that Windows immediately reclaims the backing VHDX's physical space.

For offline compaction, first stop every workload using the backing disk and terminate its WSLC session. Then use an **elevated PowerShell** with the actual disk path:

```powershell
.\n1x.ps1 clean -VhdPath 'D:\WSLC\actual-backing-disk.vhdx'
```

The path is explicit because WSLC storage can be shared with unrelated containers. This mode requires a detached VHDX and skips WSLC commands to avoid reattaching it. It uses `Optimize-VHD` when available, otherwise Windows DiskPart. DiskPart success detection expects English output; other locales may require manual verification. Compaction preserves data and cannot reclaim blocks still occupied by images or cache volumes. No global image or volume prune is performed.
