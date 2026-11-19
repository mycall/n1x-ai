using System.Text.Json.Nodes;
using N1x.Benchmarks;

static class QualificationTests
{
    static void Check(bool ok, string message) { if (!ok) throw new Exception(message); }
    public static async Task Run()
    {
        JsonNode Choice(string? text, bool call = false) => Data.Obj(new { message = new { content = text, tool_calls = call ? new[] { new { id = "call" } } : null } });
        foreach (var (first, retry, expected) in new[] { (Choice(" "), Choice("ok"), true), (Choice("ok"), Choice(""), false), (Choice(null, true), Choice("ok"), false) })
        {
            int n = 0;
            var row = await Qualification.Required(() => Task.FromResult(n++ == 0 ? first : retry), r => (string?)r["message"]!["content"] == "ok");
            Check((bool)row["retried_empty_final"]! == expected && n == (expected ? 2 : 1), "Empty final retry count");
            Check((bool)row["correct"]! == ((string?)first["message"]!["content"] == "ok"), "First score changed");
            if (expected) Check((bool?)row["retry_correct"] == true && (bool?)row["retry_empty_final"] == false, "Retry result");
        }
        var sizes = RestoreStorage.Estimate([118226944, 53477376, 41943040], 130877, 260877);
        Check(sizes.working_set_bytes / (double)(1L << 30) == 50.9375, "Restore capacity estimate");
        sizes.Require(64L << 30);
        try { sizes.Require(48L << 30); throw new Exception("Undersized volume passed"); } catch (ArgumentOutOfRangeException) { }
        Check(RestoreStorage.Estimate([4097], 4097, 1, 1, 1, 4096, 0).required_bytes == 3 * 8192, "Partial chunks");
        string[] keys = ["vllm:prefix_cache_hits_total", "vllm:external_prefix_cache_hits_total", "vllm:num_preemptions_total", "lmcache_mp_num_finished_retrieves_total", "lmcache_mp_l2_prefetch_load_completed_chunks_total"];
        var before = keys.Take(3).ToDictionary(k => k, k => 0.0); var after = new Dictionary<string, double>(before) { [keys[1]] = 260000, [keys[3]] = 2, [keys[4]] = 186 };
        bool Qualified() => (bool)Qualification.RestoreSummary(before, after, 130877, [true, true], 3)["qualified"]!;
        Check(Qualified(), "Lazy cache counters rejected");
        foreach (var (i, bad) in new[] { (0, 4096.0), (1, 0), (3, 1), (4, 0), (4, -1), (4, double.NaN), (4, double.PositiveInfinity) })
        {
            double original = after[keys[i]]; after[keys[i]] = bad; Check(!Qualified(), "Invalid restore evidence qualified"); after[keys[i]] = original;
        }
        before.Remove(keys[0]); Check(!Qualified(), "Missing vLLM baseline accepted");
    }
}
