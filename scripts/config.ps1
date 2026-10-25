function Get-N1xConfig {
    param([Parameter(Mandatory)][string]$Root, [string]$Profile='', [string]$ModelRoot='', [int]$Port=0)
    $config=Import-PowerShellDataFile (Join-Path $Root 'config.psd1')
    $local=@{}
    $localPath=Join-Path $Root 'config.local.psd1'
    if(Test-Path -LiteralPath $localPath){$local=Import-PowerShellDataFile $localPath}
    if(-not $Profile){$Profile=if($local.ContainsKey('DefaultProfile')){$local.DefaultProfile}else{$config.DefaultProfile}}
    if($Profile -notmatch '^[a-z][a-z0-9-]*$'){throw 'Invalid profile name'}
    if($Profile -ne 'baseline'){
        $path=Join-Path $Root "profiles/$Profile.psd1"
        if(-not(Test-Path -LiteralPath $path)){throw "Unknown profile: $Profile"}
        $overrides=Import-PowerShellDataFile $path
        foreach($key in $overrides.Keys){$config[$key]=$overrides[$key]}
    }
    foreach($key in $local.Keys){$config[$key]=$local[$key]}
    if($ModelRoot){$config.ModelRoot=$ModelRoot}
    if(-not $config.ModelRoot){$config.ModelRoot=Join-Path ([Environment]::GetFolderPath('UserProfile')) 'models'}
    $config.ModelRoot=[IO.Path]::GetFullPath($config.ModelRoot)
    if($Port){$config.Port=$Port}
    if($config.Port -lt 1 -or $config.Port -gt 65535){throw 'Port must be between 1 and 65535'}
    if($config.Container -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]+$'){throw 'Invalid container name'}
    if($config.WindowsMinimumGiB -lt 4){throw 'Keep at least 4 GiB of Windows headroom'}
    $config['Profile']=$Profile
    return $config
}
