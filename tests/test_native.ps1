$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
. "$root/scripts/native.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-native-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/profiles" | Out-Null
try {
    Copy-Item "$root/config.psd1" "$temporary/config.psd1"
    Copy-Item "$root/profiles/qwen38fn-myllmbox.psd1" "$temporary/profiles/"
    $config=Get-N1xConfig -Root $temporary -Profile qwen38fn-myllmbox -Port 8123 -ModelRoot "$temporary/model files"
    if($config.Backend -ne 'native' -or $config.UseLMCache -or $config.DFlash -or $config.LanAccess){throw 'Wrong native backend defaults'}
    if($config.Context -ne 409600 -or $config.KvCacheBytes -ne '12000000000'){throw 'Wrong native memory/context budget'}
    $paths=Get-N1xNativePaths $temporary $config
    $arguments=Get-N1xNativeArguments $config $paths
    $generationIndex=[array]::IndexOf($arguments,'--override-generation-config')
    if($generationIndex -lt 0 -or ($arguments[$generationIndex+1]|ConvertFrom-Json).max_new_tokens -ne 8192){throw 'Native output allowance missing'}
    $config.MaxOutputTokens=4096
    $overrideArguments=Get-N1xNativeArguments $config $paths
    if(($overrideArguments[$generationIndex+1]|ConvertFrom-Json).max_new_tokens -ne 4096){throw 'Native output allowance override ignored'}
    $config.MaxOutputTokens=8192
    foreach($required in @('qwen','Qwen/Qwen3.8-Flash-Next','8123','127.0.0.1','409600','12000000000')){
        if($arguments -notcontains $required){throw "Missing native argument: $required"}
    }
    if($paths.Model -notlike '*model files*FP4-Local'){throw 'Native model path ignored'}
    $preview=& "$root/n1x.ps1" start -Profile qwen38fn-myllmbox -ModelRoot "$temporary/model files" -Port 8123 -PrintOnly
    if($preview -match 'wslc' -or $preview -notmatch 'vllm.entrypoints.cli.main' -or $preview -notmatch '8123'){throw 'Native preview dispatched to wrong backend'}
    & "$root/n1x.ps1" setup -Profile qwen38fn-myllmbox -PrintOnly | Out-Null
    if(Test-Path -LiteralPath $paths.State){throw 'Preview wrote process state'}
    $config.LanAccess=$true
    if((Get-N1xNativeArguments $config $paths) -notcontains '0.0.0.0'){throw 'Native LAN override ignored'}
    $created=[datetime]::UtcNow
    $nativeFixture=@{process=[pscustomobject]@{ProcessId=987654;CreationDate=$created;ExecutablePath='C:\fixture\python.exe';CommandLine='python fixture'};killed=$false}
    function Get-CimInstance {param($ClassName,$Filter);$nativeFixture.process}
    function taskkill.exe {param([Parameter(ValueFromRemainingArguments=$true)]$Arguments);$nativeFixture.killed=$true;$global:LASTEXITCODE=0}
    New-Item -ItemType Directory -Force $paths.Directory | Out-Null
    @{processId=987654;creationTicks=$created.Ticks.ToString();executable='C:\fixture\python.exe';commandLine='python fixture'} | ConvertTo-Json | Set-Content $paths.State
    if(-not(Get-N1xNativeProcess $paths.State)){throw 'Owned native process not recognized'}
    try{Assert-N1xNoNativeProfile $temporary;throw 'Concurrent profile accepted'}catch{if($_.Exception.Message -notlike 'Another native project profile*'){throw}}
    Assert-N1xNoNativeProfile $temporary $config.Container
    $nativeFixture.process.CreationDate=$created.AddSeconds(1)
    try{Stop-N1xNative $temporary $config;throw 'Reused PID accepted'}catch{if($_.Exception.Message -notlike 'Native process identity changed*'){throw}}
    if($nativeFixture.killed -or -not(Test-Path $paths.State)){throw 'Identity mismatch killed a process or lost state'}
    $nativeFixture.process.CreationDate=$created
    Stop-N1xNative $temporary $config -PrintOnly | Out-Null
    if($nativeFixture.killed){throw 'Stop preview killed a process'}
    Stop-N1xNative $temporary $config
    if(-not $nativeFixture.killed -or (Test-Path $paths.State)){throw 'Owned process was not stopped and state cleared'}
    $nativeFixture.process=$null
    if(Get-N1xNativeProcess $paths.State){throw 'Missing state reported running'}
    Copy-Item "$root/profiles/qwen38fn-myllmbox.yaml" $paths.Recipe
    $nativeFixture.listener=$true
    $nativeFixture.starts=0
    function wslc { $global:LASTEXITCODE=0 }
    function Get-NetTCPConnection {param($State);if($nativeFixture.listener){[pscustomobject]@{LocalPort=8123}}}
    function Assert-N1xNativeInstallation {param($Paths)}
    function Start-Process {
        param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru,$RedirectStandardOutput,$RedirectStandardError)
        if($WindowStyle -ne 'Hidden' -or $env:PYTHONIOENCODING -ne 'utf-8'){throw 'Missing native launch environment'}
        $nativeFixture.starts++
        $nativeFixture.process=[pscustomobject]@{ProcessId=987654;CreationDate=$created;ExecutablePath=$FilePath;CommandLine=$ArgumentList}
        [pscustomobject]@{Id=987654;HasExited=$false}
    }
    try{Start-N1xNative $temporary $config 'fingerprint';throw 'Occupied port accepted'}catch{if($_.Exception.Message -notlike 'Port 8123 is already in use*'){throw}}
    if($nativeFixture.starts){throw 'Port conflict launched a process'}
    $nativeFixture.listener=$false
    Start-N1xNative $temporary $config 'fingerprint'
    Start-N1xNative $temporary $config 'fingerprint'
    if($nativeFixture.starts -ne 1){throw 'Matching process was launched twice'}
    try{Start-N1xNative $temporary $config 'changed';throw 'Changed config accepted'}catch{if($_.Exception.Message -notlike 'Native settings differ*'){throw}}
    Add-Content -LiteralPath $paths.Recipe '# changed recipe'
    try{Start-N1xNative $temporary $config 'fingerprint';throw 'Changed YAML accepted'}catch{if($_.Exception.Message -notlike 'Native settings differ*'){throw}}
    Stop-N1xNative $temporary $config
    Write-Output 'Native profile, launch, ownership, exclusion, and stop checks passed'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
