using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class LongContext
{
    public static JsonObject Template(string effort = "xhigh") => Data.Obj(new { enable_thinking = true, reasoning_effort = effort });
    public static JsonObject Message(string role, string content) => Data.Obj(new { role, content });
    public static JsonObject Tool(string name, string description) => Data.Obj(new
    {
        type = "function",
        function = new
        {
            name,
            description,
            parameters = new { type = "object", properties = new { sku = new { type = "string" } }, required = new[] { "sku" }, additionalProperties = false }
        }
    });
    public static string Fill(string unit, int characters) => string.Concat(Enumerable.Repeat(unit, characters / unit.Length + 1))[..characters];
    public static double Unix => (DateTime.UtcNow - DateTime.UnixEpoch).TotalSeconds;
    public static async Task<int> Count(ModelClient client, JsonObject payload)
    {
        var copy = new JsonObject();
        foreach (string key in new[] { "model", "messages", "tools", "chat_template_kwargs" }) if (payload.ContainsKey(key)) copy[key] = payload[key]?.DeepClone();
        foreach (var msg in copy["messages"]!.AsArray())
        {
            var m = msg!.AsObject(); if (!m.TryGetPropertyValue("reasoning_content", out var legacy)) continue;
            m.Remove("reasoning_content"); if (legacy != null && m["reasoning"] == null) m["reasoning"] = legacy;
        }
        copy["add_generation_prompt"] = true; var response = await client.Get("/tokenize", copy);
        return Data.Integer(response?["count"]) ?? throw new InvalidDataException("Server tokenizer did not return a rendered token count");
    }
    public static async Task<(Dictionary<string, double> Values, string Raw)> Metrics(ModelClient client)
    {
        string raw = await client.Text("/metrics"); var values = new Dictionary<string, double>();
        foreach (string line in raw.Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries); if (parts.Length < 2) continue;
            string name = parts[0].Split('{')[0];
            if (name is not ("vllm:num_requests_running" or "vllm:num_requests_waiting" or "vllm:num_preemptions_total")) continue;
            if (double.TryParse(parts[^1], CultureInfo.InvariantCulture, out var n) && double.IsFinite(n)) values[name] = values.GetValueOrDefault(name) + n;
        }
        return (values, raw);
    }
    public static async Task<T[]> ParallelMap<TIn, T>(IEnumerable<TIn> items, int concurrency, Func<TIn, Task<T>> action)
    {
        using var slots = new SemaphoreSlim(concurrency);
        return await Task.WhenAll(items.Select(async item => { await slots.WaitAsync(); try { return await action(item); } finally { slots.Release(); } }));
    }
    public static Dictionary<string, string> Hashes() => typeof(LongContext).Assembly.GetManifestResourceNames().Where(n => n.StartsWith("source/")).ToDictionary(n => n[7..], n =>
    {
        using var stream = typeof(LongContext).Assembly.GetManifestResourceStream(n)!;
        return Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(stream));
    });
    public static void Append(string path, JsonObject record, object sync) { lock (sync) File.AppendAllText(path, record.ToJsonString() + "\n"); }
}

