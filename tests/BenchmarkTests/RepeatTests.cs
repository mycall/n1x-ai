using N1x.Benchmarks;
using System.Text.Json.Nodes;

static class RepeatTests
{
    public static void Run()
    {
        var trials = new List<JsonObject>();
        foreach (int pair in new[] { 1, 2, 3 }) foreach (int batch in new[] { 4096, 8192 })
        {
            var row = Data.Obj(new { pair, batch, status = new { stage = "finished", success = batch == 4096 } });
            if (pair != 3 || batch != 8192) row["near_full"] = new JsonArray(Data.Obj(new
            {
                concurrency = 4,
                elapsed_s = 90 + 10 * pair - (batch == 8192 ? 10 : 0),
                correct_tasks = batch == 8192 ? 11 : 12,
                planned_tasks = 12,
                cache_evidence = new Dictionary<string, object> { { "tool-continuation", new { requests = 12, requests_with_cached_tokens = 12 } } }
            }));
            if (pair == 1 && batch == 8192) row["speed"] = new JsonArray(Data.Obj(new { concurrency = 1, depth = 4096, recorded = 1, valid = 1, read_tokens_s = 999, write_tokens_s = 999 }));
            trials.Add(row);
        }
        var report = RecipeRepeats.Report(new(), trials);
        var four = report["groups"]!["4096"]!; var eight = report["groups"]!["8192"]!;
        if ((double)four["long_elapsed_s"]!["mean"]! != 110 || (double)four["long_elapsed_s"]!["sample_sd"]! != 10 ||
            (double)eight["long_elapsed_s"]!["mean"]! != 95 || (int)eight["long_elapsed_s"]!["n"]! != 2 ||
            (int)eight["long_correct"]! != 22 || (int)eight["long_planned"]! != 24 || report["paired_results"]!.AsArray().Count != 2 ||
            (int)eight["restore_elapsed_s"]!["n"]! != 0 || eight["restore_elapsed_s"]!["mean"] != null ||
            eight["speed"]!["c1-d4096"]!["read_tokens_s"]!["mean"] != null || RecipeRepeats.Stats([3])["sample_sd"] != null)
            throw new Exception("Paired report scored missing work or excluded a failed trial");
    }
}
