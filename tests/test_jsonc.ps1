$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/../scripts/clients.ps1"
. "$PSScriptRoot/../scripts/jsonc.ps1"
$directory=Join-Path ([IO.Path]::GetTempPath()) ('n1x-jsonc-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $directory|Out-Null
try {
    $path=Join-Path $directory 'opencode.jsonc'
    $value=@{name='N1X';models=@{qwen=@{capabilities=@{reasoning=@{supported=$true}}}}}
    foreach($original in @(
        '{/* keep this */ "model":"other/model",}',
        "{`r`n // user comment`r`n `"providers`": {`"other`": {`"url`": `"http://host/a,}//b`"},},`r`n}",
        '{"providers": {/*empty*/},"text":"escaped \" // not comment"}',
        '{"providers":{"other":{}},"nested":{"providers":{}}}'
    )){
        [IO.File]::WriteAllText($path,$original)
        Update-N1xJsoncEntry -Path $path -Owner $directory -Value $value
        $doc=(Read-N1xJsonc ([IO.File]::ReadAllText($path))).Document
        if(-not $doc.providers.n1x.models.qwen.capabilities.reasoning.supported){throw 'Missing reasoning metadata'}
        Update-N1xJsoncEntry -Path $path -Owner $directory -Value $value
        Update-N1xJsoncEntry -Path $path -Owner $directory -Remove
        if([IO.File]::ReadAllText($path) -cne $original){throw 'JSONC round trip changed original text'}
    }
    Update-N1xJsoncEntry -Path $path -Owner $directory -Value $value
    $text=[IO.File]::ReadAllText($path).Replace('"other":{}','"other":{"edited":true}')
    [IO.File]::WriteAllText($path,$text)
    Update-N1xJsoncEntry -Path $path -Owner $directory -Remove
    if(-not (Read-N1xJsonc ([IO.File]::ReadAllText($path))).Document.providers.other.edited){throw 'Concurrent unrelated edit lost'}
    [IO.File]::WriteAllText($path,'{"providers":{"n1x":{"name":"user"}}}')
    try {Update-N1xJsoncEntry -Path $path -Owner $directory -Value $value;throw 'Collision accepted'}
    catch {if($_.Exception.Message -notlike 'Existing N1X entry*'){throw}}
    Write-Host 'JSONC preservation and ownership checks passed.'
} finally {
    if([IO.Path]::GetFullPath($directory).StartsWith([IO.Path]::GetTempPath(),[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $directory -Recurse -Force}
}
