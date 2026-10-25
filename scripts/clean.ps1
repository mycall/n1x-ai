param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$ModelRoot,
    [switch]$PrintOnly, [string]$VhdPath='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
$prefix=$rootPath+[IO.Path]::DirectorySeparatorChar
$modelPath=[IO.Path]::GetFullPath($ModelRoot).TrimEnd('\','/')
# Enumerate files through Git, but delete through PowerShell using literal paths.
# Never recursively traverse an ignored junction, or remove local configuration.
$raw=& git -C $rootPath -c core.quotepath=false ls-files --others --ignored --exclude-standard --directory -z
if($LASTEXITCODE -ne 0){throw 'Cannot enumerate ignored files'}
$files=[Collections.Generic.List[IO.FileInfo]]::new()
$directories=[Collections.Generic.List[string]]::new()
$pending=[Collections.Generic.Stack[string]]::new()
foreach($relative in (($raw -join "`n").Split([char]0))){if($relative){$pending.Push((Join-Path $rootPath $relative))}}
$checked=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
while($pending.Count){
    $path=[IO.Path]::GetFullPath($pending.Pop()).TrimEnd('\','/')
    if(-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw "Path outside repository: $path"}
    if($path -eq "$rootPath\config.local.psd1" -or ($VhdPath -and ($path -eq "$rootPath\.state" -or $path.StartsWith("$rootPath\.state\",[StringComparison]::OrdinalIgnoreCase))) -or
        $path -eq $modelPath -or $path.StartsWith($modelPath+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
    $cursor=$path
    while($cursor -ne $rootPath -and -not $checked.Contains($cursor)){
        if((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw "Refusing linked path: $cursor"}
        [void]$checked.Add($cursor)
        $cursor=Split-Path $cursor -Parent
    }
    $item=Get-Item -LiteralPath $path -Force
    if($item.PSIsContainer){
        $directories.Add($path)
        foreach($child in (Get-ChildItem -LiteralPath $path -Force)){$pending.Push($child.FullName)}
    } else {$files.Add($item)}
}
if($VhdPath){
    $disk=Get-Item -LiteralPath $VhdPath -Force
    if($disk.Extension -ne '.vhdx' -or $disk.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'VhdPath must be an ordinary .vhdx file'}
    $VhdPath=$disk.FullName
    if(-not $PrintOnly){
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if(-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Offline VHDX compaction requires an elevated PowerShell'}
        if((Get-DiskImage -ImagePath $VhdPath).Attached){throw 'VHDX is attached. Stop its WSLC session before offline compaction.'}
    }
}
$bytes=0L
foreach($file in $files){$bytes+=$file.Length}
Write-Host "Ignored files: $($files.Count); bytes: $bytes"
if($PrintOnly){
    $files | ForEach-Object {Write-Output "Delete: $($_.FullName)"}
    $directories | Sort-Object Length -Descending | ForEach-Object {Write-Output "Remove if empty: $_"}
    Write-Output 'Trim: wslc system session run /usr/sbin/fstrim -av (skipped during offline VHDX compaction)'
    if($VhdPath){Write-Output "Compact offline: $VhdPath"}
    return
}
if(-not $VhdPath){
    $running=@(& wslc list --filter 'label=n1x-ai.managed=true' --format json)
    if($LASTEXITCODE -ne 0){throw 'Cannot check running project containers'}
    if(@($running | Where-Object {$_.Trim()}).Count){throw 'Stop project containers before cleaning. Use clean -PrintOnly to preview.'}
}
foreach($file in $files){Remove-Item -LiteralPath $file.FullName -Force}
# Include empty Git directories (objects/info, refs/tags, etc.), which have
# no deleted file whose parent cleanup could discover them.
foreach($directory in ($directories | Sort-Object Length -Descending)){
    if((Test-Path -LiteralPath $directory) -and -not @(Get-ChildItem -LiteralPath $directory -Force).Count){Remove-Item -LiteralPath $directory -Force}
}
# Remove only empty parents of deleted files; no recursive directory deletion.
foreach($file in $files){
    $parent=$file.DirectoryName
    while($parent -ne $rootPath -and $parent.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){
        if(-not(Test-Path -LiteralPath $parent)){break}
        if(@(Get-ChildItem -LiteralPath $parent -Force).Count){break}
        Remove-Item -LiteralPath $parent -Force
        $parent=Split-Path $parent -Parent
    }
}
if($VhdPath){
    $before=(Get-Item -LiteralPath $VhdPath).Length
    if(Get-Command Optimize-VHD -ErrorAction SilentlyContinue){Optimize-VHD -Path $VhdPath -Mode Full}
    else {
        if($VhdPath -match '["\r\n]'){throw 'Invalid disk path'}
        $commandFile=Join-Path ([IO.Path]::GetTempPath()) ('n1x-compact-'+[guid]::NewGuid().ToString('N')+'.txt')
        try {
            [IO.File]::WriteAllLines($commandFile,@(('select vdisk file="'+$VhdPath+'"'),'compact vdisk','exit'))
            $output=& diskpart.exe /s $commandFile
            $exitCode=$LASTEXITCODE
            $output | Write-Host
            if($exitCode -ne 0 -or ($output -join "`n") -notmatch 'successfully compacted'){
                throw 'DiskPart compaction could not be verified; inspect its output (localized Windows may use different success text).'
            }
        } finally {Remove-Item -LiteralPath $commandFile -Force}
    }
    Write-Host "VHDX length: $before -> $((Get-Item -LiteralPath $VhdPath).Length) bytes"
} else {
    & wslc system session run /usr/sbin/fstrim -av
    if($LASTEXITCODE -ne 0){Write-Warning 'Ignored files cleaned, but WSLC trim failed. Retry from an interactive terminal. No physical disk reclamation is claimed.'}
    Write-Host 'TRIM releases unused Linux blocks; physical Windows reclamation may require offline clean -VhdPath <backing.vhdx> in elevated PowerShell.'
}
Write-Host 'Repository cleanup preserved Models and local configuration.'
