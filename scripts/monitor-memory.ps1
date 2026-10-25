param([Parameter(Mandatory)][string]$Container,[Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference='Stop'
$utf8=[Text.UTF8Encoding]::new($false)
while($true){
    $raw=& wslc inspect $Container
    if($LASTEXITCODE -ne 0){Start-Sleep -Seconds 5;continue}
    $state=@(($raw -join "`n")|ConvertFrom-Json)[0]
    if(-not $state.State.Running){break}
    $os=Get-CimInstance Win32_OperatingSystem
    $json=@{availableGiB=$os.FreePhysicalMemory/1MB;updatedUnixSeconds=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}|ConvertTo-Json -Compress
    # WSLC readers can hold a Windows handle that prevents atomic replacement.
    # Update the small snapshot in place; the supervisor retries partial JSON.
    try {[IO.File]::WriteAllText($OutputPath,$json,$utf8)}
    catch [IO.IOException] { Write-Warning 'Memory snapshot is busy; retrying next interval' }
    Start-Sleep -Seconds 5
}
