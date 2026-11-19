#:property PublishAot=false
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

try
{
    if (args.Length != 1) throw new ArgumentException("Expected a saved benchmark directory");
    string folder = args[0];
    var groups = JsonNode.Parse(File.ReadAllText(Path.Combine(folder, "summary.json")))!.AsArray();
    var tasks = File.ReadLines(Path.Combine(folder, "tasks.jsonl")).Select(line => JsonNode.Parse(line)!.AsObject()).ToArray();
    var results = groups.Select(node => node!.AsObject()).GroupBy(group => (int)group["concurrency"]!)
        .OrderBy(group => group.Key).Select(group => Summarize(folder, group, tasks)).ToArray();
    var report = new
    {
        protocol = "n1x-near-full-tools-v1",
        results,
        limits = "Synthetic tool selection and append-only continuations. Cold selection and warm phases have different generated work; their latency ratio is not a matched cache speedup. No cache-off comparison, displaced replay, or SSD restart qualification."
    };
    Console.WriteLine(JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static object Summarize(string folder, IGrouping<int, JsonObject> groups, JsonObject[] tasks)
{
    var rows = groups.SelectMany(g => g["sessions"]!.AsArray()).SelectMany(s => s!["requests"]!.AsArray())
        .Select(r => r!.AsObject()).ToArray();
    var names = groups.Select(g => (string)g["group"]!).ToHashSet();
    var appendedTimes = tasks.Where(t => names.Contains((string)t["group"]!) && (int)t["turn"]! > 0 && t.ContainsKey("elapsed_s"))
        .Select(t => (double)t["elapsed_s"]!).ToArray();
    var inputs = rows.Select(r => (int)r["rendered_input"]!).ToArray();
    double elapsed = groups.Sum(g => (double)g["elapsed_s"]!);
    int correct = groups.Sum(g => (int)g["correct_tasks"]!);
    var deltas = new Dictionary<string, double?>();
    foreach (string metric in new[] { "vllm:prefix_cache_hits_total", "vllm:external_prefix_cache_hits_total" })
    {
        double? total = 0;
        foreach (var group in groups)
        {
            string label = (string)group["group"]!;
            var before = Counter(folder, label, "before", metric);
            var after = Counter(folder, label, "after", metric);
            total += after >= before ? after - before : null;
        }
        deltas.Add(metric, total);
    }
    var phases = new Dictionary<string, object>();
    foreach (string phase in new[] { "cold-selection", "appended-selection", "tool-continuation" })
    {
        var samples = rows.Where(r => (string)r["phase"]! == phase).ToArray();
        if (samples.Length > 0) phases.Add(phase, Phase(samples));
    }
    return new
    {
        concurrency = groups.Key, correct_tasks = correct, planned_tasks = groups.Sum(g => (int)g["planned_tasks"]!),
        elapsed_s = elapsed, correct_tasks_s = correct / elapsed, preemptions = groups.Sum(g => (int)g["preemptions"]!),
        input_range = inputs.Length > 0 ? new[] { inputs.Min(), inputs.Max() } : null, phases,
        appended_task_mean_s = appendedTimes.Length > 0 ? appendedTimes.Average() : (double?)null,
        appended_task_timing_basis = "Selection plus continuation, including harness tokenization; first cold task excluded",
        cache_counter_deltas = deltas
    };
}

static object Phase(JsonObject[] samples)
{
    var outputs = samples.Select(r => (int)r["usage"]!["completion_tokens"]!).ToArray();
    var cache = samples.Select(r => r["usage"]!["prompt_tokens_details"]?["cached_tokens"] is JsonValue value &&
        value.TryGetValue<long>(out var n) ? n : (long?)null).ToArray();
    bool known = cache.All(n => n.HasValue);
    long prompts = samples.Sum(r => (long)r["usage"]!["prompt_tokens"]!);
    var decode = samples.Select(r => (double?)r["timing"]!["decode_s"]).ToArray();
    var sources = samples.Select(r => ((string?)r["timing"]!["pp_source"], (string?)r["timing"]!["decode_source"]))
        .Distinct().OrderBy(pair => pair.Item1 is null).ThenBy(pair => pair.Item1, StringComparer.Ordinal)
        .ThenBy(pair => pair.Item2 is null).ThenBy(pair => pair.Item2, StringComparer.Ordinal)
        .Select(pair => new[] { pair.Item1, pair.Item2 });
    return new
    {
        requests = samples.Length, mean_e2e_s = samples.Average(r => (double)r["timing"]!["e2e_s"]!),
        mean_client_ttft_s = CompleteMean(samples.Select(r => (double?)r["client_ttft_s"])),
        mean_pp_s = CompleteMean(samples.Select(r => (double?)r["timing"]!["pp_s"])),
        generated_range = new[] { outputs.Min(), outputs.Max() },
        cached_tokens = known ? cache.Sum() : null, cached_fraction = known ? cache.Sum() / (double)prompts : null,
        requests_with_cache = known ? cache.Count(n => n > 0) : (int?)null,
        write_tks = decode.All(n => n > 0) ? outputs.Sum(n => Math.Max(n - 1L, 0)) / decode.Sum() : null,
        timing_sources = sources
    };
}

static double? CompleteMean(IEnumerable<double?> values)
{
    var samples = values.ToArray();
    return samples.All(n => n.HasValue) ? samples.Average() : null;
}

static double? Counter(string folder, string label, string side, string metric)
{
    double? total = null;
    foreach (string line in File.ReadLines(Path.Combine(folder, $"{label}-{side}.prom")))
    {
        if (!line.StartsWith(metric + "{", StringComparison.Ordinal) && !line.StartsWith(metric + " ", StringComparison.Ordinal))
            continue;
        string token = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[^1];
        total = (total ?? 0) + double.Parse(token, CultureInfo.InvariantCulture);
    }
    return total;
}
