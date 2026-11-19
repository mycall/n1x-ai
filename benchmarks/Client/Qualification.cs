using System.Diagnostics;
using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace N1x.Benchmarks;

sealed partial class Qualification : IDisposable
{
    readonly string folder, url, salt = Guid.NewGuid().ToString("N");
    readonly bool cacheMetrics;
    JsonObject? sampling;
    readonly HttpClient http = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromHours(1) };
    readonly object logLock = new();
    public Qualification(string folder, string url, bool cacheMetrics)
    {
        this.folder = Directory.CreateDirectory(folder).FullName; this.url = url.TrimEnd('/'); this.cacheMetrics = cacheMetrics;
    }
    public void Dispose() => http.Dispose();
    void Save(string name, object value) => Data.Save(Path.Combine(folder, name), value);
    void Log(string name, JsonObject row) { lock (logLock) File.AppendAllText(Path.Combine(folder, name), row.ToJsonString() + "\n"); }
    static double Now() => (DateTime.UtcNow - DateTime.UnixEpoch).TotalSeconds;
    static JsonObject Message(string role, string content) => Data.Obj(new { role, content });
    static JsonObject Tool(string name, string description) => Data.Obj(new
    {
        type = "function",
        function = new
        {
            name,
            description,
            parameters = new { type = "object", properties = new { sku = new { type = "string" } }, required = new[] { "sku" }, additionalProperties = false }
        }
    });
    static JsonObject Assistant(JsonNode m)
    {
        var reply = Data.Obj(new { role = "assistant", content = m["content"], tool_calls = m["tool_calls"] });
        foreach (string field in new[] { "reasoning", "reasoning_content" }) if ((string?)m[field] is { Length: > 0 }) reply[field] = m[field]!.DeepClone();
        return reply;
    }
    static bool ValidCall(JsonNode choice, string name, string sku)
    {
        if ((string?)choice["finish_reason"] != "tool_calls" || choice["message"]?["tool_calls"] is not JsonArray { Count: 1 } calls ||
            (string?)calls[0]?["function"]?["name"] != name || (string?)calls[0]?["function"]?["arguments"] is not string args) return false;
        try { return JsonNode.DeepEquals(JsonNode.Parse(args), Data.Obj(new { sku })); } catch (JsonException) { return false; }
    }
    static JsonObject ToolResult(JsonNode call, object value) => Data.Obj(new { role = "tool", tool_call_id = (string)call["id"]!, content = JsonSerializer.Serialize(value) });
    static string Answer(JsonNode choice) => ((string?)choice["message"]?["content"] ?? "").Trim();
    static bool Stopped(JsonNode choice) => (string?)choice["finish_reason"] == "stop";
    async Task<JsonNode> Chat(JsonArray messages, string key, int tokens = 128, bool thinking = false, JsonArray? tools = null, string toolChoice = "auto")
    {
        var request = Data.Obj(new { model = "qwen/qwen38fn-best", messages, temperature = 0, max_tokens = tokens, cache_salt = key, chat_template_kwargs = new { enable_thinking = thinking } });
        if (sampling != null) request = Data.Merge(request, sampling);
        if (tools != null) { request["tools"] = tools.DeepClone(); request["tool_choice"] = toolChoice; }
        var timer = Stopwatch.StartNew(); double started = Now(); string? raw = null; int? status = null;
        JsonNode r;
        try
        {
            using var response = await http.PostAsJsonAsync(url + "/v1/chat/completions", request);
            raw = await response.Content.ReadAsStringAsync(); status = (int)response.StatusCode; response.EnsureSuccessStatusCode(); r = JsonNode.Parse(raw)!;
        }
        catch (Exception e)
        {
            var failure = Data.Obj(new { salt = key, started_unix_s = started, elapsed_s = timer.Elapsed.TotalSeconds, request, error = e.Message });
            if (status >= 400) { failure["status"] = status; failure["response_body"] = raw; }
            Log("errors.jsonl", failure); throw;
        }
        double elapsed = timer.Elapsed.TotalSeconds;
        Log("responses.jsonl", Data.Obj(new { salt = key, started_unix_s = started, elapsed_s = elapsed, timing = ModelClient.Timing(r["usage"], r["metrics"], elapsed, null), request, response = r }));
        return r["choices"]![0]!;
    }
    async Task<Dictionary<string, double>> Snapshot(string name)
    {
        var values = new Dictionary<string, double>();
        foreach (var (service, endpoint) in cacheMetrics ? new[] { ("vllm", url + "/metrics"), ("lmcache", "http://127.0.0.1:8080/metrics") } : [("vllm", url + "/metrics")])
        {
            string raw = await http.GetStringAsync(endpoint);
            await File.WriteAllTextAsync(Path.Combine(folder, $"{name}-{service}.prom"), raw);
            foreach (string line in raw.Split('\n'))
            {
                var m = Regex.Match(line.TrimEnd('\r'), @"^([^#\s{]+)(?:\{.*\})?\s+([\d.eE+-]+)$");
                if (m.Success) { string key = m.Groups[1].Value; values[key] = values.GetValueOrDefault(key) + double.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture); }
            }
        }
        return values;
    }
    static readonly string[] Counters = ["vllm:prefix_cache_hits_total", "vllm:external_prefix_cache_hits_total", "vllm:num_preemptions_total", "lmcache_mp_num_finished_retrieves_total", "lmcache_mp_l2_prefetch_load_completed_chunks_total"];
    internal static JsonObject RestoreSummary(Dictionary<string, double> before, Dictionary<string, double> after, int tokens, bool[] results, double elapsed)
    {
        var row = Data.Obj(new { prompt_tokens_each = tokens, correct = results.Count(x => x), elapsed_s = elapsed, qualified = false, initially_absent_counters = Counters.Where(k => !before.ContainsKey(k)) });
        var missing = Counters.Where((k, i) => !after.ContainsKey(k) || i < 3 && !before.ContainsKey(k)).ToArray();
        var delta = new Dictionary<string, double>(); string? error = null;
        if (missing.Length > 0) error = "Required restore counters missing: " + string.Join(", ", missing);
        else foreach (var k in Counters)
        {
            double a = before.GetValueOrDefault(k), b = after[k];
            if (!double.IsFinite(a) || !double.IsFinite(b) || a < 0 || b < a) { error = "Restore counters reset or contain invalid values"; break; }
            delta[k] = b - a;
        }
        if (error != null) { row["error"] = error; row["delta"] = null; return row; }
        row["delta"] = JsonSerializer.SerializeToNode(delta);
        row["qualified"] = results.Length == 2 && results.All(x => x) && delta[Counters[0]] == 0 && delta[Counters[1]] > 2 * (tokens - 4096) && delta[Counters[3]] >= 2 && delta[Counters[4]] > 0;
        return row;
    }
    async Task<int> Tokenize(JsonArray messages, bool thinking)
    {
        using var response = await http.PostAsJsonAsync(url + "/tokenize", new { model = "qwen/qwen38fn-best", messages, chat_template_kwargs = new { enable_thinking = thinking } });
        response.EnsureSuccessStatusCode(); return (int)JsonNode.Parse(await response.Content.ReadAsStringAsync())!["count"]!;
    }
    async Task<(JsonArray Messages, int Tokens)> Archive(int target)
    {
        int count = Math.Max(10, target / 18);
        for (int attempt = 0; attempt < 5; attempt++)
        {
            string[] lines = Enumerable.Range(0, count).Select(i => $"Record {i:D6}: warehouse item has batch {(i * 7919L + 137) % 999983:D6} and status archived.").ToArray();
            foreach (var (position, tree, code) in new[] { (.1, "cedar", "CEDAR-5831"), (.5, "maple", "MAPLE-9264"), (.9, "birch", "BIRCH-1748") })
                lines[(int)(count * position)] = $"SPECIAL RECORD: The {tree} access code is {code}.";
            JsonArray messages = [Message("user", "Read this archive and answer the question at its end.\n" + string.Join('\n', lines) + "\nQuestion: Return the cedar, maple, and birch access codes, in that order, and nothing else.")];
            int tokens = await Tokenize(messages, false);
            if (tokens >= target * .95 && tokens <= target) return (messages, tokens);
            count = Math.Max(10, (int)Math.Round(count * (target - 128.0) / tokens));
        }
        throw new InvalidDataException("Unable to size archive");
    }
    static bool Codes(JsonNode choice) => Stopped(choice) && Regex.IsMatch(Answer(choice), "CEDAR-5831.*MAPLE-9264.*BIRCH-1748", RegexOptions.Singleline);
    async Task<bool> Retrieve(JsonArray messages, string key) => Codes(await Chat(messages, key)) ? true : throw new InvalidDataException("Archive retrieval failed");

    async Task Restores()
    {
        var (messages, tokens) = await Archive(131000);
        string[] salts = [$"{salt}-restore-0", $"{salt}-restore-1"];
        foreach (var key in salts) await Retrieve(messages, key);
        var pressure = await Archive(261000);
        for (int i = 0; i < 3; i++) await Retrieve(pressure.Messages, $"{salt}-pressure-{i}");
        var before = await Snapshot("restore-before"); var timer = Stopwatch.StartNew();
        var results = await Task.WhenAll(salts.Select(key => Retrieve(messages, key)));
        var after = await Snapshot("restore-after");
        var summary = RestoreSummary(before, after, tokens, results, timer.Elapsed.TotalSeconds);
        Save("summary.json", summary); Console.WriteLine(summary.ToJsonString());
        if (!(bool)summary["qualified"]!) throw new InvalidDataException("Simultaneous external restores not established; inspect counters");
    }

    async Task Agents(Options options)
    {
        bool thinking = options.Has("--agent-thinking");
        int tokens = options.Int("--agent-output-tokens", thinking ? 1024 : 128), sessions = options.Int("--agent-sessions", 4), turns = options.Int("--agent-turns", 3);
        int[] points = options.Has("--agent-concurrency") ? options.Ints("--agent-concurrency", 1) : [1, 2, 4];
        if (tokens < 1 || sessions is < 1 or > 16 || turns is < 1 or > 100 || points.Any(c => c is < 1 or > 16)) throw new ArgumentException("Invalid agent workload");
        JsonArray tools = [Tool("lookup_inventory", "Look up stock by SKU.")];
        var rows = new List<JsonObject>();
        string filler = string.Join('\n', Enumerable.Range(0, 450).Select(i => $"Archive item {i:D6}: reference batch {i * 7919 % 999983:D6}; status archived."));
        foreach (int repeat in new[] { 0, 1 })
            foreach (int concurrency in repeat == 0 ? points.AsEnumerable() : points.Reverse())
            {
                var histories = new List<(int Number, JsonArray History, string Key)>();
                for (int n = 0; n < sessions; n++)
                {
                    JsonArray history = [Message("system","Use lookup_inventory whenever asked for inventory. Preserve the exact requested SKU. After its result, return only the requested CODE:COUNT format."),
                    Message("user",$"{filler}\nSession code is AGENT-{n:D4}. Remember it. Reply only READY.")];
                    string key = $"{salt}-agent-{repeat}-{concurrency}-{n}";
                    var first = await Chat(history, key, tokens, thinking, tools);
                    if (!Stopped(first) || Answer(first) != "READY") throw new InvalidDataException("Agent warmup failed");
                    history.Add(Message("assistant", (string)first["message"]!["content"]!)); histories.Add((n, history, key));
                }
                var before = await Snapshot($"agent-{repeat}-c{concurrency}-before"); var timer = Stopwatch.StartNew();
                using var slots = new SemaphoreSlim(concurrency);
                var results = await Task.WhenAll(histories.Select(async item =>
                {
                    await slots.WaitAsync();
                    try
                    {
                        var (n, history, key) = item; int correct = 0; var time = Stopwatch.StartNew();
                        for (int turn = 0; turn < turns; turn++)
                        {
                            string sku = $"AX-{n}-{turn}";
                            history.Add(Message("user", $"Look up inventory for SKU {sku}. Then return the session code and inventory count separated by a colon, with no other text."));
                            var choice = await Chat(history, key, tokens, thinking, tools);
                            if (!ValidCall(choice, "lookup_inventory", sku)) { history.Add(Message("assistant", (string?)choice["message"]?["content"] ?? "")); continue; }
                            history.Add(Assistant(choice["message"]!)); int count = 23 + n * 7 + turn;
                            history.Add(ToolResult(choice["message"]!["tool_calls"]![0]!, new { sku, count }));
                            var final = await Chat(history, key, tokens, thinking, tools, "none"); string answer = Answer(final); history.Add(Message("assistant", answer));
                            if (Stopped(final) && answer == $"AGENT-{n:D4}:{count}") correct++;
                        }
                        return new { session = n, correct_tasks = correct, planned_tasks = turns, elapsed_s = time.Elapsed.TotalSeconds };
                    }
                    finally { slots.Release(); }
                }));
                double elapsed = timer.Elapsed.TotalSeconds; var after = await Snapshot($"agent-{repeat}-c{concurrency}-after"); int passed = results.Sum(r => r.correct_tasks);
                var row = Data.Obj(new
                {
                    repeat,
                    concurrency,
                    sessions,
                    turns,
                    planned_tasks = sessions * turns,
                    correct_tasks = passed,
                    elapsed_s = elapsed,
                    correct_tasks_s = passed / elapsed,
                    preemptions = after.GetValueOrDefault(Counters[2]) - before.GetValueOrDefault(Counters[2]),
                    thinking,
                    max_output_tokens = tokens,
                    session_results = results
                });
                rows.Add(row); Save("summary.json", rows); Console.WriteLine(row.ToJsonString());
            }
    }
}
