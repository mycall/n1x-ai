function Test-N1xModelDownload([string]$Directory, [string]$Revision, [string]$Kind){
    try {
        $required=switch($Kind){
            'main' {
                'config.json'; 'model.safetensors.index.json'; 'tokenizer.json'; 'tokenizer_config.json'
                'chat_template.jinja'; 'preprocessor_config.json'; 'processor_config.json'; 'quantization_config.json'
                $index=Get-Content -LiteralPath (Join-Path $Directory 'model.safetensors.index.json') -Raw -ErrorAction Stop | ConvertFrom-Json
                $index.weight_map.PSObject.Properties.Value | Sort-Object -Unique
            }
            'ple' {5..37 | ForEach-Object {'model-{0:00000}-of-00131.safetensors' -f $_}}
            'drafter' {'config.json'; 'model.safetensors'}
            default {throw 'Unknown model kind'}
        }
        foreach($relative in $required){
            $path=[IO.Path]::GetFullPath((Join-Path $Directory $relative))
            $prefix=[IO.Path]::GetFullPath($Directory).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
            if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){return $false}
            $file=Get-Item -LiteralPath $path -ErrorAction Stop
            $metadata=Get-Content -LiteralPath (Join-Path $Directory ".cache/huggingface/download/$relative.metadata") -ErrorAction Stop
            if($file.Length -le 0 -or $metadata.Count -lt 3 -or $metadata[0] -ne $Revision){return $false}
            $downloadTime=[double]::Parse($metadata[2],[Globalization.CultureInfo]::InvariantCulture)
            if(($file.LastWriteTimeUtc-[datetime]'1970-01-01').TotalSeconds -gt $downloadTime){return $false}
        }
        return $true
    } catch {return $false}
}

function Get-N1xModelDownload([string]$Repository,[string]$Revision,[string]$Directory,[string]$Kind){
    if(Test-N1xModelDownload $Directory $Revision $Kind){Write-Host "Reusing pinned $Kind files: $Directory"; return}
    if(-not(Get-Command hf -ErrorAction SilentlyContinue)){throw 'Install Hugging Face CLI (hf) to fetch or verify missing model files; see wiki/Installation.md'}
    . "$PSScriptRoot/proxy.ps1"
    Update-N1xProxyEnvironment
    & hf download $Repository --revision $Revision --local-dir $Directory
    if($LASTEXITCODE -ne 0){throw 'Model download failed; rerun setup to resume'}
}
