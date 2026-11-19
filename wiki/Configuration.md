# Configuration

Use `config.local.psd1` in the repository root for machine-specific settings. Start from `config.local.example.psd1`. The launcher reads base settings, the selected profile, and then local settings. Command-line `-ModelRoot` and `-Port` take precedence for that invocation.

```powershell
@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'qwen38fn-best'
    Port = 8000
}
```

## Profiles

Run `.\n1x.ps1 list profiles` to see the configured default (marked `*`) and effective settings after local overrides. [Serving profiles](Profile-review.md) compares the deployment choices.

| Profile | Context (input + output) | Drafting | GPU KV pool | LMCache |
| --- | ---: | --- | --- | --- |
| `qwen38fn-best` | 262,144 | DFlash2 K3 | 15 GiB | On |
| `qwen38fn-w4-kv19`, `qwen38fn-w4-kv19-4k` | 262,144 | DFlash2 K3 | 19 GiB | On |
| `qwen38fn-w4-kv20-4k-k5`, `qwen38fn-w4-kv20-8k-k5` | 262,144 | DFlash2 K5 | 20 GiB | On |
| `qwen38fn-az-dflash`, `qwen38fn-az-kv19` | 262,144 | DFlash2 K3 | 15 / 19 GiB | On |
| `qwen38fn-lmcache-4k` (88 GiB partition) | 262,144 | DFlash2 K3 | 11 GiB | On |
| `qwen38fn-baseline`, `qwen38fn-mtp` | 32,768 | Off / MTP K1 | 4 GiB | Off |
| `qwen38fn-cache`, `qwen38fn-cache-mtp`, `qwen38fn-cache-dflash` | 262,144 | Off / MTP K1 / DFlash2 K3 | 8 GiB | On |
| `qwen38fn-myllmbox` (native Windows) | 409,600 | Dynamic MTP K3–7 | 12 GB | Off |

K is the number of draft tokens. Concurrent clients share the GPU KV pool. When their histories exceed resident capacity, requests queue even if the profile has free sequence slots. The separate `qwen38-cache-tensorfold-dflash` profile is a [feasibility check](TensorFold-trial.md).

## Lifecycle

