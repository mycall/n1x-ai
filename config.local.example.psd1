@{
    ModelRoot = 'D:\Models'
    DefaultProfile = 'qwen38fn-best'
    Port = 8000
    # Output allowance/cap when clients omit a smaller limit; includes reasoning.
    MaxOutputTokens = 8192
    # Experimental MyLLMBox DFlash2 depth, 1-7; K3 is the qualified default.
    # DFlashTokens = 3
    # Set true for local-subnet access; recreate after changing.
    LanAccess = $false
    # Optional cache budget and bounded restore admission:
    # LmcacheL1GiB = 4
    # LmcacheL2GiB = 16  # Shared SSD budget; 0 disables new SSD caching.
    # RestoreWaitMs = 2000
}
