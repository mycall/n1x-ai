# n1x-ai

Run Qwen3.8 Flash Next with vLLM on NVIDIA N1X, Windows ARM64, and WSLC. PowerShell commands handle pinned model downloads, container builds, native PLE storage, and an optional local LMCache service.

This project targets a 128 GiB N1X system with an 88 GiB dedicated GPU partition. The LMCache integration includes experimental compatibility patches for this platform. See [requirements and installation](wiki/Installation.md) before starting.

## Quick start

Install Git, WSLC with GPU support, and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli), then run these commands from the repository in PowerShell:

```powershell
.\setup.ps1 -WithLMCache
.\n1x.ps1 start
.\n1x.ps1 wait
.\n1x.ps1 test
```

Setup downloads pinned model revisions into `$HOME\models`, builds the images, copies the PLE table into a native volume, and selects the `cache-mtp` profile. Allow substantial disk space and time for downloads and the initial build. To reuse downloaded models:

```powershell
.\setup.ps1 -WithLMCache -ModelRoot D:\Models -SkipDownload
```

The API is OpenAI compatible: **`http://127.0.0.1:8000/v1`**, model **`qwen`**.

```powershell
$body = @{
    model = 'qwen'
    messages = @(@{ role = 'user'; content = 'Reply with a greeting.' })
    max_tokens = 128
    chat_template_kwargs = @{ enable_thinking = $false }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8000/v1/chat/completions `
    -Method Post -ContentType application/json -Body $body
```

## Daily use

```powershell
.\n1x.ps1 status
.\n1x.ps1 logs
.\n1x.ps1 test -Suite features
.\n1x.ps1 stop
```

Edit ignored `config.local.psd1` for local settings; [an example](config.local.example.psd1) is included. After changing settings, run `.\n1x.ps1 recreate`, then `.\n1x.ps1 wait`. Recreating the container preserves named volumes.

| Profile | Purpose | Maximum context |
| --- | --- | --- |
| `baseline` | Simple vLLM service | 32,768 |
| `mtp` | Simple service with one MTP draft token | 32,768 |
| `cache` | LMCache, native PLE, FP8 KV | 262,144 |
| `cache-mtp` | LMCache with one MTP draft token | 262,144 |

Select a profile with `-Profile`, or set `DefaultProfile` locally. Stop the active profile before starting another. Context includes input and output; concurrent requests share the KV pool.

## Documentation

- [Installation](wiki/Installation.md)
- [Configuration and profiles](wiki/Configuration.md)
- [LMCache and memory management](wiki/LMCache.md)
- [Troubleshooting](wiki/Troubleshooting.md)
- [Development and validation](wiki/Development.md)
- [API guidance for agent harnesses](AGENTS.md)

The [wiki source](wiki/Home.md) is included here for distribution and can be published to a GitHub wiki separately.

## License

Project scripts and original changes use the [MIT license](LICENSE). [Third-party notices](NOTICE.md) describe upstream code and separate model licenses. Model weights are downloaded from their publishers and are not included.