static class Capacity
{
    public static JsonObject Sample(int i, int characters)
    {
        string cedar = $"CEDAR-{5831 + i}", maple = $"MAPLE-{9264 + i}", birch = $"BIRCH-{1748 + i}"; int units = 7 + i, price = 23 + i, fee = 11 + i;
        string f = LongContext.Fill($"Archive {i:D2}: routine reference record; requests are validated, indexed, processed and stored.\n", characters);
        int a = characters / 10, b = characters / 2, c = characters * 9 / 10;
        string archive = f[..a] + $"\nAUTHORITATIVE cedar code: {cedar}; units: {units}.\n" + f[a..b] + $"\nAUTHORITATIVE maple code: {maple}; unit_price_cents: {price}.\n" +
            f[b..c] + $"\nAUTHORITATIVE birch code: {birch}; shipping_cents: {fee}.\n" + f[c..];
        string kind, question; object expected;
        switch (i % 8)
        {
            case 0: case 1: kind = "needle-retrieval"; question = "Return only the cedar, maple and birch codes in that order, separated by a single colon."; expected = $"{cedar}:{maple}:{birch}"; break;
            case 2: case 3: kind = "retrieval-arithmetic-json"; question = "Return only a JSON object with total_cents = units * unit_price_cents + shipping_cents, and birch = the birch code. No extra keys."; expected = new { total_cents = units * price + fee, birch }; break;
            case 4: case 5: kind = "structured-retrieval"; question = "Return only a JSON object with keys cedar, maple, birch, units, using their authoritative archive values. No extra keys."; expected = new { cedar, maple, birch, units }; break;
            default: kind = "tool-result-continuation"; question = $"Look up inventory for AX-{i}. After the tool result, return only CASE-{i}:COUNT:BIRCH_CODE using that count and the archive birch code."; expected = $"CASE-{i}:{100 + i}:{birch}"; break;
        }
        JsonArray messages = [LongContext.Message("system","Use only the authoritative archive facts and provided tool results. Follow the requested output format exactly."),
            LongContext.Message("user",archive+"\nQUESTION: "+question)];
        var payload = Data.Obj(new { model = "qwen/qwen38fn-best", temperature = 0, seed = 42, chat_template_kwargs = LongContext.Template(), stream = true, stream_options = new { include_usage = true } });
        if (expected is not string) payload["response_format"] = Data.Obj(new { type = "json_object" });
        if (kind == "tool-result-continuation")
        {
            string id = $"capacity-inventory-{i}", sku = $"AX-{i}";
            payload["tools"] = new JsonArray(LongContext.Tool("lookup_inventory", "Get inventory count.")); payload["tool_choice"] = "auto";
            messages.Add(Data.Obj(new
            {
                role = "assistant",
                content = (string?)null,
                reasoning_content = $"I need the inventory count for AX-{i} before giving the requested final answer.",
                tool_calls = new[] { new { id, type = "function", function = new { name = "lookup_inventory", arguments = $"{{\"sku\": \"{sku}\"}}" } } }
            }));
            messages.Add(Data.Obj(new { role = "tool", tool_call_id = id, content = $"{{\"sku\": \"{sku}\", \"count\": {100 + i}}}" }));
        }
        payload["messages"] = messages;
        return Data.Obj(new { id = $"near-limit-{i}", kind, expected, payload });
    }
    public static async Task<JsonObject> Calibrate(ModelClient client, int index, int limit, int output)
    {
        int target = limit - output - 8, low = 0, high = target * 12;
        while (low <= high)
        {
            int mid = low + (high - low) / 2; var row = Sample(index, mid); int count = await LongContext.Count(client, row["payload"]!.AsObject());
            if (Math.Abs(count - target) <= 8 && count + output <= limit) { row["input_tokens"] = count; return row; }
            if (count < target) low = mid + 1; else high = mid - 1;
        }
        throw new InvalidDataException($"Cannot calibrate task {index} near the context limit");
    }
    public static bool Score(JsonObject result, JsonNode expected)
    {
        if ((bool?)result["stream_done"] != true || (string?)result["finish_reason"] != "stop") return false;
        string text = ((string?)result["content"] ?? "").Trim();
        if (expected is JsonObject) { try { return JsonNode.DeepEquals(JsonNode.Parse(text), expected); } catch (JsonException) { return false; } }
        return text.Length > 0 && text == (string?)expected;
    }

