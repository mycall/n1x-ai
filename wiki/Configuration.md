# Configuration

Settings merge in this order: `config.psd1`, the selected profile in `profiles/`, ignored `config.local.psd1`, then `-ModelRoot` and `-Port` command arguments. Local values therefore override profile settings. Copy `config.local.example.psd1` when configuring manually.

```powershell
@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'qwen38fn-best'
    Port = 8000
}
```

## Profiles

Run `.\n1x.ps1 list profiles` to list available profiles, mark the configured default with `*`, and show each profile's effective runtime, context, speculation and LMCache settings. The list includes the built-in baseline and discovers profile files automatically; local overrides are reflected in the displayed settings. Listing does not start a server.

Profile names use the model family prefix `qwen38fn-`. The table describes checked-in defaults; local overrides can change them.

| Profile | Context | Speculation | LMCache | KV allocation |
| --- | --- | --- | --- | --- |
| qwen38fn-best (default, MyLLMBox Linux; batch8K, 96 GiB partition) | 262,144 | Three DFlash2 draft tokens | On | 15 GiB FP8, BF16 draft KV |
| qwen38fn-lmcache-4k (batch4K alternate) | 262,144 | Three DFlash2 draft tokens | On | 11 GiB FP8, BF16 draft KV |
| qwen38fn-baseline | 32,768 | Off | Off | 4 GiB |
| qwen38fn-mtp | 32,768 | One draft token, Triton | Off | 4 GiB |
| qwen38fn-cache | 262,144 | Off | On | 8 GiB FP8 |
| qwen38fn-cache-mtp | 262,144 | One draft token, Triton | On | 8 GiB FP8 |
| qwen38fn-cache-dflash | 262,144 | Three DFlash2 draft tokens | On | 8 GiB FP8 |
| qwen38fn-myllmbox (native Windows, test) | 409,600 | Dynamic MTP depth 3–7, HEAD2 | Off | 12 GB FP8, BF16 draft KV |

