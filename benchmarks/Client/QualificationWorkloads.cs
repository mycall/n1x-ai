using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace N1x.Benchmarks;

sealed partial class Qualification
{
    static JsonArray Vision()
    {
        using var stream = typeof(Qualification).Assembly.GetManifestResourceStream("vision-fixture.png")!;
        using var memory = new MemoryStream(); stream.CopyTo(memory);
        return [Data.Obj(new {role="user",content=new object[]{new {type="text",text="Name the color and shape on the left, then on the right. Be brief."},
            new {type="image_url",image_url=new {url="data:image/png;base64,"+Convert.ToBase64String(memory.ToArray())}}}})];
    }

    internal static async Task<JsonObject> Required(Func<Task<JsonNode>> chat, Func<JsonNode, bool> check)
    {
        var first = await chat(); var message = first["message"]!;
        var retry = Answer(first).Length == 0 && (message["tool_calls"]?.AsArray().Count ?? 0) == 0 ? await chat() : null;
        return Data.Obj(new
        {
            correct = check(first),
            retried_empty_final = retry != null,
            retry_correct = retry != null ? (bool?)check(retry) : null,
            retry_empty_final = retry != null ? (bool?)(Answer(retry).Length == 0) : null
        });
    }

    async Task Mixed(int output, bool soak)
    {
        if (output < 1) throw new ArgumentException("Output allowance must be positive");
        var archives = new Dictionary<int, JsonArray>(); var lengths = new Dictionary<int, int>();
        foreach (int n in new[] { 65000, 131000 }) { archives[n] = (await Archive(n)).Messages; if (!soak) lengths[n] = await Tokenize(archives[n], true); }
        var picture = Vision(); var rows = new List<JsonObject>();
        JsonArray tools = [Tool("lookup_inventory", "Get stock by SKU.")];
        string prefix = soak ? "soak-" : "";
        var before = await Snapshot(prefix + "before"); var timer = Stopwatch.StartNew();
        async Task<JsonObject> ArchiveCheck(int cycle)
        {
            int n = cycle % 2 == 0 ? 65000 : 131000;
            var r = await Required(() => Chat(archives[n], $"{salt}-archive-{cycle}", output, true), Codes);
            r["kind"] = "archive"; r["prompt_tokens"] = lengths[n]; return r;
        }
        async Task<JsonObject> Check(string kind, int cycle, JsonArray history, Func<JsonNode, bool> accept)
        {
            var r = await Required(() => Chat(history, $"{salt}-{(kind == "arithmetic" ? "short" : kind)}-{cycle}", output, true), accept);
            r["kind"] = kind; return r;
        }
        async Task<JsonObject> ToolCheck(int cycle)
        {
            string sku = $"MIX-{cycle}", key = $"{salt}-tool-{cycle}";
            JsonArray history = [Message("user", $"Use lookup_inventory to look up SKU {sku}. After its result return only the integer count. Do not guess.")];
            var first = await Chat(history, key, output, true, tools);
            if (!ValidCall(first, "lookup_inventory", sku)) return Data.Obj(new { kind = "tool", correct = false });
            history.Add(Assistant(first["message"]!)); history.Add(ToolResult(first["message"]!["tool_calls"]![0]!, new { sku, count = 23 + cycle }));
            var r = await Required(() => Chat(history, key, output, true, tools, "none"), c => Stopped(c) && Answer(c) == (23 + cycle).ToString()); r["kind"] = "tool"; return r;
        }
        if (soak)
        {
            for (int cycle = 0; cycle < 12; cycle++)
            {
                await Retrieve(archives[cycle % 2 == 0 ? 65000 : 131000], $"{salt}-soak-{cycle}");
                var choice = await Chat(picture, $"{salt}-vision-{cycle}");
                if (!Stopped(choice) || !new[] { "red", "circle", "blue", "square" }.All(w => Answer(choice).Contains(w, StringComparison.OrdinalIgnoreCase)))
                    throw new InvalidDataException("Mixed-workload vision check failed");
                choice = await Chat([Message("user", "Return only the result of 9 times 7.")], $"{salt}-short-{cycle}");
                if (!Stopped(choice) || Answer(choice) != "63") throw new InvalidDataException("Mixed-workload short check failed");
                if (cycle >= 4 && cycle % 4 == 3) await Retrieve(archives[65000], $"{salt}-soak-{cycle - 3}");
                rows.Add(Data.Obj(new { cycle = cycle + 1, elapsed_s = timer.Elapsed.TotalSeconds, passed = true })); Save("summary.json", rows);
            }
            var after = await Snapshot("soak-after"); Save("counters.json", Counters.Skip(2).ToDictionary(k => k, k => after.GetValueOrDefault(k) - before.GetValueOrDefault(k))); return;
        }
        try
        {
            for (int cycle = 0; cycle < 12; cycle++)
            {
                var time = Stopwatch.StartNew();
                var checks = (await Task.WhenAll(ArchiveCheck(cycle),
                    Check("vision", cycle, picture, c => Stopped(c) && Regex.IsMatch(Answer(c), @"red\s+circle.*blue\s+square", RegexOptions.Singleline | RegexOptions.IgnoreCase)),
                    Check("arithmetic", cycle, [Message("user", $"Return only the integer result of {9 + cycle} times 7.")], c => Stopped(c) && Answer(c) == ((9 + cycle) * 7).ToString()), ToolCheck(cycle))).ToList();
                if (cycle is 7 or 11) { var r = await ArchiveCheck(cycle - 3); r["kind"] = "revisit"; checks.Add(r); }
                rows.Add(Data.Obj(new { cycle = cycle + 1, elapsed_s = time.Elapsed.TotalSeconds, checks })); Save("cycles.json", rows);
                if (checks.Any(c => (bool?)c["correct"] != true)) throw new InvalidDataException("Mixed-workload correctness failed; inspect responses");
            }
        }
        finally
        {
            var after = await Snapshot("after");
            var checks = rows.SelectMany(r => r["checks"]!.AsArray()).ToArray();
            Save("summary.json", new
            {
                completed_cycles = rows.Count,
                planned_cycles = 12,
                correct = checks.Count(c => (bool?)c!["correct"] == true),
                checks = checks.Length,
                elapsed_s = timer.Elapsed.TotalSeconds,
                thinking = true,
                max_output_tokens = output,
                concurrency = 4,
                prompt_tokens = lengths,
                counters = Counters.Skip(1).Where(k => cacheMetrics || !k.StartsWith("lmcache_")).ToDictionary(k => k, k => after.GetValueOrDefault(k) - before.GetValueOrDefault(k)),
                retried_empty_finals = checks.Count(c => (bool?)c!["retried_empty_final"] == true),
                retry_correct_checks = checks.Count(c => (bool?)c!["retry_correct"] == true),
                retry_policy = "One unchanged-history retry for an empty required final; original scores retained; elapsed time includes retries"
            });
        }
    }

