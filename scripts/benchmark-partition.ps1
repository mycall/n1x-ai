function Get-N1xBenchmarkPartitionMiB {
    # This N1X host also reports a non-CUDA adapter with memory.total=N/A.
    # Serving uses CUDA device zero; do not confuse the extra adapter with it.
    $values=@(& nvidia-smi --id=0 --query-gpu=memory.total --format=csv,noheader,nounits)
    if($LASTEXITCODE -ne 0 -or $values.Count -ne 1){
        throw 'Cannot verify the benchmark GPU partition: expected one result for GPU 0 from nvidia-smi.'
    }
    $memoryMiB=0
    if(-not [int]::TryParse(([string]$values[0]).Trim(),[ref]$memoryMiB) -or $memoryMiB -le 0){
        throw 'Cannot verify the benchmark GPU partition: invalid nvidia-smi memory total.'
    }
    return $memoryMiB
}

function Confirm-N1xBenchmarkPartition {
    param([Parameter(Mandatory)][string]$Group,
          [ValidateRange(1,1048576)][int]$RequiredMiB=90112)
    $actual=Get-N1xBenchmarkPartitionMiB
    $confirmed=$false
    if($actual -ne $RequiredMiB){
        $requiredGiB=$RequiredMiB/1024
        Write-Host "$Group requires the documented $requiredGiB GiB GPU partition; currently $($actual/1024) GiB. Tests are waiting."
        Write-Host 'Stop the model server before changing the partition in the NVIDIA app. If a reboot is needed, cancel and rerun the test command afterward. Restart the requested profile before resuming an existing-server benchmark.'
        try {$answer=Read-Host "After changing it, type $requiredGiB to recheck and continue; anything else cancels"}
        catch {throw "Partition change required before $Group. Interactive confirmation is unavailable; switch to $requiredGiB GiB and rerun. No tests started."}
        if($answer -ne [string]$requiredGiB){throw "Cancelled $Group before testing; partition was not confirmed."}
        $actual=Get-N1xBenchmarkPartitionMiB
        if($actual -ne $RequiredMiB){throw "Partition still reports $($actual/1024) GiB; $Group requires $requiredGiB GiB. No tests started."}
        $confirmed=$true
    }
    return @{group=$Group;requiredMiB=$RequiredMiB;actualMiB=$actual;changeConfirmed=$confirmed;verifiedUtc=[datetime]::UtcNow.ToString('o')}
}
