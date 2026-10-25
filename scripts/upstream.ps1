function Initialize-N1xUpstream([string]$Root,[string]$Repository,[string]$Revision){
    $upstream=Join-Path $Root 'upstream'
    # Explicit git-dir prevents Git from walking up to n1x-ai/.git.
    $valid=$false
    if(Test-Path -LiteralPath "$upstream/.git/HEAD"){
        $actual=& git --git-dir="$upstream/.git" --work-tree="$upstream" rev-parse --verify HEAD
        $valid=$LASTEXITCODE -eq 0
    }
    if(-not $valid){
        if(Test-Path -LiteralPath $upstream){
            if((Get-Item -LiteralPath $upstream -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Refusing linked upstream directory'}
            # Preserve partial checkout contents, rather than discarding edits.
            $backup=Join-Path $Root ('.build/upstream-incomplete-'+[guid]::NewGuid().ToString('N'))
            $prefix=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')+'\'
            foreach($path in @($upstream,$backup)){
                if(-not [IO.Path]::GetFullPath($path).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe upstream recovery path'}
            }
            New-Item -ItemType Directory -Force (Split-Path $backup -Parent) | Out-Null
            Move-Item -LiteralPath $upstream -Destination $backup -Force -ErrorAction Stop
            Write-Host "Preserved incomplete upstream checkout: $backup"
        }
        & git clone --no-checkout $Repository $upstream
        if($LASTEXITCODE -ne 0){throw 'Upstream clone failed; rerun setup to retry'}
        & git --git-dir="$upstream/.git" --work-tree="$upstream" checkout --detach $Revision
        if($LASTEXITCODE -ne 0){throw 'Upstream checkout failed'}
        $actual=& git --git-dir="$upstream/.git" --work-tree="$upstream" rev-parse --verify HEAD
        if($LASTEXITCODE -ne 0){throw 'Cannot verify upstream checkout'}
    }
    if($actual -ne $Revision){throw "Expected upstream $Revision, found $actual"}
}
