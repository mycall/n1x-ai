function Get-N1xProfileList {
    param([Parameter(Mandatory)][string]$Root)
    $names=@('qwen38fn-baseline')+@(Get-ChildItem (Join-Path $Root 'profiles') -Filter '*.psd1' -File | ForEach-Object BaseName)
    foreach($name in ($names | Sort-Object -Unique)){
        $settings=Get-N1xConfig -Root $Root -Profile $name
        [pscustomobject]@{
            Profile=$name
            Default=if($name -eq $settings.DefaultProfile){'*'}else{''}
            Runtime=if($settings.ContainsKey('Backend') -and $settings.Backend -eq 'native'){'Windows'}else{'WSLC'}
            Context=$settings.Context
            Speculation=if($settings.DFlash){"DFlash2 K$($settings.DFlashTokens)"}elseif($settings.Mtp){'MTP'}else{'Off'}
            LMCache=$settings.UseLMCache
        }
    }
}

function Get-N1xConfig {
    param([Parameter(Mandatory)][string]$Root, [string]$Profile='', [string]$ModelRoot='', [int]$Port=0)
    $config=Import-PowerShellDataFile (Join-Path $Root 'config.psd1')
    $local=@{}
    $localPath=Join-Path $Root 'config.local.psd1'
    if(Test-Path -LiteralPath $localPath){$local=Import-PowerShellDataFile $localPath}
    if(-not $Profile){$Profile=if($local.ContainsKey('DefaultProfile')){$local.DefaultProfile}else{$config.DefaultProfile}}
    if($Profile -notmatch '^[a-z][a-z0-9-]*$'){throw 'Invalid profile name'}
    if($Profile -ne 'qwen38fn-baseline'){
        $path=Join-Path $Root "profiles/$Profile.psd1"
        if(-not(Test-Path -LiteralPath $path)){throw "Unknown profile: $Profile"}
        $overrides=Import-PowerShellDataFile $path
        foreach($key in $overrides.Keys){$config[$key]=$overrides[$key]}
    }
    foreach($key in $local.Keys){$config[$key]=$local[$key]}
    if($ModelRoot){$config.ModelRoot=$ModelRoot}
    if(-not $config.ModelRoot){$config.ModelRoot=Join-Path ([Environment]::GetFolderPath('UserProfile')) 'models'}
    if($config.ModelRoot -match '^~[\\/]'){$config.ModelRoot=Join-Path ([Environment]::GetFolderPath('UserProfile')) $config.ModelRoot.Substring(2)}
    $config.ModelRoot=[IO.Path]::GetFullPath($config.ModelRoot)
    if($Port){$config.Port=$Port}
    if($config.Port -lt 1 -or $config.Port -gt 65535){throw 'Port must be between 1 and 65535'}
    if($config.MaxOutputTokens -isnot [int] -or $config.MaxOutputTokens -lt 1 -or $config.MaxOutputTokens -ge $config.Context){
        throw 'MaxOutputTokens must be a positive integer smaller than Context'
    }
    if($config.DFlashTokens -isnot [int] -or $config.DFlashTokens -lt 1 -or $config.DFlashTokens -gt 7){
        throw 'DFlashTokens must be an integer from 1 through 7'
    }
    if($config.DFlashTokens -ne 3 -and (-not $config.ContainsKey('Backend') -or $config.Backend -ne 'wslc-myllmbox')){
        # Other backends keep their fixed recipes; discard this MyLLMBox-only
        # override when inventory/cleanup enumerates those profiles.
        $config.DFlashTokens=3
    }
    if($config.ContainsKey('Backend')){
        if($config.Backend -notin @('native','wslc-myllmbox')){throw 'Unknown serving backend'}
        if($config.Backend -eq 'native'){
        foreach($key in @('NativeRuntimeRoot','NativeConfig','NativeModel')){
            if(-not $config.ContainsKey($key) -or -not $config[$key]){throw "Missing native setting: $key"}
        }
        if($config.UseLMCache -or $config.DFlash -or -not $config.Mtp){throw 'The native RTX Spark recipe requires MTP without DFlash or LMCache'}
        }
        if($config.Backend -eq 'wslc-myllmbox'){
            foreach($key in @('ImageId','MyllmboxConfig','MyllmboxEnvironment','MyllmboxModel','MyllmboxDrafter','MyllmboxWSLCVersion','RequiredPartitionMiB')){
                if(-not $config.ContainsKey($key) -or -not $config[$key]){throw "Missing MyLLMBox setting: $key"}
            }
            if($config.ImageId -notmatch '^sha256:[a-f0-9]{64}$'){throw 'MyLLMBox requires an immutable ImageId'}
            if($config.Mtp -or -not $config.DFlash){throw 'The MyLLMBox recipe requires DFlash2'}
            if($config.UseLMCache){
                if(-not $config.ContainsKey('LmcacheNamespace') -or $config.LmcacheNamespace -notmatch '^qwen-[A-Za-z0-9._-]+$'){throw 'MyLLMBox LMCache requires a qwen- namespace without path separators'}
                if($config.LmcacheVolume -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]+$' -or $config.LmcacheL1GiB -le 0 -or $config.LmcacheL2GiB -le 0 -or $config.RestoreWaitMs -lt 0){throw 'MyLLMBox LMCache requires bounded positive RAM/SSD budgets, a named volume and a nonnegative restore wait'}
            }
            if($config.MaxSequences -isnot [int] -or $config.MaxSequences -lt 1 -or $config.MaxSequences -gt 8){throw 'MyLLMBox sequence slots must be an integer from 1 through 8'}
            if($config.RequiredPartitionMiB -notin @(90112,98304)){throw 'MyLLMBox requires a qualified 88 or 96 GiB partition; the selected profile specifies which'}
        }
    }
    if($config.Container -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]+$'){throw 'Invalid container name'}
    if($config.WindowsMinimumGiB -lt 4){throw 'Keep at least 4 GiB of Windows headroom'}
    if($config.LmcacheL2GiB -lt 0){throw 'LMCache SSD budget cannot be negative'}
    if($config.CacheBlockTokens -le 0 -or $config.LmcacheChunkTokens -le 0 -or $config.LmcacheChunkTokens % $config.CacheBlockTokens){
        throw 'LMCache chunk tokens must be a positive multiple of cache block tokens'
    }
    $config['Profile']=$Profile
    return $config
}
