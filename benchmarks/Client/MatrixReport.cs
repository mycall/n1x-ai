using System.Globalization;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class MatrixReport
{
    internal static JsonObject Summarize(string folder, bool incomplete)
    {
        var m = Data.Read(Path.Combine(folder, "manifest.json"));
        int[] contexts = m["contexts"]!.AsArray().Select(v => (int)v!).ToArray(), points = m["concurrency"]!.AsArray().Select(v => (int)v!).ToArray();
        var waves = Directory.GetFiles(folder, "*-receipt.json").Order(StringComparer.Ordinal).Select(Data.Read).Where(r => (bool?)r["warmup"] != true).ToArray();
        var expected = (from repeat in Enumerable.Range(1, (int)m["repeats"]!) from c in points from n in contexts select (repeat, c, n)).ToHashSet();
        var actual = waves.Select(w => ((int)w["repeat"]!, (int)w["concurrency"]!, (int)w["target_input"]!)).ToHashSet();
        bool complete = actual.SetEquals(expected);
        if (!incomplete && (!complete || actual.Count != waves.Length)) throw new InvalidDataException($"Incomplete/duplicate matrix: {actual.Count}/{expected.Count} waves");
        foreach (var w in waves)
        {
            if ((bool?)w["valid"] != true) throw new InvalidDataException("Invalid wave in measured matrix");
            if (w["responses"]!.AsArray().Count != (int)w["concurrency"]!) throw new InvalidDataException("Response count does not match concurrency");
            foreach (var r in w["responses"]!.AsArray())
            {
                var u = r!["usage"]; int target = (int)w["target_input"]!, count = (int?)u?["prompt_tokens"] ?? 0;
                if ((bool?)r["done"] != true || (int?)r["status"] != 200 || (string?)r["finish_reason"] != "length" || (int?)u?["completion_tokens"] != 512 ||
                    count < target - 4 || count > target || (int?)u?["prompt_tokens_details"]?["cached_tokens"] != 0 ||
                    Data.Positive(r["metrics"]?["time_to_first_token_ms"]) == null || Data.Positive(r["metrics"]?["generation_time_ms"]) == null)
                    throw new InvalidDataException("Invalid response in matrix receipt");
            }
        }
        static double[] Range(IEnumerable<double> values) { var a = values.ToArray(); return [a.Min(), a.Max()]; }
        static double? Counter(string path, string key)
        {
            double? sum = null; foreach (string line in File.ReadLines(path)) if (line.StartsWith(key + " ", StringComparison.Ordinal) || line.StartsWith(key + "{", StringComparison.Ordinal))
                sum = (sum ?? 0) + double.Parse(line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[^1], CultureInfo.InvariantCulture);
            return sum;
        }
        var cells = new List<JsonObject>();
        foreach (int n in contexts) foreach (int c in points)
        {
            var group = waves.Where(w => (int)w["concurrency"]! == c && (int)w["target_input"]! == n).ToArray();
            if (group.Length == 0) continue;
            var measures = group.Select(w =>
            {
                string name = (string)w["name"]!; var rows = w["responses"]!.AsArray(); var common = Data.Read(Path.Combine(folder, name + "-vllm.json"));
                var prompts = rows.Select(r => (int)r!["usage"]!["prompt_tokens"]!).ToArray();
                double pp = rows.Sum(r => (double)r!["metrics"]!["time_to_first_token_ms"]!) / 1000, decode = rows.Sum(r => (double)r!["metrics"]!["generation_time_ms"]!) / 1000;
                var ttfts = common["ttfts"]!.AsArray().Select(t => (double)t!).ToArray();
                double duration = (double)common["duration"]!;
                string before = Path.Combine(folder, name + "-before.prom"), after = Path.Combine(folder, name + "-after.prom");
                double? Delta(string key) => File.Exists(before) && File.Exists(after) ? Counter(after, key) - Counter(before, key) : null;
                double? success = Delta("vllm:request_success_total"); if (success != null && success != c) throw new InvalidDataException("Unexpected server completion count; unrelated work or counter reset");
                return new
                {
                    name,
                    prompts,
                    pp,
                    decode,
                    ttfts,
                    duration,
                    success,
                    preemptions = Delta("vllm:num_preemptions_total"),
                    queue = rows.Sum(r => (double)r!["metrics"]!["queue_time_ms"]!) / 1000,
                    latencies = common["latencies"]!.AsArray().Select(t => (double)t!),
                    tpot = (double)common["mean_tpot_ms"]!
                };
            }).ToArray();
            var inputs = measures.SelectMany(v => v.prompts).ToArray(); int count = inputs.Length; long tokens = inputs.Sum(i => (long)i);
            double duration = measures.Sum(v => v.duration), pp = measures.Sum(v => v.pp), decode = measures.Sum(v => v.decode);
            var ttfts = measures.SelectMany(v => v.ttfts).ToArray();
            cells.Add(Data.Obj(new
            {
                context = n,
                concurrency = c,
                waves = group.Length,
                requests = count,
                prompt_tokens_range = new[] { inputs.Min(), inputs.Max() },
                read_tks = tokens / pp,
                write_tks = count * 511 / decode,
                read_wave_range = Range(measures.Select(v => v.prompts.Sum() / v.pp)),
                write_wave_range = Range(measures.Select(v => 511 * c / v.decode)),
                mean_pp_s = pp / count,
                mean_decode_s = decode / count,
                mean_queue_s = measures.Sum(v => v.queue) / count,
                mean_client_ttft_s = ttfts.Average(),
                client_read_tks = tokens / ttfts.Sum(),
                client_read_wave_range = Range(measures.Select(v => v.prompts.Sum() / v.ttfts.Sum())),
                mean_client_e2e_s = measures.SelectMany(v => v.latencies).Average(),
                common_mean_tpot_ms = measures.Average(v => v.tpot),
                common_input_throughput = tokens / duration,
                common_output_throughput = count * 512 / duration,
                common_input_wave_range = Range(measures.Select(v => v.prompts.Sum() / v.duration)),
                common_output_wave_range = Range(measures.Select(v => 512 * c / v.duration)),
                common_duration_s = duration,
                cached_tokens = 0,
                wave_names = measures.Select(v => v.name),
                preemptions = measures.All(v => v.preemptions != null) ? measures.Sum(v => v.preemptions) : null,
                observed_server_completions = measures.All(v => v.success != null) ? measures.Sum(v => v.success) : null
            }));
        }
        return Data.Obj(new { protocol = m["protocol"], generated_utc = DateTime.UtcNow, manifest = m, complete, measured_waves = waves.Length, measured_requests = cells.Sum(c => (int)c["requests"]!), cells });
    }
    public static void Run(string[] args)
    {
        if (args.Length == 0) throw new ArgumentException("Expected FOLDER --output FILE");
        var options = new Options(args[1..], ["--allow-incomplete"], [], ["--output"]); string path = Path.GetFullPath(options.Get("--output"));
        var data = Summarize(args[0], options.Has("--allow-incomplete")); Directory.CreateDirectory(Path.GetDirectoryName(path)!); Data.Save(Path.ChangeExtension(path, ".json"), data);
        var lines = new List<string> { "# qwen38fn-best read/write speed matrix", "", $"{data["measured_waves"]} measured bursts; {data["measured_requests"]} requests. Complete: {data["complete"]}.", "" };
        foreach (var (key, title, precision) in new[]{("client_read_tks","Read including waiting (tokens/s per request)",1),("read_tks","Read excluding queue time (tokens/s per request)",1),
            ("write_tks","Write (tokens/s per request)",2),("common_output_throughput","Aggregate output throughput (tokens/s across the complete burst)",2),
            ("mean_client_ttft_s","Mean client time to first token (seconds, including queue)",2),("mean_queue_s","Mean server queue time (seconds)",2)})
        {
            var contexts = data["manifest"]!["contexts"]!.AsArray();
            lines.AddRange([title, "", "| Concurrency | " + string.Join(" | ", contexts.Select(n => n!.ToString())) + " |", "| --- | " + string.Join(" | ", contexts.Select(_ => "---:")) + " |"]);
            foreach (var c in data["manifest"]!["concurrency"]!.AsArray())
            {
                var cells = data["cells"]!.AsArray(); string Value(JsonNode? n)
                {
                    var cell = cells.FirstOrDefault(x => (int)x!["concurrency"]! == (int)c! && (int)x["context"]! == (int)n!);
                    return cell == null ? "pending" : ((double)cell[key]!).ToString("N" + precision, CultureInfo.InvariantCulture);
                }
                lines.Add($"| C{c} | " + string.Join(" | ", contexts.Select(Value)) + " |");
            }
            lines.Add("");
        }
        File.WriteAllText(Path.ChangeExtension(path, ".md"), string.Join('\n', lines));
        using var reader = new StreamReader(typeof(MatrixReport).Assembly.GetManifestResourceStream("matrix.html")!);
        File.WriteAllText(Path.ChangeExtension(path, ".html"), reader.ReadToEnd().Replace("__DATA__", data.ToJsonString()));
    }
}
