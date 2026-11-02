@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'qwen38fn-cache-dflash'
    Port = 8000
    # Output allowance/cap when clients omit a smaller limit; includes reasoning.
    MaxOutputTokens = 8192
    # Set false for localhost-only serving; recreate after changing.
    LanAccess = $true
    # Optional cache budget and bounded restore admission:
    # LmcacheL1GiB = 4
    # LmcacheL2GiB = 16  # Shared SSD budget; 0 disables new SSD caching.
    # RestoreWaitMs = 2000
}
