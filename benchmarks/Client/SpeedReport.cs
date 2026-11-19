using System.Globalization;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class SpeedReport
{
    public static JsonObject Load(string directory)
    {
        var run = Data.Read(Path.Combine(directory, "run.json"));
        string raw = Path.Combine(directory, "requests.jsonl");
        var rows = File.Exists(raw) ? File.ReadLines(raw).Where(l => !string.IsNullOrWhiteSpace(l)).Select(l => JsonNode.Parse(l)!.AsObject()).ToArray() : [];
        var summary = Summarize(run, rows);
        summary["artifact_directory"] = Path.GetFullPath(directory);
        return summary;
    }

    public static JsonObject Summarize(JsonObject run, IReadOnlyList<JsonObject> rows)
    {
        var s = run["settings"]!;
        if ((string?)s["protocol"] != "n1x-speed-v1") throw new InvalidDataException("Unsupported speed protocol");
        var cells = new List<object>();
        foreach (string mode in s["modes"]!.DeserializeArray<string>())
            foreach (int c in s["concurrency"]!.DeserializeArray<int>())
                foreach (int depth in s["depths"]!.DeserializeArray<int>())
                {
                    var point = rows.Where(r => (string?)r["mode"] == mode && (int)r["concurrency"]! == c && (int)r["depth"]! == depth).ToArray();
                    var measured = point.Where(r => (string?)r["phase"] == "measured").ToArray();
                    var valid = measured.Where(r => (string?)r["status"] == "ok").ToArray();
                    int repeats = (int)s["repeats"]!, expected = c * repeats;
                    var identities = valid.Select(r => ((int)r["repeat"]!, (int)r["stream"]!)).ToHashSet();
                    var sources = valid.GroupBy(r => (Pp: (string?)r["timing"]!["pp_source"], Decode: (string?)r["timing"]!["decode_source"])).ToArray();
                    var skipped = point.Where(r => (string?)r["status"] is "skipped" or "not-applicable").Select(r => (string)r["reason"]!).ToArray();
                    bool complete = valid.Length == expected && measured.Length == expected && sources.Length == 1 &&
                        !string.IsNullOrEmpty(sources[0].Key.Pp) && !string.IsNullOrEmpty(sources[0].Key.Decode) &&
                        identities.Count == expected && identities.All(id => id.Item1 >= 0 && id.Item1 < repeats && id.Item2 >= 0 && id.Item2 < c);
                    int[]? Range(Func<JsonObject, int> field) => valid.Length == 0 ? null : [valid.Min(field), valid.Max(field)];
                    double? read = complete ? valid.Sum(r => (long)r["read_tokens"]!) / valid.Sum(r => (double)r["timing"]!["pp_s"]!) : null;
                    double? write = complete ? valid.Sum(r => (long)r["usage"]!["completion_tokens"]! - 1) / valid.Sum(r => (double)r["timing"]!["decode_s"]!) : null;
                    cells.Add(new
                    {
                        mode,
                        concurrency = c,
                        depth,
                        status = complete ? "complete" : mode == "cold" && depth == 0 ? "not-applicable" : skipped.Length > 0 && measured.Length == 0 ? "skipped" : "incomplete",
                        expected_requests = expected,
                        recorded_requests = measured.Length,
                        valid_requests = valid.Length,
                        timing_sources = sources.Select(g => new { pp = g.Key.Pp, decode = g.Key.Decode, requests = g.Count() }),
                        timing_source = sources.Length == 1 ? new[] { sources[0].Key.Pp, sources[0].Key.Decode } : null,
                        read_write_tks = new[] { read, write },
                        input_tokens = Range(r => (int)r["usage"]!["prompt_tokens"]!),
                        history_tokens = Range(r => (int)r["history_tokens"]!),
                        read_tokens = Range(r => (int)r["read_tokens"]!),
                        completion_tokens = Range(r => (int)r["usage"]!["completion_tokens"]!),
                        cached_tokens = Range(r => (int)r["usage"]!["prompt_tokens_details"]!["cached_tokens"]!),
                        cached_prompt_fraction = valid.Length == 0 ? (double?)null : valid.Sum(r => (long)r["usage"]!["prompt_tokens_details"]!["cached_tokens"]!) / (double)valid.Sum(r => (long)r["usage"]!["prompt_tokens"]!),
                        mean_client_ttft_s = valid.Length == 0 ? (double?)null : valid.Average(r => (double)r["client_ttft_s"]!),
                        mean_e2e_s = valid.Length == 0 ? (double?)null : valid.Average(r => (double)r["timing"]!["e2e_s"]!),
                        notes = skipped.Concat(measured.SelectMany(r => r["errors"]?.DeserializeArray<string>() ?? []))
                            .Concat(measured.Where(r => r.ContainsKey("error")).Select(r => (string)r["error"]!)).Distinct().Order(StringComparer.Ordinal)
                    });
                }
        return Data.Obj(new
        {
            schema_version = 1,
            protocol = s["protocol"],
            run_id = run["run_id"],
            profile = s["profile"],
            status = run["status"],
            settings = s,
            metadata = run,
            cells
        });
    }

    static T[] DeserializeArray<T>(this JsonNode node) => System.Text.Json.JsonSerializer.Deserialize<T[]>(node.ToJsonString())!;
    static string Esc(string value) => value.Replace("|", "\\|").ReplaceLineEndings(" ");
    static string Num(int value) => value.ToString("N0", CultureInfo.InvariantCulture);
    static string Range(JsonNode? n) => n == null ? "—" : (int)n[0]! == (int)n[1]! ? Num((int)n[0]!) : $"{Num((int)n[0]!)}–{Num((int)n[1]!)}";
    record Cell(JsonObject Run, JsonNode Point);
    static string Label(JsonObject run) => $"{Esc((string)run["profile"]!)} / `{((string)run["run_id"]!)[..Math.Min(8, ((string)run["run_id"]!).Length)]}`";

    public static void Write(IReadOnlyList<JsonObject> runs, string directory)
    {
        var lines = new List<string> { "# Speed by context depth", "",
            "Each cell is **(read, write) tk/s**. Read = summed workload tokens / summed PP durations. Write = summed (completion tokens − 1) / summed decode durations. Concurrent request intervals overlap.", "",
            "Cold depth is the full rendered prompt with zero cache hits. Incremental depth is the primed history; read tokens count the actual extension. The fixed generation includes reasoning.", "" };
        var groups = runs.SelectMany(run => run["cells"]!.AsArray().Select(cell => new Cell(run, cell!))).GroupBy(c =>
        {
            var s = c.Run["settings"]!;
            return new
            {
                mode = (string)c.Point["mode"]!,
                protocol = (string)s["protocol"]!,
                output = (int)s["output_tokens"]!,
                extension = (int)s["extension_tokens"]!,
                thinking = (bool)s["thinking"]!,
                effort = s.AsObject().ContainsKey("reasoning_effort") ? (string?)s["reasoning_effort"] : "unspecified",
                repeats = (int)s["repeats"]!,
                tolerance = (int)s["tolerance"]!,
                seed = (int)s["seed"]!,
                recipe = (string)s["prompt_recipe_sha256"]!,
                policy = (string)s["timing_policy"]!,
                generator = (string?)s["generator_sha256"]
            };
        });
        foreach (var group in groups)
        {
            var k = group.Key;
            string[] sources = group.Where(c => (string)c.Point["status"]! == "complete").Select(c => c.Point["timing_source"]!.ToJsonString()).Distinct().Order(StringComparer.Ordinal).DefaultIfEmpty("[\"unavailable\",\"unavailable\"]").ToArray();
            foreach (string key in sources)
            {
                var source = JsonNode.Parse(key)!;
                lines.AddRange([$"## {k.mode} · thinking {(k.thinking ? "on" : "off")}", "", $"Reasoning effort: **{(k.thinking ? k.effort : "disabled")}**.", "",
                    $"Protocol `{k.protocol}`; output **{k.output}**; repeats **{k.repeats}**; extension **{k.extension}** (incremental only); token calibration tolerance ±{k.tolerance}.", "",
                    $"PP source: `{source[0]}`. Decode source: `{source[1]}`.", ""]);
                int[] depths = group.Select(c => (int)c.Point["depth"]!).Distinct().Order().ToArray();
                lines.Add("| Client concurrency | Profile / run | Server slots | " + string.Join(" | ", depths.Select(Num)) + " |");
                lines.Add("| --- | --- | ---: | " + string.Join(" | ", depths.Select(_ => "---:")) + " |");
                foreach (int concurrency in group.Select(c => (int)c.Point["concurrency"]!).Distinct().Order())
                    foreach (var run in group.GroupBy(c => c.Run))
                    {
                        var values = new List<string>();
                        foreach (int depth in depths)
                        {
                            var p = run.FirstOrDefault(c => (int)c.Point["concurrency"]! == concurrency && (int)c.Point["depth"]! == depth)?.Point;
                            string status = (string?)p?["status"] ?? "missing";
                            values.Add(status != "complete" ? "— " + status : p!["timing_source"]!.ToJsonString() != key ? "— different timing source" :
                                "(" + string.Join(", ", p["read_write_tks"]!.DeserializeArray<double>().Select(n => n.ToString("N2", CultureInfo.InvariantCulture))) + ")");
                        }
                        lines.Add($"| **C{concurrency}** | {Label(run.Key)} | {run.Key["metadata"]?["host"]?["config"]?["MaxSequences"]?.ToString() ?? "—"} | " + string.Join(" | ", values) + " |");
                    }
                lines.AddRange(["", "| Client concurrency | Profile / run | Depth | Actual history | Actual input | Read numerator | Generated | Cached tokens | Valid / planned | Mean client TTFT / e2e (s) | Status |", "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |"]);
                foreach (var cell in group.OrderBy(c => runs.ToList().IndexOf(c.Run)).ThenBy(c => (int)c.Point["concurrency"]!).ThenBy(c => (int)c.Point["depth"]!))
                {
                    var p = cell.Point;
                    if ((string)p["status"]! == "complete" && p["timing_source"]!.ToJsonString() != key) continue;
                    string latency = p["mean_client_ttft_s"] == null ? "—" : FormattableString.Invariant($"{(double)p["mean_client_ttft_s"]!:F3} / {(double)p["mean_e2e_s"]!:F3}");
                    string notes = string.Join("; ", p["notes"]!.DeserializeArray<string>());
                    string ranges = string.Join(" | ", new[] { "history_tokens", "input_tokens", "read_tokens", "completion_tokens", "cached_tokens" }.Select(name => Range(p[name])));
                    lines.Add($"| {p["concurrency"]} | {Label(cell.Run)} | {Num((int)p["depth"]!)} | {ranges} | {p["valid_requests"]}/{p["expected_requests"]} | {latency} | {Esc(p["status"] + (notes.Length == 0 ? "" : ": " + notes))} |");
                }
                lines.Add("");
            }
        }
        lines.AddRange(["## Run metadata", "", "| Profile | Run | Status | Context limit | Artifacts |", "| --- | --- | --- | ---: | --- |"]);
        foreach (var run in runs) lines.Add($"| {Esc((string)run["profile"]!)} | `{run["run_id"]}` | {run["status"]} | {Num((int)run["settings"]!["context_limit"]!)} | {Esc((string?)run["artifact_directory"] ?? "this run")} |");
        File.WriteAllText(Path.Combine(directory, "comparison.md"), string.Join('\n', lines) + "\n");
        Data.Save(Path.Combine(directory, "comparison.json"), new { schema_version = 1, runs });
    }
}
