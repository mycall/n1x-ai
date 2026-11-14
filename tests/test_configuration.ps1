$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-config-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/profiles"|Out-Null
try {
    Copy-Item "$root/config.psd1" "$temporary/config.psd1"
    Copy-Item "$root/profiles/qwen38fn-cache-mtp.psd1" "$temporary/profiles/qwen38fn-cache-mtp.psd1"
    Copy-Item "$root/profiles/qwen38fn-cache-dflash.psd1" "$temporary/profiles/qwen38fn-cache-dflash.psd1"
    Copy-Item "$root/profiles/qwen38fn-best.psd1" "$temporary/profiles/qwen38fn-best.psd1"
    $config=Get-N1xConfig -Root $temporary
    if($config.MaxOutputTokens -ne 8192){throw 'Default output allowance must be 8192'}
    if($config.DFlashTokens -ne 3){throw 'Default DFlash2 depth must remain K3'}
    if($config.Profile -ne 'qwen38fn-best' -or -not $config.DFlash -or -not $config.UseLMCache -or $config.Mtp){throw 'Selected default must use the promoted LMCache DFlash2 best profile'}
    if($config.Backend -ne 'wslc-myllmbox' -or $config.Context -ne 262144 -or $config.RequiredPartitionMiB -ne 98304 -or $config.KvCacheBytes -ne '16106127360'){throw 'Selected default differs from the promoted 96 GiB configuration'}
    $reference=Get-N1xConfig -Root $temporary -Profile qwen38fn-cache-dflash
    if(-not $reference.DFlash -or -not $reference.UseLMCache -or $reference.Mtp){throw 'Original cache-DFlash reference must remain selectable'}
    foreach($oldName in @('baseline','mtp','cache','cache-mtp','cache-dflash','qwen38fn-devjeonghwan')){
        try {Get-N1xConfig -Root $root -Profile $oldName;throw "Old name accepted: $oldName"}
        catch {if($_.Exception.Message -ne "Unknown profile: $oldName"){throw}}
    }
    $expectedRoot=Join-Path ([Environment]::GetFolderPath('UserProfile')) 'models'
    if($config.ModelRoot -ne $expectedRoot){throw 'Default model path is not portable'}
    $overrideRoot=Join-Path $temporary 'model files'
    $escaped=$overrideRoot.Replace("'","''")
    [IO.File]::WriteAllText("$temporary/config.local.psd1","@{ ModelRoot='$escaped'; DefaultProfile='qwen38fn-cache-mtp'; Port=8001 }")
    $config=Get-N1xConfig -Root $temporary
    if(-not $config.Mtp -or -not $config.UseLMCache -or $config.Port -ne 8001 -or $config.ModelRoot -ne $overrideRoot){throw 'Local configuration precedence failed'}
    $config=Get-N1xConfig -Root $temporary -Port 8002
    if($config.Port -ne 8002){throw 'CLI override failed'}
    try{Get-N1xConfig -Root $temporary -Profile '../escape';throw 'Traversal accepted'}catch{if($_.Exception.Message -ne 'Invalid profile name'){throw}}
    $preview=& "$root/n1x.ps1" start -Profile qwen38fn-cache-mtp -ModelRoot $overrideRoot -PrintOnly
    if($preview -notmatch 'n1x-ai:lmcache' -or $preview -notmatch 'fp8_e4m3' -or $preview -notmatch '/profiles/qwen38fn-mtp.yaml'){throw 'Portable launch preview failed'}
    $draftPreview=& "$root/n1x.ps1" start -Profile qwen38fn-cache-dflash -ModelRoot $overrideRoot -PrintOnly
    if($draftPreview -notmatch '--override-generation-config' -or $draftPreview -notmatch 'max_new_tokens.*8192'){throw 'Server output allowance missing from container launch'}
    foreach($required in @('/drafter:ro','/profiles/qwen38fn-dflash.yaml','sliding_window','fp8-dflash-a22a','VLLM_INDEXER_FP8=1','-idxfp8')){
        if(-not $draftPreview.Contains($required)){throw "DFlash launch missing $required"}
    }
    if($draftPreview.Contains('/profiles/qwen38fn-mtp.yaml')){throw 'DFlash launch also enables MTP'}
    if($draftPreview -notmatch '0\.0\.0\.0:\d+:8000'){throw 'LAN publication missing'}
    [IO.File]::WriteAllText("$temporary/config.local.psd1",'@{LanAccess=$false}')
    $localConfig=Get-N1xConfig -Root $temporary
    if($localConfig.LanAccess){throw 'LAN opt-out ignored'}
    [IO.File]::WriteAllText("$temporary/config.local.psd1",'@{MaxOutputTokens=4096}')
    if((Get-N1xConfig -Root $temporary).MaxOutputTokens -ne 4096){throw 'Local output allowance override ignored'}
    foreach($invalid in @('0','-1','1.5','262144')){
        [IO.File]::WriteAllText("$temporary/config.local.psd1","@{MaxOutputTokens=$invalid}")
        try{Get-N1xConfig -Root $temporary;throw 'Invalid output allowance accepted'}catch{
            if($_.Exception.Message -ne 'MaxOutputTokens must be a positive integer smaller than Context'){throw}
        }
    }
    foreach($depth in 1..7){
        [IO.File]::WriteAllText("$temporary/config.local.psd1","@{DFlashTokens=$depth}")
        if((Get-N1xConfig -Root $temporary).DFlashTokens -ne $depth){throw 'Local DFlashTokens override ignored'}
    }
    foreach($invalid in @('0','-1','1.5','8',"'5'",'$true')){
        [IO.File]::WriteAllText("$temporary/config.local.psd1","@{DFlashTokens=$invalid}")
        try{Get-N1xConfig -Root $temporary;throw 'Invalid DFlashTokens accepted'}catch{
            if($_.Exception.Message -ne 'DFlashTokens must be an integer from 1 through 7'){throw}
        }
    }
    [IO.File]::WriteAllText("$temporary/config.local.psd1",'@{DFlashTokens=5}')
    if((Get-N1xConfig -Root $temporary -Profile qwen38fn-cache-dflash).DFlashTokens -ne 3){throw 'Reference recipe inherited an unsupported MyLLMBox depth'}
    $inventory=@(Get-N1xProfileList -Root $temporary)
    if($inventory.Count -ne 4){throw 'A local draft-depth override broke profile inventory'}
    if(($inventory|Where-Object Profile -eq 'qwen38fn-best').Speculation -ne 'DFlash2 K5' -or
        ($inventory|Where-Object Profile -eq 'qwen38fn-cache-dflash').Speculation -ne 'DFlash2 K3'){
        throw 'Profile inventory does not show effective DFlash2 depths'
    }
    [IO.File]::WriteAllText("$temporary/config.local.psd1",'@{CacheBlockTokens=1024;LmcacheChunkTokens=1536}')
    try{Get-N1xConfig -Root $temporary;throw 'Misaligned cache geometry accepted'}catch{
        if($_.Exception.Message -ne 'LMCache chunk tokens must be a positive multiple of cache block tokens'){throw}
    }
    Write-Output 'Configuration and launch checks passed'
} finally {
    # Only this explicitly created temporary directory may be removed.
    $resolved=[IO.Path]::GetFullPath($temporary)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
