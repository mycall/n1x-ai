using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

sealed class LongTools : IDisposable
{
    readonly string dir, url, id = Guid.NewGuid().ToString("N");
    readonly int target, repeats, sessions, turns;
    readonly int[] points;
    readonly JsonObject host;
    readonly ModelClient client;
    readonly object sync = new();
    readonly List<JsonObject> groups = [];
    public LongTools(string[] args, bool replay)
    {
        var o = new Options(args, [], ["--concurrency"], ["--host", "--url", "--out", "--target", "--repeats", "--sessions", "--turns"]);
        dir = o.Get("--out"); url = o.Get("--url", "http://127.0.0.1:8000"); target = o.Int("--target", 250000); repeats = o.Int("--repeats", 2);
        sessions = replay ? 6 : o.Int("--sessions", 2); turns = o.Int("--turns", 3); points = o.Has("--concurrency") ? o.Ints("--concurrency", 1) : [1, 2];
        if (target is < 1024 or > 250000 || repeats < 1 || replay && repeats > 10 || turns < 1 || sessions < points.Max() ||
            points.Any(c => c is not (1 or 2 or 4)) || points.Distinct().Count() != points.Length) throw new ArgumentException("Invalid tool workload");
        host = Data.Read(o.Get("--host")); client = new ModelClient(url, 3600);
    }
    public void Dispose() => client.Dispose();
    void Save(string name, object data) => Data.Save(Path.Combine(dir, name), data);
    void Log(string name, JsonObject row) => LongContext.Append(Path.Combine(dir, name), row, sync);
    static string Question(int n, int turn) => $"Look up {(turn % 2 == 0 ? "inventory" : "price")} for SKU AX-{n}-{turn}. Use the appropriate tool. After its result return only SESSION_CODE:VALUE:BIRCH_CODE, using the archive codes and the returned count or price_cents. No other text.";
    static JsonObject Payload(int n, int chars)
    {
        string f = LongContext.Fill("Archive reference: routine warehouse records are indexed and stored for later review.\n", chars);
        int a = chars / 10, b = chars * 9 / 10; string archive = f[..a] + $"\nAUTHORITATIVE session code: SESSION-{n:D4}.\n" + f[a..b] + $"\nAUTHORITATIVE birch code: BIRCH-{1748 + n}.\n" + f[b..];
        return Data.Obj(new
        {
            model = "qwen/qwen38fn-best",
            temperature = 0,
            seed = 42,
            max_tokens = 8192,
            stream = true,
            stream_options = new { include_usage = true },
            tools = new[] { LongContext.Tool("lookup_inventory", "Return current inventory count for a SKU."), LongContext.Tool("lookup_price", "Return current price in cents for a SKU.") },
            tool_choice = "auto",
            chat_template_kwargs = LongContext.Template(),
            messages = new[]{LongContext.Message("system","Use the requested lookup tool; never guess its result. Preserve the requested SKU exactly. Use authoritative archive codes and tool results. Follow the requested output format exactly."),
            LongContext.Message("user",archive+"\n"+Question(n,0))}
        });
    }
    async Task<int> Count(JsonObject body)
    {
        for (int attempt = 0; ; attempt++)
        {
            try { return await LongContext.Count(client, body); }
            catch (Exception e) when (attempt < 2 && (e is HttpRequestException { StatusCode: null } or TaskCanceledException or IOException))
            { Console.WriteLine($"Tokenization transport retry {attempt + 1}: {e.Message}"); await Task.Delay(1000 * (attempt + 1)); }
        }
    }
    async Task<(JsonObject Body, int Tokens)> Calibrate(int n)
    {
        int lo = 0, hi = target * 12;
        while (lo <= hi)
        {
            int mid = lo + (hi - lo) / 2; var body = Payload(n, mid); int tokens = await Count(body);
            if (Math.Abs(tokens - target) <= 8) return (body, tokens); if (tokens < target) lo = mid + 1; else hi = mid - 1;
        }
        throw new InvalidDataException("Cannot calibrate initial tool prompt");
    }
    internal static bool Valid(JsonObject r, string name, string sku)
    {
        if ((bool?)r["stream_done"] != true || (string?)r["finish_reason"] != "tool_calls" || r["tool_calls"] is not JsonArray { Count: 1 } list) return false;
        var call = list[0]; if (string.IsNullOrEmpty((string?)call?["id"]) || (string?)call?["type"] != "function" || (string?)call?["function"]?["name"] != name) return false;
        try { return JsonNode.DeepEquals(JsonNode.Parse((string?)call?["function"]?["arguments"] ?? ""), Data.Obj(new { sku })); } catch (JsonException) { return false; }
    }
    internal static JsonObject Assistant(JsonObject r)
    {
        var m = Data.Obj(new { role = "assistant", content = string.IsNullOrEmpty((string?)r["content"]) ? null : (string?)r["content"] });
        if (!string.IsNullOrEmpty((string?)r["reasoning"])) m["reasoning"] = r["reasoning"]!.DeepClone();
        if (r["tool_calls"] is JsonArray { Count: > 0 }) m["tool_calls"] = r["tool_calls"]!.DeepClone(); return m;
    }
    static void Continue(JsonObject body, JsonObject result, string sku, string field, int value)
    {
        var m = body["messages"]!.AsArray(); m.Add(Assistant(result));
        m.Add(Data.Obj(new { role = "tool", tool_call_id = result["tool_calls"]![0]!["id"], content = $"{{\"sku\": \"{sku}\", \"{field}\": {value}}}" }));
    }
    static bool Passed(JsonObject r, string expected) => (bool?)r["stream_done"] == true && (string?)r["finish_reason"] == "stop" &&
        (r["tool_calls"]?.AsArray().Count ?? 0) == 0 && ((string?)r["content"])?.Trim() == expected;
    static bool Empty(JsonObject r) => string.IsNullOrWhiteSpace((string?)r["content"]) && (r["tool_calls"]?.AsArray().Count ?? 0) == 0;
    async Task<JsonObject> Generate(JsonObject body, JsonObject tags, List<JsonObject>? requests = null)
    {
        int count = await Count(body); if (count + 8192 > 262144) throw new InvalidDataException("Insufficient output reserve");
        double started = LongContext.Unix; var r = await client.Generate(body); bool match = Data.Integer(r["usage"]?["prompt_tokens"]) == count;
        if (tags.ContainsKey("diagnostic")) r["rendered_input_matches"] = match;
        var row = Data.Merge(tags, r, Data.Obj(new { rendered_input = count, started_unix_s = started, request = body }));
        Log("requests.jsonl", row); row.Remove("request"); requests?.Add(row);
        if (!match) throw new InvalidDataException("Rendered input differs from response usage");
        return r;
    }
    async Task<(Dictionary<string, double> Values, string Raw)> Snapshot(string name)
    {
        var m = await LongContext.Metrics(client); File.WriteAllText(Path.Combine(dir, name + ".prom"), m.Raw); return m;
    }
    public async Task Run(bool replay)
    {
        Data.NewFolder(dir); await client.Get("/health");
        var prepared = new List<JsonObject>(); var calibration = new List<object>();
        var meta = Data.Obj(new { run_id = id, target, repeats, host, source_hashes = LongContext.Hashes() });
        if (replay) meta = Data.Merge(meta, Data.Obj(new { protocol = "n1x-displaced-tools-v1", concurrency = 2, targets = 2, pressure_histories = 4, output_allowance = 8192 }));
        else meta = Data.Merge(meta, Data.Obj(new
        {
            protocol = "n1x-near-full-tools-v1",
            started_utc = DateTime.UtcNow,
            context_limit = 262144,
            output_allowance = 8192,
            concurrency = points,
            sessions,
            turns,
            thinking = true,
            reasoning_effort = "xhigh",
            temperature = 0,
            seed = 42,
            models = await client.Get("/v1/models")
        }));
        Save("run.json", meta);
        for (int n = 0; n < sessions; n++) { var (body, count) = await Calibrate(n); prepared.Add(body); calibration.Add(new { session = n, tokens = count }); }
        if (!replay) Save("calibration.json", calibration);
        for (int repeat = 0; repeat < repeats; repeat++)
        {
            if (replay) { await Replay(prepared, repeat); continue; }
            foreach (int c in repeat % 2 == 0 ? points.AsEnumerable() : points.Reverse()) await Group(prepared, repeat, c);
        }
        if (groups.Any(g => (int)g["correct_tasks"]! != (int)g["planned_tasks"]!)) throw new InvalidDataException("Incomplete qualification: inspect first scores and errors");
    }
    async Task Group(List<JsonObject> prepared, int repeat, int concurrency)
    {
        string label = $"r{repeat}-c{concurrency}"; var before = await Snapshot(label + "-before");
        async Task<JsonObject> Session(int n)
        {
            var body = prepared[n].DeepClone().AsObject(); body["cache_salt"] = $"{id}-{label}-s{n}"; var requests = new List<JsonObject>(); int correct = 0;
            try
            {
                for (int turn = 0; turn < turns; turn++)
                {
                    var timer = Stopwatch.StartNew(); if (turn > 0) body["messages"]!.AsArray().Add(LongContext.Message("user", Question(n, turn)));
                    Task<JsonObject> Ask(string phase, bool diagnostic = false) => Generate(body, Data.Obj(new { group = label, session = n, turn, phase, diagnostic }), diagnostic ? null : requests);
                    string name = turn % 2 == 0 ? "lookup_inventory" : "lookup_price", sku = $"AX-{n}-{turn}";
                    var selected = await Ask(turn == 0 ? "cold-selection" : "appended-selection");
                    if (!Valid(selected, name, sku)) { Log("tasks.jsonl", Data.Obj(new { group = label, session = n, turn, correct = false, error = "invalid-tool-call" })); break; }
                    int value = 23 + n * 7 + turn; Continue(body, selected, sku, turn % 2 == 0 ? "count" : "price_cents", value);
                    var final = await Ask("tool-continuation"); string expected = $"SESSION-{n:D4}:{value}:BIRCH-{1748 + n}";
                    bool passed = Passed(final, expected); if (passed) correct++;
                    Log("tasks.jsonl", Data.Obj(new { group = label, session = n, turn, correct = passed, expected, actual = final["content"], elapsed_s = timer.Elapsed.TotalSeconds }));
                    if (Empty(final)) await Ask("empty-final-retry", true); if (!passed) break; body["messages"]!.AsArray().Add(Assistant(final));
                }
            }
            catch (Exception e) { Log("errors.jsonl", Data.Obj(new { group = label, session = n, error = e.ToString() })); }
            return Data.Obj(new { session = n, correct_tasks = correct, planned_tasks = turns, requests });
        }
        using var stop = new CancellationTokenSource();
        async Task Monitor()
        {
            using var observer = new ModelClient(url, 5);
            while (!stop.IsCancellationRequested)
            {
                try
                {
                    var m = await LongContext.Metrics(observer); JsonObject? memory = null;
                    try { memory = Data.Read(Path.Combine(Directory.GetCurrentDirectory(), ".state/n1x-qwen38fn-best/host.json")); } catch (Exception e) when (e is IOException or JsonException) { }
                    Log("scheduler.jsonl", Data.Obj(new { group = label, unix_s = LongContext.Unix, values = m.Values, host_memory = memory }));
                }
                catch (Exception e) { Log("scheduler.jsonl", Data.Obj(new { group = label, unix_s = LongContext.Unix, error = e.Message })); }
                try { await Task.Delay(2000, stop.Token); } catch (OperationCanceledException) { break; }
            }
        }
        var timer = Stopwatch.StartNew(); var watcher = Monitor(); JsonObject[] results;
        try { results = await LongContext.ParallelMap(Enumerable.Range(0, sessions), concurrency, Session); } finally { stop.Cancel(); await watcher; }
        double elapsed = timer.Elapsed.TotalSeconds; int count = results.Sum(r => (int)r["correct_tasks"]!);
        var group = Data.Obj(new { group = label, concurrency, repeat, elapsed_s = elapsed, correct_tasks = count, planned_tasks = sessions * turns, sessions = results });
        Save("partial-group.json", Data.Merge(group, Data.Obj(new { telemetry_complete = false })));
        var after = await Snapshot(label + "-after");
        group["correct_tasks_s"] = count / elapsed; const string k = "vllm:num_preemptions_total"; group["preemptions"] = after.Values.GetValueOrDefault(k) - before.Values.GetValueOrDefault(k);
        groups.Add(group); Save("summary.json", groups);
    }
    static double? Counter(string raw, string name)
    {
        double? value = null; foreach (string line in raw.Split('\n')) if (line.StartsWith(name + "{", StringComparison.Ordinal) || line.StartsWith(name + " ", StringComparison.Ordinal))
            value = (value ?? 0) + double.Parse(line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[^1], CultureInfo.InvariantCulture); return value;
    }
    async Task Replay(List<JsonObject> prepared, int repeat)
    {
        var bodies = prepared.Select((b, i) => Data.Merge(b, Data.Obj(new { cache_salt = $"{id}-r{repeat}-s{i}" }))).ToArray();
        Task<JsonObject> Ask(int n, string phase, JsonObject? body = null) => Generate(body ?? bodies[n], Data.Obj(new { phase, repeat, session = n }));
        const string nativeKey = "vllm:prefix_cache_hits_total", externalKey = "vllm:external_prefix_cache_hits_total";
        var residency = new List<bool>();
        for (int n = 0; n < 6; n++)
        {
            string phase = n < 2 ? "prime" : "pressure", sku = $"AX-{n}-0"; var result = await Ask(n, phase);
            if (!Valid(result, "lookup_inventory", sku) || Data.Integer(result["timing"]?["cached_tokens"]) != 0) throw new InvalidDataException($"Invalid cold {phase} first tool call");
            if (n >= 2) continue; string label = $"r{repeat}-prime{n}";
            var pre = await Snapshot(label + "-before"); var warm = await Ask(n, "prime-residency-check"); var post = await Snapshot(label + "-after");
            bool resident = Counter(post.Raw, nativeKey) > Counter(pre.Raw, nativeKey) && Data.Integer(warm["timing"]?["cached_tokens"]) > 0; residency.Add(resident);
            if (!Valid(warm, "lookup_inventory", sku) || target >= 8192 && !resident) throw new InvalidDataException("Prime residency check failed");
        }
        string wave = $"r{repeat}-selection"; var before = await Snapshot(wave + "-before"); var timer = Stopwatch.StartNew();
        var selected = await Task.WhenAll(Enumerable.Range(0, 2).Select(n => Ask(n, "replay-selection"))); double selection = timer.Elapsed.TotalSeconds;
        var after = await Snapshot(wave + "-after");
        var tasks = await Task.WhenAll(Enumerable.Range(0, 2).Select(async n =>
        {
            string sku = $"AX-{n}-0"; if (!Valid(selected[n], "lookup_inventory", sku)) return Data.Obj(new { session = n, correct = false, error = "invalid-replay-tool-call" });
            int value = 23 + n * 7; var body = bodies[n].DeepClone().AsObject(); Continue(body, selected[n], sku, "count", value);
            var final = await Ask(n, "replay-continuation", body); string expected = $"SESSION-{n:D4}:{value}:BIRCH-{1748 + n}"; bool correct = Passed(final, expected);
            if (Empty(final)) await Ask(n, "empty-final-diagnostic", body); return Data.Obj(new { session = n, correct, expected, actual = final["content"] });
        }));
        var deltas = new Dictionary<string, double?>();
        foreach (string key in new[] { nativeKey, externalKey, "vllm:num_preemptions_total" }) { var a = Counter(before.Raw, key); var b = Counter(after.Raw, key); deltas[key] = b >= a ? b - a : null; }
        var cached = selected.Select(r => Data.Integer(r["timing"]?["cached_tokens"])).ToArray(); bool displaced = residency.All(x => x) && deltas[nativeKey] == 0;
        groups.Add(Data.Obj(new
        {
            repeat,
            concurrency = 2,
            planned_tasks = 2,
            correct_tasks = tasks.Count(t => (bool)t["correct"]!),
            elapsed_s = timer.Elapsed.TotalSeconds,
            selection_elapsed_s = selection,
            tasks,
            selection_cached_tokens = cached,
            cache_counter_deltas = deltas,
            prime_native_residency = residency,
            native_displacement_verified = displaced,
            external_restore_verified = displaced && deltas[externalKey] > 0 && cached.All(n => n > 0),
            selection_results = selected
        })); Save("summary.json", groups);
    }
}