    async Task Recovery()
    {
        JsonArray tools = [Tool("lookup_inventory", "Get current stock count."), Tool("lookup_price", "Get current price in cents.")];
        async Task<List<JsonObject>> Session(int n)
        {
            var rows = new List<JsonObject>();
            string key = $"{salt}-recovery-{n}";
            JsonArray history = [Message("system", "Use the appropriate lookup tool; never guess values. Retry a transient tool error once. If the service gives a canonical_sku, retry with that exact SKU. After success, return only the requested CODE:VALUE.")];
            for (int turn = 0; turn < 6; turn++)
            {
                string name = turn % 2 == 0 ? "lookup_inventory" : "lookup_price", field = turn % 2 == 0 ? "count" : "price_cents";
                string mode = new[] { "normal", "transient", "canonical" }[turn % 3], sku = $"AX-{n}-{turn}", expected = sku, code = $"CASE-{n}-{turn}";
                int value = 137 + n * 11 + turn * 3, calls = 0; bool passed = false, success = false; string reason = "No final answer";
                history.Add(Message("user", $"Look up the {(turn % 2 == 0 ? "stock count" : "price in cents")} for SKU {sku}. Return only {code}:VALUE with the value from the tool."));
                for (int step = 0; step < 4; step++)
                {
                    var c = await Chat(history, key, 1024, true, tools); var m = c["message"]!;
                    if (m["tool_calls"] is JsonArray { Count: > 0 } list)
                    {
                        history.Add(Assistant(m));
                        if (success || !ValidCall(c, name, expected))
                        {
                            foreach (var call in list) history.Add(ToolResult(call!, new { error = "unexpected_tool_call" }));
                            reason = "Incorrect tool, arguments, or duplicate successful call"; break;
                        }
                        calls++; object result;
                        if (calls == 1 && mode == "transient") result = new { error = "temporary_unavailable", retryable = true };
                        else if (calls == 1 && mode == "canonical") { expected = sku + "-CANON"; result = new { error = "noncanonical_sku", canonical_sku = expected }; }
                        else { success = true; result = new Dictionary<string, object> { ["sku"] = expected, [field] = value }; }
                        history.Add(ToolResult(list[0]!, result));
                    }
                    else
                    {
                        string answer = Answer(c); history.Add(Message("assistant", answer)); passed = success && Stopped(c) && answer == $"{code}:{value}";
                        reason = passed ? "pass" : "Incorrect or premature final answer"; break;
                    }
                }
                rows.Add(Data.Obj(new { session = n, turn, mode, tool = name, passed, calls, reason }));
            }
            return rows;
        }
        var before = await Snapshot("before"); var time = Stopwatch.StartNew();
        var rows = (await Task.WhenAll(Enumerable.Range(0, 4).Select(Session))).SelectMany(x => x).ToArray();
        double elapsed = time.Elapsed.TotalSeconds; var after = await Snapshot("after"); int correct = rows.Count(r => (bool)r["passed"]!);
        Save("summary.json", new
        {
            correct,
            planned = rows.Length,
            elapsed_s = elapsed,
            thinking = true,
            concurrency = 4,
            max_output_tokens = 1024,
            preemptions = after.GetValueOrDefault(Counters[2]) - before.GetValueOrDefault(Counters[2]),
            rows
        });
        if (correct != rows.Length) throw new InvalidDataException("Tool recovery qualification failed; inspect summary and responses");
    }