    internal static JsonObject Summary(JsonObject[] rows, int c, double elapsed, Dictionary<string, double> before, Dictionary<string, double> after, List<JsonObject> samples, int planned)
    {
        var done = rows.Where(r => r["timing"] is JsonObject { Count: > 0 } && Data.Integer(r["usage"]?["prompt_tokens"]) != null && Data.Integer(r["usage"]?["completion_tokens"]) != null).ToArray();
        bool cold = done.Length == planned && done.All(r => Data.Integer(r["usage"]?["prompt_tokens_details"]?["cached_tokens"]) == 0);
        var sources = done.Select(r => ((string?)r["timing"]!["pp_source"], (string?)r["timing"]!["decode_source"])).Distinct()
            .OrderBy(p => p.Item1 is null).ThenBy(p => p.Item1, StringComparer.Ordinal).ThenBy(p => p.Item2 is null).ThenBy(p => p.Item2, StringComparer.Ordinal).Select(p => new[] { p.Item1, p.Item2 }).ToArray();
        bool valid = cold && sources.Length == 1 && done.All(r => (bool?)r["rendered_input_matches"] == true && Data.Positive(r["timing"]!["pp_s"]) != null && Data.Positive(r["timing"]!["decode_s"]) != null);
        int[] input = done.Select(r => (int)r["usage"]!["prompt_tokens"]!).ToArray(), output = done.Select(r => (int)r["usage"]!["completion_tokens"]!).ToArray();
        const string key = "vllm:num_preemptions_total";
        int correct = rows.Count(r => (bool?)r["correct"] == true);
        double? Peak(string name) => samples.Max(s => (double?)s["values"]?[name]);
        return Data.Obj(new
        {
            client_concurrency = c,
            first_attempt_correct = correct,
            planned,
            completed_streams = rows.Count(r => (bool?)r["stream_done"] == true),
            elapsed_s = elapsed,
            cold_cache_evidence_passed = cold,
            correct_tasks_s = correct / elapsed,
            read_write_tks = valid ? new double?[] { input.Sum() / done.Sum(r => (double)r["timing"]!["pp_s"]!), output.Sum(v => Math.Max(0, v - 1)) / done.Sum(r => (double)r["timing"]!["decode_s"]!) } : [null, null],
            timing_sources = sources,
            input_tokens_range = input.Length == 0 ? null : new[] { input.Min(), input.Max() },
            generated_tokens_range = output.Length == 0 ? null : new[] { output.Min(), output.Max() },
            aggregate_input_output_tks = done.Length == planned ? new double?[] { input.Sum() / elapsed, output.Sum() / elapsed } : [null, null],
            aggregate_basis = "Whole measured batch wall time; distinct from request-phase read/write rates",
            preemptions = before.TryGetValue(key, out var pre) && after.TryGetValue(key, out var post) && post >= pre ? post - pre : (double?)null,
            max_observed_running_requests = Peak("vllm:num_requests_running"),
            max_observed_waiting_requests = Peak("vllm:num_requests_waiting"),
            running_gauge_limit = "Scheduled request count does not establish eight fully resident maximum-length KV histories",
            mean_client_ttft_s = done.Length > 0 && done.All(r => r["client_ttft_s"] != null) ? done.Average(r => (double)r["client_ttft_s"]!) : (double?)null,
            mean_e2e_s = done.Length > 0 ? done.Average(r => (double)r["timing"]!["e2e_s"]!) : (double?)null
        });
    }
    public static async Task Run(string[] args)
    {
        var o = new Options(args, [], ["--concurrency"], ["--out", "--profile", "--url", "--context-limit", "--output-tokens", "--timeout", "--repeats", "--prepared-from", "--host-record"]);
        string dir = o.Get("--out"), url = o.Get("--url", "http://127.0.0.1:8000"), id = Guid.NewGuid().ToString("N"); int limit = o.Int("--context-limit", 262144), output = o.Int("--output-tokens", 8192), repeats = o.Int("--repeats", 3);
        int[] points = o.Has("--concurrency") ? o.Ints("--concurrency", 1) : [1, 8]; double timeout = double.Parse(o.Get("--timeout", "1800"), CultureInfo.InvariantCulture);
        if (limit <= output + 1024 || output < 128 || timeout <= 0 || repeats is < 1 or > 10 || points.Any(c => c is not (1 or 6 or 8)) || points.Length != points.Distinct().Count()) throw new ArgumentException("Invalid capacity workload");
        var settings = Data.Obj(new
        {
            protocol = "n1x-near-limit-quality-v2",
            run_id = id,
            profile = o.Get("--profile"),
            tokenizer_preprocessing = "Match pinned chat reasoning_content-to-reasoning normalization; generation history unchanged",
            context_limit = limit,
            output_tokens = output,
            thinking = true,
            reasoning_effort = "xhigh",
            concurrency = points,
            tasks_per_repeat = 8,
            repeats,
            tasks = 8 * repeats,
            source_hashes = LongContext.Hashes(),
            requested_input_target = limit - output - 8,
            first_scores_only = true,
            no_generation_warmups = true,
            scope = "Two needle, two retrieval/arithmetic JSON, two structured retrieval and two provided-tool-result continuation tasks. Not a general reasoning/coding benchmark or full end-to-end tool loop."
        });
        Data.NewFolder(dir); using var client = new ModelClient(url, timeout); using var observer = new ModelClient(url, 5);
        if (o.Has("--host-record")) settings["host"] = Data.Read(o.Get("--host-record"));
        await client.Get("/health"); settings["models"] = await client.Get("/v1/models"); Data.Save(Path.Combine(dir, "settings.json"), settings);
        List<JsonObject> prepared = [];
        if (o.Has("--prepared-from"))
        {
            string old = o.Get("--prepared-from"); var prior = Data.Read(Path.Combine(old, "settings.json"));
            foreach (string key in new[] { "protocol", "context_limit", "output_tokens", "repeats", "tasks", "reasoning_effort" })
                if (!JsonNode.DeepEquals(prior[key], settings[key])) throw new InvalidDataException("Prepared comparison uses a different context/output/task/effort plan");
            string path = Path.Combine(old, "prepared-requests.json");
            prepared = JsonNode.Parse(File.ReadAllText(path))!.AsArray().Select(n => n!.AsObject()).ToList();
            if (prepared.Count != 8 * repeats) throw new InvalidDataException("Prepared task count mismatch");
            foreach (var r in prepared) if (await LongContext.Count(client, r["payload"]!.AsObject()) != (int)r["input_tokens"]!) throw new InvalidDataException("Prepared rendered token count mismatch");
            settings["prepared_source"] = Data.Obj(new { directory = Path.GetFullPath(old), sha256 = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path))) });
            Data.Save(Path.Combine(dir, "settings.json"), settings);
        }
        else for (int i = 0; i < 8 * repeats; i++) prepared.Add(await Calibrate(client, i, limit, output));
        Data.Save(Path.Combine(dir, "prepared-requests.json"), prepared);
        List<JsonObject> groups = []; object sync = new();
        foreach (int c in points)
        {
            string group = Directory.CreateDirectory(Path.Combine(dir, $"c{c}")).FullName; var samples = new List<JsonObject>();
            var before = await LongContext.Metrics(observer); File.WriteAllText(Path.Combine(group, "before.prom"), before.Raw);
            using var stop = new CancellationTokenSource();
            async Task Monitor()
            {
                while (!stop.IsCancellationRequested)
                {
                    try { var m = await LongContext.Metrics(observer); samples.Add(Data.Obj(new { utc = DateTime.UtcNow, values = m.Values })); }
                    catch (Exception e) { samples.Add(Data.Obj(new { utc = DateTime.UtcNow, error = e.Message })); }
                    try { await Task.Delay(1000, stop.Token); } catch (OperationCanceledException) { break; }
                }
            }
            var monitor = Monitor(); var timer = Stopwatch.StartNew(); JsonObject[] rows; double elapsed;
            try
            {
                rows = await LongContext.ParallelMap(prepared, c, async task =>
                {
                    var body = Data.Merge(task["payload"]!.AsObject(), Data.Obj(new { max_tokens = output, cache_salt = $"{id}-c{c}-{task["id"]}" }));
                    double started = LongContext.Unix; JsonObject row;
                    try
                    {
                        var r = await client.Generate(body); bool match = Data.Integer(r["usage"]?["prompt_tokens"]) == (int)task["input_tokens"]!;
                        row = Data.Merge(r, Data.Obj(new
                        {
                            task_id = task["id"],
                            kind = task["kind"],
                            expected = task["expected"],
                            started_unix_s = started,
                            expected_input_tokens = task["input_tokens"],
                            rendered_input_matches = match,
                            correct = match && Score(r, task["expected"]!),
                            request = body
                        }));
                    }
                    catch (Exception e) { row = Data.Obj(new { task_id = task["id"], kind = task["kind"], correct = false, error = e.Message, request = body, started_unix_s = started }); }
                    LongContext.Append(Path.Combine(group, "responses.jsonl"), row, sync); return row;
                }); elapsed = timer.Elapsed.TotalSeconds;
            }
            finally { stop.Cancel(); await monitor; Data.Save(Path.Combine(group, "metrics-samples.json"), samples); }
            var after = await LongContext.Metrics(observer); File.WriteAllText(Path.Combine(group, "after.prom"), after.Raw);
            var summary = Summary(rows, c, elapsed, before.Values, after.Values, samples, prepared.Count); groups.Add(summary); Data.Save(Path.Combine(group, "summary.json"), summary);
            bool complete = groups.Count == points.Length;
            Data.Save(Path.Combine(dir, "summary.json"), new { settings, groups, complete, quality_passed = complete && groups.All(g => (int)g["first_attempt_correct"]! == (int)g["planned"]!) });
            foreach (var row in rows.Where(r => (bool?)r["stream_done"] == true && string.IsNullOrWhiteSpace((string?)r["content"])))
            {
                JsonObject diagnostic;
                try { var r = await client.Generate(row["request"]!.AsObject()); diagnostic = Data.Obj(new { task_id = row["task_id"], recovered = Score(r, row["expected"]!), first_score_unchanged = true, result = r }); }
                catch (Exception e) { diagnostic = Data.Obj(new { task_id = row["task_id"], recovered = false, error = e.Message, first_score_unchanged = true }); }
                LongContext.Append(Path.Combine(group, "empty-final-diagnostics.jsonl"), diagnostic, sync);
            }
            Console.WriteLine(summary.ToJsonString());
        }
        var lines = new List<string>{$"# Near-{limit:N0}-token context at "+string.Join(" / ",points.Select(n=>"C"+n)),"",$"Thinking enabled, explicit xhigh; {output:N0} output tokens reserved. Each group runs {repeats} eight-task sets with fresh cache salts.","",
            "| Client C | Input tokens | Generated tokens | First-score quality | Phase (read, write) tk/s | Batch seconds | Preemptions | Peak running / waiting |","| ---: | --- | --- | ---: | --- | ---: | ---: | --- |"};
        foreach (var g in groups) lines.Add($"| {g["client_concurrency"]} | {g["input_tokens_range"]?.ToJsonString()} | {g["generated_tokens_range"]?.ToJsonString()} | {g["first_attempt_correct"]}/{g["planned"]} | {g["read_write_tks"]?.ToJsonString()} | {(double)g["elapsed_s"]!:F2} | {g["preemptions"]} | {g["max_observed_running_requests"]} / {g["max_observed_waiting_requests"]} |");
        File.WriteAllText(Path.Combine(dir, "comparison.md"), string.Join('\n', lines) + "\n");
    }
}
