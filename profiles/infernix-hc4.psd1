@{
    Backend = 'infernix'
    Container = 'infernix-n1x-hc4-256k'
    InfernixImage = 'infernix:n1x'
    InfernixVolume = 'infernix-hc4-ple-a78ba00a'
    Port = 8001
    Context = 262144
    MaxSequences = 8
    MaxOutputTokens = 262144
    DFlash = $true
    Mtp = $false
    DFlashTokens = 3
    UseLMCache = $false
}