    async Task Restart(string stage)
    {
        if (stage == "seed")
        {
            var (messages, tokens) = await Archive(131000); string[] salts = [$"{salt}-pair-0", $"{salt}-pair-1"];
            Save("manifest.json", new { messages, tokens, salts });
            foreach (string key in salts) await Retrieve(messages, key);
            var time = Stopwatch.StartNew(); int stable = 0; double? previous = null;
            while (time.Elapsed.TotalSeconds < 60)
            {
                var c = await Snapshot("seed-after"); double submitted = c.GetValueOrDefault("lmcache_mp_l2_store_submitted_requests_total");
                stable = submitted > 0 && c.GetValueOrDefault("lmcache_mp_l2_store_completed_requests_total") >= submitted && submitted == previous ? stable + 1 : 0;
                if (stable >= 2) return; previous = submitted; await Task.Delay(1000);
            }
            throw new TimeoutException("SSD stores did not settle before restart");
        }
        if (stage != "verify") throw new ArgumentException("Expected seed or verify");
        var m = Data.Read(Path.Combine(folder, "manifest.json")); var before = await Snapshot("before"); var timer = Stopwatch.StartNew();
        var results = await Task.WhenAll(m["salts"]!.AsArray().Select(key => Retrieve(m["messages"]!.AsArray(), (string)key!)));
        double elapsed = timer.Elapsed.TotalSeconds; var after = await Snapshot("after"); int count = (int)m["tokens"]!;
        var delta = Counters.ToDictionary(k => k, k => after.GetValueOrDefault(k) - before.GetValueOrDefault(k));
        bool qualified = results.All(x => x) && delta[Counters[0]] == 0 && delta[Counters[1]] > 2 * (count - 4096) && delta[Counters[3]] >= 2 && delta[Counters[4]] > 0;
        Save("summary.json", new { tokens_each = count, correct = results.Count(x => x), elapsed_s = elapsed, qualified, delta });
        if (!qualified) throw new InvalidDataException("Answers passed but full simultaneous external restores not established");
    }

    public static async Task Run(string command, string[] args)
    {
        var o = new Options(args, ["--agent-thinking", "--no-lmcache-metrics"], ["--agent-concurrency"],
            ["--url", "--out", "--phase", "--agent-output-tokens", "--agent-sessions", "--agent-turns", "--output-tokens", "--stage", "--recipe-effort", "--recipe-temperature", "--recipe-seed"]);
        using var probe = new Qualification(o.Get("--out"), o.Get("--url", "http://127.0.0.1:8000"), !o.Has("--no-lmcache-metrics"));
        if (o.Has("--recipe-effort"))
        {
            string effort = o.Get("--recipe-effort");
            if (effort is not ("xhigh" or "medium")) throw new ArgumentException("Unknown recipe effort");
            probe.sampling = Data.Obj(new
            {
                temperature = double.Parse(o.Get("--recipe-temperature"), System.Globalization.CultureInfo.InvariantCulture),
                top_p = .95,
                top_k = 20,
                presence_penalty = 0,
                seed = o.Int("--recipe-seed", 42),
                max_tokens = 8192,
                chat_template_kwargs = new { enable_thinking = true, reasoning_effort = effort }
            });
        }
        await probe.http.GetStringAsync(probe.url + "/health");
        switch (command == "agent" ? o.Get("--phase") : command)
        {
            case "agents": await probe.Agents(o); break;
            case "restores" when probe.cacheMetrics: await probe.Restores(); break;
            case "soak" when probe.cacheMetrics: await probe.Mixed(128, true); break;
            case "mixed": await probe.Mixed(o.Int("--output-tokens", 1024), false); break;
            case "recovery": await probe.Recovery(); break;
            case "restart": await probe.Restart(o.Get("--stage")); break;
            default: throw new ArgumentException("Invalid qualification phase or cache metrics setting");
        }
    }
}