Best and the 4K alternate use standard FP32 SSM with RecoverSSM off, a BF16 indexer, and eight server slots. See [MyLLMBox](MyLLMBox.md) for runtime prerequisites, [LMCache](LMCache.md#ssd-budget) for RAM/SSD budgets, and [Component review](Profile-review.md) for measured tradeoffs.

The [native Windows reference](Native-vLLM.md) has separate weights and dependencies. Container setup and cleanup instructions do not manage that external installation.

Context includes input and output. Concurrent clients share the KV pool and queue when resident capacity is exhausted; eight slots do not guarantee eight full-window histories fit. Output length, simultaneous prefill, vision, and host applications affect capacity.

## Memory headroom

`WindowsMinimumGiB` defaults to 4. Startup and monitoring check both free physical RAM and Windows commit headroom, the remaining Windows allocation allowance. The GPU partition and `KvCacheBytes` are separate settings. See [memory monitoring and partition checks](LMCache.md#memory-budget) for runtime behavior; the scripts do not change the hardware partition.

## Output allowance

`MaxOutputTokens = 8192` is the shared default output allowance and server cap for every profile. It counts reasoning and final-answer tokens together. Override it in `config.local.psd1` when needed:

```powershell
MaxOutputTokens = 8192
```

Both native and WSLC launches pass this through vLLM's `--override-generation-config` as `max_new_tokens`, preserving the model's other generation settings. Requests that omit an output limit receive up to this allowance, subject to remaining context. An explicit smaller request limit still wins; a larger one is capped. Raise `MaxOutputTokens` and recreate the service to allow more than 8,192. This server-wide cap behavior is documented in the [vLLM generation configuration](https://docs.vllm.ai/en/latest/cli/serve/#--generation-config).

The setting must be a positive integer smaller than `Context`. Reserve room for output when constructing prompts; it does not increase the context window or force the model to generate 8,192 tokens. OpenCode/Pi registrations use the configured allowance on the next normal start, subject to the existing client-registration opt-out. Clients that explicitly send 1,024 still use 1,024. Fixed benchmark budgets are unchanged.

Apply changes with `recreate`. Fixed benchmark budgets remain independent; the [coverage table](Test-plan.md) records the outstanding matched output-budget experiment.

## Scheduling

`BatchedTokens` is the scheduler's per-step token budget, not the number of sessions. The reference DFlash2 and MTP cache profiles use 4,096; their cache blocks are 1,664 and 2,048 tokens respectively. A budget of one block can serialize admission. The target-only `qwen38fn-cache` profile uses 2,048. `qwen38fn-best` uses an 8,192-token batch and 4,096-token block with its separately qualified MyLLMBox runtime.

Set `BatchedTokens` in `config.local.psd1` and recreate the service to apply an override. Larger budgets require memory validation. `CacheBlockTokens` and `LmcacheChunkTokens` must be compatible: the chunk size must be a positive multiple of the block size, and the runtime validates each attention group's layout. Keep the supplied per-profile values unless testing a new layout. See [agent concurrency measurements](Benchmarks.md#agent-and-restore-qualification) for the benchmark reference profile.

## Lifecycle

| Action | Purpose |
| --- | --- |
| `start` / `wait` | Launch the selected profile / wait for API readiness |
| `status` / `logs` / `doctor` | Inspect readiness, logs, and installation diagnostics |
| `test` | Run API smoke checks; [additional suites](Development.md#service-validation) are explicit |
| `stop` | Stop serving and remove managed client/firewall registrations |
| `restart` | Restart using a matching existing configuration |
| `recreate` | Replace the selected container to apply runtime changes; preserve named volumes |
| `start -PrintOnly` | Preview launch arguments without model files or WSLC access |

Use the same profile argument across commands, or set `DefaultProfile`. Only one project profile should run at a time. Commands refuse to modify containers without the project's ownership label.

Changing only `DefaultProfile` changes which profile commands select; it does not change an existing profile's runtime settings or require recreating that profile.

Existing containers retain their creation settings. After configuration changes:

```powershell
.\n1x.ps1 recreate
.\n1x.ps1 wait
```

Also recreate after selecting a rebuilt image or changing the HTTP model name. MyLLMBox image selection requires a matching tag and immutable ID; see [candidate selection](MyLLMBox.md#select-a-candidate). Configuration and recipe fingerprints prevent silently reusing stale settings.

## LAN access

Best defaults to localhost. Set `LanAccess = $true` in `config.local.psd1` and recreate to publish on all IPv4 interfaces. Startup adds a Windows Firewall rule for the configured port, restricted to `LocalSubnet` across all network profiles, including Public Wi-Fi. The API has no authentication.

Use `Get-NetIPConfiguration` to find the host's LAN IPv4 address. From another computer, check `http://<Windows-LAN-IP>:8000/health`, then use the `/v1` API. Substitute the configured port. Router policy and Wi-Fi isolation can still block access; LMCache's internal ports are not published.

`start -DenyFirewall` removes this checkout's allowance without changing the listening address; it also works with `restart` and `recreate`. A later plain start follows `LanAccess` again. For persistent localhost-only serving, set `LanAccess = $false` and recreate.

`stop`, online `clean`, and `uninstall` remove the managed rule. Firewall changes request UAC separately; keep the main command in your normal terminal so WSLC uses the same session. Failed or cancelled elevation is reported even if serving started. Other applications' firewall rules remain unchanged. Local client registrations always use localhost.

## Agent clients

### REST reasoning control

The API base URL is `http://127.0.0.1:8000/v1` by default. Its client-facing model ID is `qwen/qwen38fn-best`. Reference profiles use the same alias when explicitly launched. Containers created with the former `qwen` alias require `recreate`; reload clients after registration refreshes.

For `POST /v1/chat/completions`, choose reasoning effort per request:

```json
{
  "model": "qwen/qwen38fn-best",
  "messages": [{"role": "user", "content": "Explain this code."}],
  "max_tokens": 8192,
  "chat_template_kwargs": {
    "enable_thinking": true,
    "reasoning_effort": "medium"
  }
}
```

The pinned template supports `low`, `medium`, and `xhigh`; omitting effort uses its `xhigh` default. Set `enable_thinking` to `false` to disable thinking. The output budget includes reasoning and the final answer. OpenCode's medium default is a client setting, not a server-wide override. The same request works through the LAN API URL.

### Client registration

Successful `start` and `restart` register the local model for clients whose user configuration directories exist. `stop`, online `clean`, and `uninstall` remove only the registrations owned by this checkout. Existing defaults and unrelated providers remain unchanged; `-PrintOnly` does not modify client files.

| Client | User configuration | Select the local model |
| --- | --- | --- |
| OpenCode 2 | `~/.config/opencode/opencode.jsonc` when present, otherwise `opencode.json`; provider `n1x` | Reload/reopen OpenCode, then select `n1x/qwen/qwen38fn-best` in `/models` |
| Codex 0.134+ | `~/.codex/n1x.config.toml` | `codex --profile n1x` |
| Pi | `~/.pi/agent/models.json`, provider `n1x` | Open `/model`, or `pi --provider n1x --model qwen/qwen38fn-best` |

The entries follow the active port and context limit. OpenCode and Pi advertise image input and reasoning, with thinking enabled and an 8,192-token output cap (less for small contexts). Codex uses the Responses API and a compaction threshold at 85% of context. Configuration registration does not establish end-to-end client/tool compatibility; Codex specifically requires the server's `/v1/responses` support.

`XDG_CONFIG_HOME`, `CODEX_HOME`, and `PI_CODING_AGENT_DIR` override the corresponding user locations. Set `$env:N1X_CLIENT_CONFIG='off'` to disable automatic changes. OpenCode JSONC is patched with a managed provider block: comments, formatting, trailing commas, and unrelated settings are preserved. Stop removes that block. Invalid configuration, name collisions, or manually edited N1X entries are preserved with a warning. Ownership sidecars stay alongside the client configs so repository cleanup cannot lose them. Existing sessions may need a client reload after start/stop; the service must be ready before sending requests. Select `n1x/qwen/qwen38fn-best` for the explicit reasoning and vision metadata; OpenCode's auto-discovered `vLLM/qwen/qwen38fn-best` entry is separate.

Install and launch a client once to create its user configuration directory, then run `n1x.ps1 start` again to register it; an already-running matching container is reused. These are configuration entries, not executable patches or client installations. Configuration is updated only on this Windows user account; configure clients on other computers with the LAN endpoint separately.

OpenCode defaults to medium reasoning for `n1x/qwen/qwen38fn-best`. Its `medium` variant and the backward-compatible `thinking` variant both send `chat_template_kwargs = {enable_thinking: true, reasoning_effort: "medium"}`. Desktop may still display "No reasoning" because of its [v2 model tooltip bug](https://github.com/anomalyco/opencode/issues/50257). The label does not establish whether the model is reasoning; check the response's reasoning field. This limitation affects the desktop display even when the CLI and service load the correct request settings.

The opt-out affects both registration and removal. To remove existing managed entries before opting out, run `n1x.ps1 stop` first. To re-enable automatic updates in the current terminal, run `Remove-Item Env:N1X_CLIENT_CONFIG`. Keep each `*.n1x-managed.json` sidecar so stop can identify its own entries safely.

## DFlash2

DFlash2 uses a separate drafter; MTP uses the target's indexed extra tensors. See [Model assets](Model-assets.md) for their exact dependencies. Best and the reference DFlash2 profile use three draft tokens, but differ in indexer precision, cache geometry, and runtime. Keep those per-profile settings together. The first launch may compile additional FlashInfer kernels. See [historical DFlash2/MTP results](Benchmarks.md#dflash2-comparison) before drawing performance conclusions.

### Experimental draft depth

For the MyLLMBox profiles (`qwen38fn-best` and `qwen38fn-lmcache-4k`), set `DFlashTokens` in `config.local.psd1` and recreate to test another depth:

```powershell
DFlashTokens = 5
```

The setting accepts integers 1-7; the installed DFlash2 checkpoint's block must also accommodate the draft tokens plus one bonus token. K3 remains the qualified default. The launcher sets the effective speculative configuration on the command line and derives graph coverage from `(DFlashTokens + 1) * MaxSequences`. Editing only the YAML's `num_speculative_tokens` does not override this setting. Other backends ignore this MyLLMBox option and retain their existing recipes. `list profiles` shows the effective DFlash2 depth for each profile.

Depths 5-7 also require a runtime with the QSA ring fix. Earlier images compute a 12-slot ring that cannot divide the supplied 4,096-token block. New MyLLMBox builds apply a source-guarded patch that rounds the ring to 16 slots while retaining the existing ring sizes at depths 1-4. Setup and new large-depth launches check the image's `n1x-ai.qsa-ring=power-of-two-v1` marker before loading weights. Follow the [candidate build and selection procedure](MyLLMBox.md#select-a-candidate) when using a rebuilt image.

K3 retains its existing LMCache namespace and configuration identity. Other depths append `-dflash-kN` to the configured namespace to prevent cross-depth restores. Named volumes and prepared PLE are reused; no additional model download is needed. Changing depth changes recurrent-state/cache geometry and can require more memory or fail startup. Validate tools, actual context capacity, and restored answers before selecting a candidate. Remove the override or set it to `3`, then recreate, to return to K3.

The [DFlash2 depth trial](DFlash-depth-trial.md) records the tested candidate image, bounded correctness and speed results, and remaining qualification gaps. Returning to the original runtime also requires removing candidate `Image` and `ImageId` overrides.

## Storage

- Main weights: read-only mount from ModelRoot.
- Native PLE volume: verified copy created by `prepare-native-ple.ps1`.
- Runtime cache volume: compilation and library caches; MyLLMBox also stores its prepared PLE map here.
- LMCache volume: local SSD cache, separated by runtime/model and speculative method.
- `.state/`: ignored current host-memory snapshot, monitor identity, and local test output.

Named volumes survive stop and recreate. The [SSD cache budget](LMCache.md#ssd-budget) bounds stored KV files; model weights, images, and compilation caches are separate. Cache reuse across engine restarts is not guaranteed by this project.

## Cleanup and disk reclamation

Use the [model-file inventory](Model-assets.md) to distinguish required weights and prepared PLE from regenerable KV data. Review consumers before removing assets manually, and retain [benchmark evidence](Benchmarks.md#retained-evidence) before cleaning local results. Logical file sizes do not establish physical space recoverable from shared layers or virtual disks.

```powershell
.\n1x.ps1 clean -PrintOnly
.\n1x.ps1 stop
.\n1x.ps1 clean
```

| Command | Removes | Preserves |
| --- | --- | --- |
| `clean` | Stopped project containers, obsolete project images, disposable kernel/KV/test cache volumes, ignored build sources, environments, logs and raw test results | Models (including `.cache`), settings, current runtime/build/benchmark images, native PLE, MyLLMBox prepared PLE and configured LMCache volumes, tracked and ordinary untracked files |
| `uninstall` | Project containers (stopping them first), project images and volumes including native PLE, and the same ignored files | Models, settings, repository source, unrelated/shared resources |

`clean` preserves the selected prepared installation, including best's LMCache volume; it does not discard that volume's warm entries. Removed disposable caches regenerate on later use. It cannot restore prerequisites already removed separately. `uninstall` removes runtime assets and requires preparation before serving again. Preview either command with `-PrintOnly`.

Best's LMCache volume can be retired separately while the service is stopped. Run `n1x.ps1 setup -Profile qwen38fn-best` to create it empty before the next start. Model weights and prepared PLE are still required. Retire obsolete trial volumes explicitly: their independent budgets can accumulate, and normal cleanup is not a global prune.

Export raw results you want to keep before cleaning. Resource removal is scoped to project labels, legacy `n1x-*` containers using project images, configured cache volumes, and the `n1x-ai` image repositories. Resources referenced by unrelated containers are preserved. No global image, volume, or build-cache prune is performed. Repository cleanup refuses linked paths and preserves local configuration. Normal cleanup removes stale `.state` files and empty generated directory trees, including `.build` and `results`. Offline `clean -VhdPath` preserves `.state` so an active compaction log is not deleted.

The command then runs `fstrim -av` in the default WSLC session to release unused Linux blocks. Run from an interactive terminal if WSLC reports an invalid handle. TRIM does not guarantee that Windows immediately reclaims the backing VHDX's physical space.

For offline compaction, first stop every workload using the backing disk and terminate its WSLC session. Then use an **elevated PowerShell** with the actual disk path:

```powershell
.\n1x.ps1 clean -VhdPath 'D:\WSLC\actual-backing-disk.vhdx'
```

The path is explicit because WSLC storage can be shared with unrelated containers. This mode requires a detached VHDX and skips WSLC commands to avoid reattaching it. It uses `Optimize-VHD` when available, otherwise Windows DiskPart. DiskPart success detection expects English output; other locales may require manual verification. Compaction preserves data and cannot reclaim blocks still occupied by images or cache volumes. No global image or volume prune is performed.
