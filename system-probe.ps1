param([string]$RunName = "system-probe-$(Get-Date -Format yyyyMMdd-HHmmss)")
$ErrorActionPreference='Stop'
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'RunName must use letters, numbers, underscore or hyphen' }
$running=@(& wslc list --filter 'label=n1x-ai.managed=true' --format json)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect containers' }
if (@($running | Where-Object { $_.Trim() }).Count) { throw 'Stop managed inference containers before system probes' }
$config=Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$table=Join-Path $config.ModelRoot 'ple-table-fp8'
$fixture=Get-ChildItem $table -Filter '*.safetensors' | Sort-Object Name | Select-Object -First 1
if (-not $fixture) { throw 'PLE table fixture missing' }
$dir=Join-Path "$PSScriptRoot/results" $RunName
if (Test-Path $dir) { throw 'Run directory already exists' }
New-Item -ItemType Directory $dir | Out-Null
$scratch="/cache/n1x-system-probe/$RunName"
$argsList=@('run','--rm','--name',$RunName,'--label','n1x-ai.managed=true','--entrypoint','python','--volume',"${PSScriptRoot}:/workspace:ro",'--volume',"${table}:/table:ro",'--volume',"$($config.CacheVolume):/cache",$config.Image,'/workspace/system-probe.py','--source',"/table/$($fixture.Name)",'--scratch',$scratch)
& wslc @argsList | Tee-Object -FilePath "$dir/probe.log"
if ($LASTEXITCODE -ne 0) { throw 'System probe failed' }
$raw=& wslc run --rm --entrypoint cat --volume "$($config.CacheVolume):/cache:ro" $config.Image "$scratch/results.json"
if ($LASTEXITCODE -ne 0) { throw 'Cannot retrieve probe results' }
[IO.File]::WriteAllText((Join-Path $dir 'results.json'),($raw -join "`n"),[Text.UTF8Encoding]::new($false))
Write-Host "Saved $dir/results.json"
