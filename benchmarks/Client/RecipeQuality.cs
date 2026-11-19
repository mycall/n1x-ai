using System.Diagnostics;
using System.Globalization;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class RecipeQuality
{
    public static async Task Run(string[] args)
    {
        var o = new Options(args, [], ["--variants", "--phases"], ["--out", "--url", "--quality-depth", "--seed"]);
        string dir = o.Get("--out"), url = o.Get("--url", "http://127.0.0.1:8000"); int depth = o.Int("--quality-depth", 32768), seed = o.Int("--seed", 42);
        string[] variants = o.Has("--variants") ? o.List("--variants") : ["xhigh-t1", "medium-t1", "xhigh-t06", "medium-t06"], phases = o.Has("--phases") ? o.List("--phases") : ["agents", "recovery"];
        if (variants.Any(v => v is not ("xhigh-t1" or "medium-t1" or "xhigh-t06" or "medium-t06")) || phases.Any(p => p is not ("agents" or "recovery" or "quality"))) throw new ArgumentException("Unknown variant or phase");
        static double Temperature(string v) => v.EndsWith("t06") ? .6 : 1;
        Data.NewFolder(dir); using var client = new ModelClient(url, 3600); await client.Get("/health");
        Data.Save(Path.Combine(dir, "settings.json"), new
        {
            utc = DateTime.UtcNow,
            variants = variants.Distinct().ToDictionary(v => v, v => new object[] { v.Split('-')[0], Temperature(v) }),
            phases,
            quality_depth = depth,
            output_tokens = 8192,
            top_p = .95,
            top_k = 20,
            seed,
            presence_penalty = 0,
            model = await client.Get("/v1/models"),
            source_hashes = LongContext.Hashes(),
            note = "Fixed-seed parameter comparison. First scores are retained. Empty final retries are diagnostic only."
        });
        var prepared = new List<JsonObject>(); var failures = new List<object>();
        if (phases.Contains("quality"))
        {
            foreach (int i in new[] { 0, 2, 4, 6 }) prepared.Add(await Capacity.Calibrate(client, i, depth + 8192 + 8, 8192));
            Data.Save(Path.Combine(dir, "prepared-requests.json"), prepared);
        }
        foreach (string v in variants) foreach (string phase in phases)
        {
            string effort = v.Split('-')[0], folder = Path.Combine(dir, v, phase); double temperature = Temperature(v);
            await client.Get("/health");
            try
            {
                if (phase == "quality") await Quality(folder, client, prepared, effort, temperature, seed);
                else
                {
                    List<string> opts = ["--out", folder, "--url", url, "--no-lmcache-metrics", "--recipe-effort", effort, "--recipe-temperature", temperature.ToString(CultureInfo.InvariantCulture), "--recipe-seed", seed.ToString()];
                    if (phase == "agents") opts.AddRange(["--phase", "agents", "--agent-thinking", "--agent-output-tokens", "8192", "--agent-sessions", "2", "--agent-turns", "2", "--agent-concurrency", "1", "2"]);
                    try { await Qualification.Run(phase == "agents" ? "agent" : "recovery", opts.ToArray()); }
                    finally
                    {
                        string file = Path.Combine(folder, "summary.json");
                        if (phase == "recovery" && File.Exists(file)) Data.Save(file, Data.Merge(Data.Read(file), Data.Obj(new { max_output_tokens = 8192, reasoning_effort = effort, temperature, seed })));
                    }
                }
            }
            catch (Exception e) { failures.Add(new { variant = v, phase, error = e.Message }); Data.Save(Path.Combine(dir, "failures.json"), failures); }
            string raw = Path.Combine(folder, "responses.jsonl"); if (!File.Exists(raw)) continue;
            foreach (string line in File.ReadLines(raw))
            {
                var row = JsonNode.Parse(line)!; var m = row["response"]!["choices"]![0]!["message"]!;
                if ((m["tool_calls"]?.AsArray().Count ?? 0) > 0 || !string.IsNullOrWhiteSpace((string?)m["content"])) continue;
                var r = Data.Obj(new { first_score_unchanged = true, request = row["request"] });
                try { r["response"] = await client.Get("/v1/chat/completions", row["request"]); } catch (Exception e) { r["error"] = e.Message; }
                File.AppendAllText(Path.Combine(folder, "empty-final-diagnostics.jsonl"), r.ToJsonString() + "\n");
            }
        }
        Data.Save(Path.Combine(dir, "completed.json"), new { utc = DateTime.UtcNow, failures });
    }
    static async Task Quality(string dir, ModelClient client, List<JsonObject> prepared, string effort, double temperature, int seed)
    {
        var summaries = new List<JsonObject>();
        foreach (int concurrency in new[] { 1, 2 })
        {
            string group = Path.Combine(dir, $"c{concurrency}"); Data.NewFolder(group);
            File.WriteAllText(Path.Combine(group, "before.prom"), (await LongContext.Metrics(client)).Raw);
            var timer = Stopwatch.StartNew();
            var rows = await LongContext.ParallelMap(prepared, concurrency, async t =>
            {
                var body = Data.Merge(t["payload"]!.AsObject(), Data.Obj(new { temperature, top_p = .95, top_k = 20, presence_penalty = 0, seed, max_tokens = 8192, cache_salt = Guid.NewGuid().ToString("N"), chat_template_kwargs = LongContext.Template(effort) }));
                int count = await LongContext.Count(client, body); if (count + 8192 > 262144) throw new InvalidDataException("Input does not reserve output space");
                var time = Stopwatch.StartNew(); JsonObject row;
                try
                {
                    var result = await client.Generate(body); bool match = Data.Integer(result["usage"]?["prompt_tokens"]) == count;
                    row = Data.Merge(result, Data.Obj(new { task_id = t["id"], kind = t["kind"], expected = t["expected"], request = body, input_tokens = count, rendered_input_matches = match, correct = match && Capacity.Score(result, t["expected"]!) }));
                }
                catch (Exception e) { row = Data.Obj(new { task_id = t["id"], correct = false, error = e.Message, request = body }); }
                row["elapsed_s"] = time.Elapsed.TotalSeconds; Data.Save(Path.Combine(group, t["id"] + ".json"), row); return row;
            });
            double elapsed = timer.Elapsed.TotalSeconds;
            File.WriteAllText(Path.Combine(group, "after.prom"), (await LongContext.Metrics(client)).Raw);
            summaries.Add(Data.Obj(new { concurrency, correct = rows.Count(r => (bool?)r["correct"] == true), planned = prepared.Count, elapsed_s = elapsed, max_output_tokens = 8192 }));
            Data.Save(Path.Combine(dir, "summary.json"), summaries);
            foreach (var r in rows.Where(r => (bool?)r["stream_done"] == true && string.IsNullOrWhiteSpace((string?)r["content"])))
            {
                var result = await client.Generate(r["request"]!.AsObject()); Data.Save(Path.Combine(group, r["task_id"] + "-diagnostic.json"), new { first_score_unchanged = true, recovered = Capacity.Score(result, r["expected"]!), result });
            }
        }
        if (summaries.Any(r => (int)r["correct"]! != (int)r["planned"]!)) throw new InvalidDataException("Archive quality first-attempt failures");
    }
}