| Action | Purpose |
| --- | --- |
| `start` | Launch and wait for API readiness; replace stale managed containers while preserving named volumes |
| `start -NoWait` | Return after launch without waiting for API readiness |
| `wait` | Wait for an existing service with matching settings; does not start or replace it |
| `status` / `logs` / `doctor` | Inspect readiness, logs, and installation diagnostics |
| `test` | Run API smoke checks; [additional suites](Development.md#service-validation) are explicit |
| `stop` | Stop serving and remove managed client/firewall registrations |
| `restart` | Restart using a matching existing configuration |
| `recreate` | Replace the selected container to apply runtime changes; preserve named volumes |
| `start -PrintOnly` | Preview launch arguments without model files or WSLC access |

Run one project profile at a time. To switch, stop the running profile by name, then start the desired one. Use that name on later commands or set `DefaultProfile` to select it automatically.

```powershell
.\n1x.ps1 stop -Profile qwen38fn-best
.\n1x.ps1 start -Profile qwen38fn-w4-kv20-4k-k5
```

After a settings or recipe change, `start` replaces a stale managed container and reuses a matching one. It waits up to 3,600 seconds after launch. Use `-TimeoutSeconds 7200` for a longer cold start, or `-NoWait` followed by `wait` to check readiness separately. A timeout leaves the container available for inspection. Changing only `DefaultProfile` changes future command selection.

Use `recreate` to force replacement. Both `recreate` and `restart` return after launch, so run `wait` before sending work. The launcher checks project ownership before modifying a container. Image changes also require a matching tag and immutable ID. [Candidate image selection](MyLLMBox.md#select-a-candidate)

## LAN access

Best defaults to localhost. Set `LanAccess = $true` in `config.local.psd1` and recreate to publish on all IPv4 interfaces. Startup adds a Windows Firewall rule for the configured port, restricted to `LocalSubnet` across all network profiles, including Public Wi-Fi. The API has no authentication.

Use `Get-NetIPConfiguration` to find the host's LAN IPv4 address. From another computer, check `http://<Windows-LAN-IP>:8000/health`, then use the `/v1` API. Substitute the configured port. Router policy and Wi-Fi isolation can still block access; LMCache's internal ports are not published.

`start -DenyFirewall` removes this checkout's allowance without changing the listening address; it also works with `restart` and `recreate`. A later plain start follows `LanAccess` again. For persistent localhost-only serving, set `LanAccess = $false` and recreate.

`stop`, online `clean`, and `uninstall` remove the managed rule. Firewall changes request UAC separately; keep the main command in your normal terminal so WSLC uses the same session. Failed or cancelled elevation is reported even if serving started. Other applications' firewall rules remain unchanged. Local client registrations always use localhost.

## Agent clients

### REST reasoning control

Check `http://127.0.0.1:8000/health` before sending work. Use `http://127.0.0.1:8000/v1` as the API base and `qwen/qwen38fn-best` as the model ID, including when you launch an alternate profile.

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

Start the client once to create its configuration directory, then run `n1x.ps1 start` and reload the client. Registrations follow the active port and context. On another computer, configure the [LAN endpoint](#lan-access) manually.

- **OpenCode** selects medium reasoning for the managed model. Both the `medium` and `thinking` variants send `enable_thinking=true` and `reasoning_effort=medium`. Select the `n1x` provider for explicit reasoning and vision metadata. Some desktop versions display “No reasoning” even when the response has a reasoning field. [OpenCode display issue](https://github.com/anomalyco/opencode/issues/50257)
- **Pi and OpenCode** advertise image input, reasoning, and the configured output allowance, bounded by context.
- **Codex** uses the Responses API and sets compaction at 85% of context. Check the server’s `/v1/responses` support for your workflow.

The launcher honors `XDG_CONFIG_HOME`, `CODEX_HOME`, and `PI_CODING_AGENT_DIR`. It preserves existing client defaults, JSONC comments, and unrelated settings. It warns on invalid configuration, name collisions, or manually edited entries. Keep the `*.n1x-managed.json` sidecars so it can identify its own entries.

To opt out, first run `n1x.ps1 stop` if you want to remove existing registrations, then set `$env:N1X_CLIENT_CONFIG='off'`. This disables both registration and removal. Run `Remove-Item Env:N1X_CLIENT_CONFIG` to re-enable them in the current terminal.

## Memory headroom

`WindowsMinimumGiB` defaults to 4. Startup and monitoring check both free physical RAM and Windows commit headroom, the remaining Windows allocation allowance. The GPU partition and `KvCacheBytes` are separate settings. See [memory monitoring and partition checks](LMCache.md#memory-budget) for runtime behavior; the scripts do not change the hardware partition.

## Output allowance

`MaxOutputTokens` defaults to **8,192 tokens for reasoning and final content combined**. Both runtimes pass it to vLLM as `max_new_tokens`. Requests can ask for less. The rendered input, including tools and images, plus the requested output must fit within `Context`.

To change the cap, set `MaxOutputTokens` to a positive integer smaller than `Context` in `config.local.psd1` and apply it with `start`. OpenCode and Pi pick up the allowance on registration. Benchmarks with an explicit output limit keep their own budgets. [API guidance](../AGENTS.md) · [vLLM generation configuration](https://docs.vllm.ai/en/latest/cli/serve/#--generation-config)

## Scheduling

`BatchedTokens` is the scheduler's per-step token budget, not the number of sessions. The reference DFlash2 and MTP cache profiles use 4,096; their cache blocks are 1,664 and 2,048 tokens respectively. A budget of one block can serialize admission. The target-only `qwen38fn-cache` profile uses 2,048. `qwen38fn-best` uses an 8,192-token batch and 4,096-token block with its separately qualified MyLLMBox runtime.

Set `BatchedTokens` in `config.local.psd1` and recreate the service to apply an override. Larger budgets require memory validation. `CacheBlockTokens` and `LmcacheChunkTokens` must be compatible: the chunk size must be a positive multiple of the block size, and the runtime validates each attention group's layout. Keep the supplied per-profile values unless testing a new layout. See [agent concurrency measurements](Benchmarks.md#agent-and-restore-qualification) for the benchmark reference profile.

## DFlash2

DFlash2 uses a separate drafter; MTP uses the target's indexed extra tensors. See [Model assets](Model-assets.md) for their exact dependencies. Best and the reference DFlash2 profile use three draft tokens, but differ in indexer precision, cache geometry, and runtime. Keep those per-profile settings together. The first launch may compile additional FlashInfer kernels. See [historical DFlash2/MTP results](Reference-benchmarks.md#dflash2-comparison) before drawing performance conclusions.

### Experimental draft depth

For a MyLLMBox Linux DFlash2 profile, set `DFlashTokens` in `config.local.psd1` and recreate to test another depth:

```powershell
DFlashTokens = 5
```

The setting accepts integers 1-7; the installed DFlash2 checkpoint's block must also accommodate the draft tokens plus one bonus token. The default profile uses K3. The W4/KV20 profiles specify K5. The launcher sets the effective speculative configuration on the command line and derives graph coverage from `(DFlashTokens + 1) * MaxSequences`. Editing only the YAML's `num_speculative_tokens` does not override this setting. Other backends ignore this MyLLMBox option and retain their existing recipes. `list profiles` shows the effective DFlash2 depth for each profile.

Depths 5-7 also require a runtime with the QSA ring fix. Earlier images compute a 12-slot ring that cannot divide the supplied 4,096-token block. New MyLLMBox builds apply a source-guarded patch that rounds the ring to 16 slots while retaining the existing ring sizes at depths 1-4. Setup and new large-depth launches check the image's `n1x-ai.qsa-ring=power-of-two-v1` marker before loading weights. Follow the [candidate build and selection procedure](MyLLMBox.md#select-a-candidate) when using a rebuilt image.

Built-in MyLLMBox cache namespaces identify the target weights, model compute precision, SSM state precision and PLE source. For W4 they also identify the BF16 indexer. At launch, `{settings}` expands to the target KV dtype and pool size, sequence slots, prefill batch tokens, cache block tokens, LMCache chunk tokens and DFlash2 depth. Best uses FP8 target KV with the recipe’s sliding-window exception, FP32 SSM state and a separate FP8 PLE table. Explicit trial namespaces retain their depth suffix for non-K3 runs. The v2 names start with an empty cache directory. Historical entries remain under their old names until normal budget eviction. Named volumes and prepared PLE are reused; no additional model download is needed. Changing depth changes recurrent-state/cache geometry and can require more memory or fail startup. Validate tools, actual context capacity, and restored answers before selecting a candidate. Remove the local override and recreate to restore the selected profile’s configured depth.

For measured effects, see [K1, K3, K5, and K7 on 88 GiB](DFlash-depth-trial.md) and [K5 batch sizes on 96 GiB](FP4-Local-AZ-trial.md#three-run-kv20k5-averages). Returning to the original runtime also requires removing candidate `Image` and `ImageId` overrides.

## Storage

- Main weights: read-only mount from ModelRoot.
- Native PLE volume: verified copy created by `prepare-native-ple.ps1`.
- Runtime cache volume: compilation and library caches; MyLLMBox also stores its prepared PLE map here.
- LMCache volume: local SSD cache, separated by runtime/model and speculative method.
- `.state/`: ignored current host-memory snapshot, monitor identity, and local test output.

Named volumes survive stop and recreate. The [SSD cache budget](LMCache.md#ssd-budget) bounds stored KV files; model weights, images, and compilation caches are separate. Cache reuse across engine restarts is not guaranteed by this project.

## Cleanup and disk reclamation

Export any raw benchmark results you want to keep before cleaning. Preview the cleanup in your normal PowerShell, then stop serving and run it. [Model and volume inventory](Model-assets.md) · [Benchmark evidence](Benchmarks.md#retained-evidence)

```powershell
.\n1x.ps1 clean -PrintOnly
.\n1x.ps1 stop
.\n1x.ps1 clean
```

| Command | Removes | Preserves |
| --- | --- | --- |
| `clean` | Stopped project containers, obsolete project images, disposable kernel/KV/test cache volumes, ignored build sources, environments, logs and raw test results | Models (including `.cache`), settings, current runtime/build/benchmark images, native PLE, MyLLMBox prepared PLE and configured LMCache volumes, tracked and ordinary untracked files |
| `uninstall` | Project containers (stopping them first), project images and volumes including native PLE, and the same ignored files | Models, settings, repository source, unrelated/shared resources |

Cleanup uses project labels, legacy `n1x-*` container names with project images, configured volumes, and the `n1x-ai` image repositories to identify resources. It skips resources referenced by unrelated containers and refuses linked repository paths. Online cleanup also removes stale `.state` files and empty generated directories.

The default profile’s LMCache volume survives normal cleanup. To reset that cache, stop the service before retiring its volume. Setup can recreate it empty. Other trial volumes each have an independent budget. Inspect their consumers before removing them.

### Compact the WSLC disk

Online cleanup runs `fstrim -av` inside WSLC. Use an interactive terminal if it reports an invalid handle. The Linux filesystem can show free blocks while the Windows backing file still occupies the same space.

For offline compaction, stop every workload using the backing disk and terminate its WSLC session. The VHDX must be detached. In an **elevated PowerShell**, supply the actual backing disk path:

```powershell
.\n1x.ps1 clean -VhdPath 'D:\WSLC\actual-backing-disk.vhdx'
```

This mode also cleans ignored repository files, but preserves `.state` for the compaction log. It skips WSLC commands to keep the disk detached, runs `Optimize-VHD` or Windows DiskPart, and reports the file size before and after. DiskPart success detection expects English output. On other locales, verify the result manually. Blocks still occupied by images or volumes remain allocated.
