param([string]$Volume = 'n1x-ple-native')
$ErrorActionPreference='Stop'
if ($Volume -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]+$') { throw 'Invalid volume name' }
$running=@(& wslc list --filter 'label=n1x-ai.managed=true' --format json)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect containers' }
if (@($running | Where-Object { $_.Trim() }).Count) { throw 'Stop managed containers before copying the table' }
$config=Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$table=Join-Path $config.ModelRoot 'ple-table-fp8'
$run=@('run','--rm','--name','n1x-prepare-ple','--label','n1x-ai.managed=true','--entrypoint','python',
    '--volume',"${table}:/source-table:ro",'--volume',"${Volume}:/native-table",'--volume',"${PSScriptRoot}:/workspace:ro",
    $config.Image,'/workspace/prepare-native-ple.py')
& wslc @run
if ($LASTEXITCODE -ne 0) { throw 'Native PLE preparation failed' }
$raw=& wslc run --rm --entrypoint cat --volume "${Volume}:/native-table:ro" $config.Image /native-table/n1x-copy-manifest.json
if ($LASTEXITCODE -ne 0) { throw 'Cannot retrieve copy manifest' }
$raw | Set-Content "$PSScriptRoot/results/native-ple-manifest.json" -Encoding UTF8
