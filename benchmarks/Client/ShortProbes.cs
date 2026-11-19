using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class ShortProbes
{
    static double Clock() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
    public static async Task Run(string mode, string[] args)
    {
        var o = new Options(args, ["--thinking", "--no-thinking"], [], mode == "scheduler" ? ["--out", "--url", "--concurrency", "--output-tokens"] : ["--out", "--url"]);
        string folder = mode == "scheduler" ? o.Get("--out", "/results") : o.Get("--out");
        Directory.CreateDirectory(folder);
        string url = o.Get("--url", "http://127.0.0.1:8000");
        using var client = new ModelClient(url, mode == "scheduler" ? 1800 : 600);
        using var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri(url), Timeout = TimeSpan.FromSeconds(15) };
        await client.Get("/health");
        bool thinking = !o.Has("--no-thinking");
        string salt = Guid.NewGuid().ToString("N");
        JsonObject Body(string prompt, string id, int tokens) => Data.Obj(new
        {
            model = "qwen/qwen38fn-best",
            messages = new[] { new { role = "user", content = prompt } },
            max_tokens = tokens,
            temperature = 0,
            stream = true,
            stream_options = new { include_usage = true },
            cache_salt = id,
            chat_template_kwargs = new { enable_thinking = thinking }
        });
        if (mode == "speculation")
        {
            var tasks = new Dictionary<string, string>
            {
                ["json"] = "Return only a JSON array of objects for integers 1 through 20. Each object must have keys n, square, cube with the integer and its square and cube. No markdown.",
                ["code"] = "Write a complete Python implementation of a bounded LRU cache using collections.OrderedDict, with get and put methods, type hints, and a small usage example. Explain how eviction works.",
                ["explain"] = "Explain how a database B-tree index speeds up queries. Cover equality, range scans, composite indexes, and the cost of writes. Use concrete examples in about 300 words."
            };
            async Task Metrics(string side) => await File.WriteAllBytesAsync(Path.Combine(folder, side + ".prom"), await http.GetByteArrayAsync("/metrics"));
            await Metrics("before");
            var rows = new List<JsonObject>();
            foreach (var (task, prompt) in tasks)
                for (int repeat = 0; repeat < 2; repeat++)
                {
                    var request = Body(prompt, $"compare-{salt}-{task}", thinking ? 2048 : 512);
                    var r = await client.Generate(request);
                    var row = Data.Obj(new
                    {
                        task,
                        repeat,
                        thinking,
                        ttft = r["client_ttft_s"],
                        elapsed = r["timing"]!["e2e_s"],
                        decode_tps = r["timing"]!["write_tks"],
                        timing = r["timing"],
                        metrics = r["metrics"],
                        usage = r["usage"],
                        finish = r["finish_reason"],
                        text = r["content"],
                        reasoning = r["reasoning"],
                        request
                    });
                    if (task == "json")
                    {
                        var expected = JsonSerializer.SerializeToNode(Enumerable.Range(1, 20).Select(n => new { n, square = n * n, cube = n * n * n }));
                        try { row["correct"] = JsonNode.DeepEquals(JsonNode.Parse((string)r["content"]!), expected); }
                        catch (JsonException) { row["correct"] = false; }
                    }
                    rows.Add(row); Data.Save(Path.Combine(folder, "results.json"), rows);
                    if (row["decode_tps"] == null || task == "json" && ((bool?)row["correct"] != true || (string?)row["finish"] != "stop"))
                        throw new InvalidDataException("Incomplete or incorrect generation; inspect results.json");
                    Console.WriteLine($"{salt} {task} {repeat} (read, write) tk/s {r["timing"]!["read_write_tks"]}");
                }
            await Metrics("after"); return;
        }
        int concurrency = o.Int("--concurrency", 4), output = o.Int("--output-tokens", 256);
        if (concurrency < 1 || output < 1) throw new ArgumentException("Positive concurrency and output required");
        var samples = new List<JsonObject>(); var rowsByEnd = new List<JsonObject>();
        using var stop = new CancellationTokenSource();
        async Task Monitor()
        {
            do
            {
                var row = Data.Obj(new { time = Clock() });
                foreach (string line in (await http.GetStringAsync("/metrics")).Split('\n'))
                    foreach (string name in new[] { "num_requests_running", "num_requests_waiting", "num_preemptions_total" })
                        if (line.StartsWith("vllm:" + name + "{", StringComparison.Ordinal)) row[name] = double.Parse(line[(line.LastIndexOf(' ') + 1)..], CultureInfo.InvariantCulture);
                samples.Add(row);
                try { await Task.Delay(100, stop.Token); } catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            } while (!stop.IsCancellationRequested);
        }
        async Task Ask(int id)
        {
            string prompt = $"Independent session {id}.\n" + string.Concat(Enumerable.Repeat("The service accepts requests, checks inputs, and returns a response. ", 320)) + "\nWrite a detailed fictional story about building a helpful robot.";
            var request = Body(prompt, salt, output); request["ignore_eos"] = true;
            double start = Clock(); var r = await client.Generate(request);
            var row = Data.Obj(new { id, start, first = start + (double?)r["client_ttft_s"], end = Clock(), metrics = r["metrics"], timing = r["timing"], usage = r["usage"], content = r["content"] });
            lock (rowsByEnd) rowsByEnd.Add(row);
        }
        var monitor = Monitor();
        try { await Task.WhenAll(Enumerable.Range(0, concurrency).Select(Ask)); }
        finally { stop.Cancel(); await monitor; }
        var events = rowsByEnd.SelectMany(r => new[] { ((double)r["first"]!, 1), ((double)r["end"]!, -1) }).OrderBy(e => e.Item1).ThenBy(e => e.Item2).ToArray();
        int peak = 0, active = 0; double previous = events[0].Item1;
        var overlap = new Dictionary<int, double>();
        foreach (var (stamp, delta) in events) { overlap[active] = overlap.GetValueOrDefault(active) + (stamp - previous); active += delta; peak = Math.Max(peak, active); previous = stamp; }
        double duration = rowsByEnd.Max(r => (double)r["end"]!) - rowsByEnd.Min(r => (double)r["start"]!);
        double Rate(string key) => rowsByEnd.Sum(r => (long)r["usage"]![key]!) / duration;
        var result = Data.Obj(new
        {
            concurrency,
            thinking,
            output_tokens = output,
            duration_s = duration,
            aggregate_input_output_tks = new[] { Rate("prompt_tokens"), Rate("completion_tokens") },
            aggregate_rate_basis = "whole-run wall time; not per-request PP/decode",
            output_tokens_s = Rate("completion_tokens"),
            max_running = samples.Max(s => (double?)s["num_requests_running"] ?? 0),
            max_overlapping_decode_intervals = peak,
            generation_overlap_seconds = overlap,
            mean_ttft_s = rowsByEnd.Average(r => (double)r["first"]! - (double)r["start"]!),
            mean_completion_s = rowsByEnd.Average(r => (double)r["end"]! - (double)r["start"]!),
            rows = rowsByEnd,
            samples
        });
        Data.Save(Path.Combine(folder, "probe.json"), result); result.Remove("rows"); result.Remove("samples"); Console.WriteLine(result.ToJsonString());
    }
}
