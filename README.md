# n1x-ai

Run Qwen3.8 Flash Next with vLLM on NVIDIA N1X, Windows ARM64, and WSLC. PowerShell commands handle pinned model downloads, container builds, native PLE storage, and an optional local LMCache service.

See [requirements and installation](wiki/Installation.md) before starting. The LMCache integration includes experimental compatibility patches for this platform.

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

See [Configuration](wiki/Configuration.md) for profiles, local settings, and applying changes.

## Documentation

- [Installation](wiki/Installation.md)
- [Configuration and profiles](wiki/Configuration.md)
- [LMCache and memory management](wiki/LMCache.md)
- [Benchmarks and results](wiki/Benchmarks.md)
- [Troubleshooting](wiki/Troubleshooting.md)
- [Development and validation](wiki/Development.md)
- [API guidance for agent harnesses](AGENTS.md)

## License

Project scripts and original changes use the [MIT license](LICENSE). [Third-party notices](NOTICE.md) describe upstream code and separate model licenses. Model weights are downloaded from their publishers and are not included.
