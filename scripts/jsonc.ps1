# Preserve source offsets while validating JSON with comments and trailing commas.
function Read-N1xJsonc([string]$Text) {
    $pattern='"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
    $plain=[regex]::Replace($Text,$pattern,[Text.RegularExpressions.MatchEvaluator]{
        param($match)
        if($match.Value.StartsWith('"')){return $match.Value}
        return [regex]::Replace($match.Value,'[^\r\n]',' ')
    })
    # Match strings first so punctuation inside a string is never rewritten.
    $plain=[regex]::Replace($plain,'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',[Text.RegularExpressions.MatchEvaluator]{
        param($match)
        if($match.Value -eq ','){return ' '}
        return $match.Value
    })
    try {$document=$plain|ConvertFrom-Json}
    catch {throw 'Invalid JSONC; preserving the original client configuration'}
    if($document -isnot [pscustomobject]){throw 'Expected a JSONC object'}
    $tokens=@([regex]::Matches($plain,'"(?:\\.|[^"\\])*"|[{}\[\]:,]|[^\s{}\[\]:,]+'))
    $depth=0
    $providersOpen=-1
    for($i=0;$i -lt $tokens.Count;$i++){
        $token=$tokens[$i].Value
        if($depth -eq 1 -and $token.StartsWith('"') -and ($token|ConvertFrom-Json) -ceq 'providers' -and $tokens[$i+1].Value -eq ':'){
            if($tokens[$i+2].Value -ne '{'){throw 'Expected a providers object'}
            $providersOpen=$tokens[$i+2].Index
        }
        if($token -in @('{','[')){$depth++}
        if($token -in @('}',']')){$depth--}
    }
    return [pscustomobject]@{Document=$document;RootOpen=$tokens[0].Index;ProvidersOpen=$providersOpen}
}

function Update-N1xJsoncEntry {
    param([string]$Path,[string]$Owner,[object]$Value,[switch]$Remove)
    $statePath=$Path+'.n1x-managed.json'
    $original=[IO.File]::ReadAllText($Path)
    $parsed=Read-N1xJsonc $original
    $state=if(Test-Path -LiteralPath $statePath){Get-Content -LiteralPath $statePath -Raw|ConvertFrom-Json}else{$null}
    if($state -and $state.owner -ne $Owner){throw 'N1X entry belongs to another checkout'}
    if($Remove -and -not $state){return}
    $base=$original
    if($state){
        $position=$base.IndexOf([string]$state.block,[StringComparison]::Ordinal)
        if($position -lt 0 -or $base.IndexOf([string]$state.block,$position+1,[StringComparison]::Ordinal) -ge 0){
            throw 'Managed JSONC block was edited; preserving it'
        }
        $base=$base.Remove($position,$state.block.Length)
        $parsed=Read-N1xJsonc $base
    }
    $replacement=$base
    $block=''
    if(-not $Remove){
        if($parsed.ProvidersOpen -ge 0 -and $parsed.Document.providers.PSObject.Properties['n1x']){
            throw 'Existing N1X entry is user-owned; preserving it'
        }
        $newline=if($base.Contains("`r`n")){"`r`n"}else{"`n"}
        $entry='"n1x": '+($Value|ConvertTo-Json -Depth 50 -Compress)
        $position=$parsed.ProvidersOpen+1
        if($parsed.ProvidersOpen -lt 0){$entry='"providers": {'+$entry+'}';$position=$parsed.RootOpen+1}
        $block=$newline+'  // n1x-ai managed provider'+$newline+'  '+$entry+','+$newline
        $replacement=$base.Insert($position,$block)
    }
    $null=Read-N1xJsonc $replacement
    if([IO.File]::ReadAllText($Path) -cne $original){throw 'Client config changed concurrently; retry the command'}
    if($Remove){
        Write-N1xClientFile $Path $replacement
        Remove-Item -LiteralPath $statePath
    } else {
        Write-N1xClientFile $statePath (@{owner=$Owner;block=$block}|ConvertTo-Json -Depth 5)
        Write-N1xClientFile $Path $replacement
    }
}
