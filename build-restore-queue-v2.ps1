param([string]$ParentImage = 'n1x-ai:lmcache-optimization-test')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$raw=& wslc image inspect $ParentImage
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect comparison parent image' }
$parent=@(($raw -join "`n")|ConvertFrom-Json)[0]
$parentId=[string]$parent.Id
if ($parentId -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Unexpected parent image identity' }
# Resolve once, then build from a digest-specific local tag rather than a
# mutable comparison tag. No model or upstream source is modified.
$pinnedTag='n1x-ai:queue-parent-' + $parentId.Substring(7,12)
& wslc tag $parentId $pinnedTag
if ($LASTEXITCODE -ne 0) { throw 'Cannot pin queue parent image' }
& wslc build --build-arg "COMPARISON_IMAGE=$pinnedTag" --build-arg "COMPARISON_IMAGE_ID=$parentId" -t n1x-ai:lmcache-restore-queue-v2-test -f "$PSScriptRoot/cache-tests/Dockerfile.restore-queue-v2" "$PSScriptRoot/cache-tests"
if ($LASTEXITCODE -ne 0) { throw 'Queue image build failed' }
$raw=& wslc image inspect n1x-ai:lmcache-restore-queue-v2-test
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect queue image' }
$child=@(($raw -join "`n")|ConvertFrom-Json)[0]
if ($child.Config.Labels.'n1x-ai.comparison-base' -ne $parentId) { throw 'Queue image parent provenance mismatch' }
[pscustomobject]@{image=$child.Id;baseImage=$parentId}
