namespace N1x.Benchmarks;

public record RestoreStorage(long bytes_per_chunk, long chunks, long working_set_bytes, long reserve_bytes, long required_bytes)
{
    public string scope => "Upper envelope; assumes all groups stored at every chunk";
    public static RestoreStorage Estimate(long[] groupBytes, long seedTokens, long pressureTokens, long seedCount = 2,
        long pressureCount = 3, long chunkTokens = 4096, long reserveBytes = 4L << 30)
    {
        if (groupBytes.Length == 0 || groupBytes.Any(v => v <= 0) || seedTokens <= 0 || pressureTokens <= 0 || seedCount <= 0 || pressureCount <= 0 || chunkTokens <= 0 || reserveBytes < 0)
            throw new ArgumentOutOfRangeException(nameof(groupBytes), "Layout and workload sizes must be positive and reserve nonnegative");
        static long Ceil(long n, long d) => 1 + (n - 1) / d;
        checked
        {
            long per = groupBytes.Sum(n => checked(Ceil(n, 4096) * 4096));
            long chunks = seedCount * Ceil(seedTokens, chunkTokens) + pressureCount * Ceil(pressureTokens, chunkTokens);
            long working = per * chunks;
            return new(per, chunks, working, reserveBytes, working + reserveBytes);
        }
    }
    public void Require(long capacity)
    {
        if (capacity <= 0 || capacity < required_bytes) throw new ArgumentOutOfRangeException(nameof(capacity), "SSD budget cannot retain the restore workload and its reserve");
    }
}
