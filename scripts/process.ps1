function Invoke-N1xCapturedProcess {
    param([Parameter(Mandatory)][string]$FilePath,[string[]]$ArgumentList=@())
    # Bypass PowerShell's native output encoding path (notably for DiskPart).
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=$FilePath
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    foreach($argument in $ArgumentList){$start.ArgumentList.Add($argument)}
    $process=[Diagnostics.Process]::Start($start)
    try {
        # Drain both pipes concurrently; sequential reads can deadlock.
        $stdout=$process.StandardOutput.ReadToEndAsync()
        $stderr=$process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [pscustomobject]@{ExitCode=$process.ExitCode;Stdout=$stdout.GetAwaiter().GetResult();Stderr=$stderr.GetAwaiter().GetResult()}
    } finally {$process.Dispose()}
}
