using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;
using N1x.Benchmarks;

string root = Directory.CreateTempSubdirectory("n1x-speed-test-").FullName;
static void Check(bool ok, string message) { if (!ok) throw new Exception(message); }
static void Equal(JsonNode? a, JsonNode? b) => Check(JsonNode.DeepEquals(a, b), $"Mismatch: {a} != {b}");
var taken = new ConcurrentDictionary<string, int>();
int health = 0, generated = 0;
bool failPrime = false, invalid = false, slow = false;
using var port = new TcpListener(IPAddress.Loopback, 0);
port.Start();
string url = "http://127.0.0.1:" + ((IPEndPoint)port.LocalEndpoint).Port;
port.Stop();
using var listener = new HttpListener();
listener.Prefixes.Add(url + "/"); listener.Start();
async Task Respond(HttpListenerContext ctx)
{
    try
    {
        string path = ctx.Request.Url!.AbsolutePath;
        string text;
        if (path == "/health") { Interlocked.Increment(ref health); text = "{}"; }
        else if (path == "/metrics") text = "# HELP L1 \u2192 L2\nvllm:num_requests_running{worker=\"a\"} 2\n";
        else if (path == "/v1/models") text = "{\"data\":[]}";
        else
        {
            using var input = new StreamReader(ctx.Request.InputStream);
            var body = JsonNode.Parse(await input.ReadToEndAsync())!;
            var messages = body["messages"]!.AsArray(); var lastMessage = messages[^1]!;
            var prompt = (string?)lastMessage["content"] ?? "";
            if (body["stream"] == null && path.EndsWith("/chat/completions"))
            {
                object msg; string finish = "stop";
                if (prompt.EndsWith("Reply only READY.")) msg = new { content = "READY" };
                else if ((string?)lastMessage["role"] == "tool")
                {
                    if ((string?)messages[^2]!["reasoning"] != "preserved" || (string?)lastMessage["tool_call_id"] != "tool-id") throw new Exception("Broken tool continuation");
                    string code = System.Text.RegularExpressions.Regex.Match((string)messages[1]!["content"]!, @"AGENT-\d+").Value;
                    msg = new { content = code + ":" + JsonNode.Parse(prompt)!["count"] };
                }
                else
                {
                    string sku = System.Text.RegularExpressions.Regex.Match(prompt, @"AX-\d+-\d+").Value;
                    msg = new { content = (string?)null, reasoning = "preserved", tool_calls = new[] { new { id = "tool-id", type = "function", function = new { name = "lookup_inventory", arguments = Data.Obj(new { sku }).ToJsonString() } } } };
                    finish = "tool_calls";
                }
                text = Data.Obj(new { choices = new[] { new { finish_reason = finish, message = msg } } }).ToJsonString();
                await ctx.Response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes(text)); return;
            }
            string archive = (string?)messages.FirstOrDefault(m => (string?)m?["role"] == "user")?["content"] ?? "";
            int count = archive.Length / 4 + 20;
            if (path == "/tokenize") text = Data.Obj(new { count }).ToJsonString();
            else
            {
                Interlocked.Increment(ref generated);
                string salt = (string)body["cache_salt"]!;
                int tokens = (int)body["max_tokens"]!;
                if (failPrime && tokens == 1) { ctx.Response.StatusCode = 500; return; }
                if (slow && salt.EndsWith("-0")) await Task.Delay(180);
                taken.TryGetValue(salt, out int cached); taken[salt] = count;
                var usage = new { prompt_tokens = count, completion_tokens = tokens - (invalid ? 1 : 0), prompt_tokens_details = new { cached_tokens = cached } };
                var metrics = new { time_to_first_token_ms = 500, generation_time_ms = 1000 };
                if (archive.Contains("AUTHORITATIVE") && prompt != "")
                {
                    string[] words = System.Text.RegularExpressions.Regex.Matches(archive, @"(?:CEDAR|MAPLE|BIRCH)-\d+").Select(m => m.Value).ToArray();
                    string final;
                    object delta; string finish = "stop";
                    if (archive.Contains("AUTHORITATIVE session code"))
                    {
                        string sku = System.Text.RegularExpressions.Regex.Match(prompt, @"AX-\d+-\d+").Value;
                        if ((string?)lastMessage["role"] == "user")
                        {
                            string tool = prompt.Contains("Look up price") ? "lookup_price" : "lookup_inventory"; finish = "tool_calls";
                            delta = new { reasoning = "kept", tool_calls = new[] { new { index = 0, id = "fixture", type = "function", function = new { name = tool, arguments = Data.Obj(new { sku }).ToJsonString() } } } };
                        }
                        else
                        {
                            var tool = JsonNode.Parse(prompt)!;
                            string code = System.Text.RegularExpressions.Regex.Match(archive, @"SESSION-\d+").Value;
                            final = $"{code}:{tool["count"] ?? tool["price_cents"]}:{words[0]}"; delta = new { content = final };
                        }
                    }
                    else
                    {
                        int index = int.Parse(words[0][6..]) - 5831;
                        final = (index % 8) switch
                        {
                            0 or 1 => string.Join(":", words),
                            2 or 3 => Data.Obj(new { total_cents = (7 + index) * (23 + index) + 11 + index, birch = words[2] }).ToJsonString(),
                            4 or 5 => Data.Obj(new { cedar = words[0], maple = words[1], birch = words[2], units = 7 + index }).ToJsonString(),
                            _ => $"CASE-{index}:{100 + index}:{words[2]}"
                        };
                        delta = new { content = final };
                    }
                    string packet = Data.Obj(new { choices = new[] { new { delta, finish_reason = finish } }, usage, metrics }).ToJsonString();
                    await ctx.Response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes("data: " + packet + "\n\ndata: [DONE]\n\n")); return;
                }
                var first = Data.Obj(new { choices = new[] { new { delta = new { reasoning_content = "think", tool_calls = new[] { new { index = 0, id = "id", function = new { name = "to", arguments = "{" } } } } } } });
                bool squares = prompt.StartsWith("Return only a JSON array");
                string answer = squares ? System.Text.Json.JsonSerializer.Serialize(Enumerable.Range(1, 20).Select(n => new { n, square = n * n, cube = n * n * n })) : "answer";
                var last = Data.Obj(new { choices = new[] { new { delta = new { content = answer, tool_calls = new[] { new { index = 0, function = new { name = "ol", arguments = "}" } } } }, finish_reason = squares ? "stop" : "length" } }, usage, metrics });
                text = $"data: {first.ToJsonString()}\n\ndata: {last.ToJsonString()}\n\ndata: [DONE]\n\n";
            }
        }
        await ctx.Response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes(text));
    }
    finally { ctx.Response.Close(); }
}
var server = Task.Run(async () =>
{
    try { while (listener.IsListening) { var ctx = await listener.GetContextAsync(); _ = Respond(ctx); } }
    catch (HttpListenerException) when (!listener.IsListening) { }
    catch (ObjectDisposedException) when (!listener.IsListening) { }
});
string PathTo(string name) => Path.Combine(root, name);
Task Run(string name, params string[] extra) => new SpeedProbe(["--out", PathTo(name), "--profile", "fixture", "--url", url, "--context-limit", "65536", .. extra]).Run();
async Task Fails(Func<Task> action)
{
    try { await action(); } catch (Exception) { return; }
    throw new Exception("Expected failure");
}
try
{
    SuiteTests.Run(root);
    await QualificationTests.Run();
    await Run("plan", "--plan-only");
    var plan = Data.Read(PathTo("plan/plan.json"));
    Check(health == 0 && (int)plan["output_tokens"]! == 128 && (int)plan["token_tolerance"]! == 0 && (int)plan["cells"]![0]!["depth"]! == 4096 && (string)plan["cells"]![0]!["mode"]! == "cold", "Offline standard plan");
    await Run("standard");
    var standard = SpeedReport.Load(PathTo("standard"));
    var cell = standard["cells"]![0]!;
    Equal(cell["read_write_tks"], JsonNode.Parse("[8192,127]"));
    Check((int)cell["valid_requests"]! == 3 && generated == 3 && health == 1, "Standard request counts");
    var raw = File.ReadLines(PathTo("standard/requests.jsonl")).Select(l => JsonNode.Parse(l)!.AsObject()).ToArray();
    Check((string)raw[0]["reasoning"]! == "think" && (string)raw[0]["content"]! == "answer" &&
        (string)raw[0]["tool_calls"]![0]!["function"]!["name"]! == "tool" && (string)raw[0]["tool_calls"]![0]!["function"]!["arguments"]! == "{}", "SSE fragments");
    var run = Data.Read(PathTo("standard/run.json"));
    Check((string)SpeedReport.Summarize(run, [raw[0], raw[0], raw[2]])["cells"]![0]!["status"]! == "incomplete", "Duplicate identities");
    raw[1]["timing"]!["pp_source"] = "derived";
    Equal(SpeedReport.Summarize(run, raw)["cells"]![0]!["read_write_tks"], JsonNode.Parse("[null,null]"));
    await Fails(() => Run("standard"));
    slow = true;
    await Run("incremental", "--mode", "incremental", "--depths", "0", "512", "--concurrency", "2", "--repeats", "2", "--extension-tokens", "128", "--output-tokens", "16", "--reasoning-effort", "low");
    slow = false;
    var summary = SpeedReport.Load(PathTo("incremental"));
    Check(summary["cells"]!.AsArray().All(c => (string)c!["status"]! == "complete"), "Incremental cache reuse");
    var entries = File.ReadLines(PathTo("incremental/requests.jsonl")).Select(l => JsonNode.Parse(l)!).ToArray();
    Check((int)entries[0]["stream"]! == 1 && (int)entries[^1]["depth"]! == 0, "Completion and repeat order");
    foreach (var entry in entries) Check((string)entry["request"]!["chat_template_kwargs"]!["reasoning_effort"]! == "low", "Effort propagation");
    failPrime = true;
    await Fails(() => Run("failed", "--mode", "incremental", "--depths", "512", "--repeats", "1"));
    failPrime = false;
    Check((string)Data.Read(PathTo("failed/run.json"))["status"]! == "failed" && File.Exists(PathTo("failed/summary.json")), "Prime failure retained");
    invalid = true;
    await Fails(() => Run("invalid", "--repeats", "1"));
    invalid = false;
    Check((string)SpeedReport.Load(PathTo("invalid"))["cells"]![0]!["status"]! == "incomplete", "Invalid output retained");
    await Fails(() => Run("skip", "--depths", "0", "100000"));
    var skipped = SpeedReport.Load(PathTo("skip"))["cells"]!;
    Check((string)skipped[0]!["status"]! == "not-applicable" && (string)skipped[1]!["status"]! == "skipped", "Unsupported points");
    await Fails(() => Run("bad", "--no-thinking", "--reasoning-effort", "low"));
    var fallback = ModelClient.Timing(Data.Obj(new { prompt_tokens = 100, completion_tokens = 21 }), null, 3, 1);
    Equal(fallback["read_write_tks"], JsonNode.Parse("[100,10]"));
    Equal(ModelClient.Timing(null, null, 2, null)["read_write_tks"], JsonNode.Parse("[null,null]"));
    var other = standard.DeepClone().AsObject();
    other["run_id"] = "other";
    other["cells"]![0]!["timing_source"]![0] = "derived";
    SpeedReport.Write([standard, other], root);
    Check(File.ReadAllText(PathTo("comparison.md")).Contains("different timing source"), "Timing source separation");
    other["settings"]!.AsObject().Remove("reasoning_effort");
    SpeedReport.Write([standard, other], root);
    Check(File.ReadAllText(PathTo("comparison.md")).Contains("unspecified"), "Legacy effort");
    await ShortProbes.Run("scheduler", ["--out", PathTo("scheduler"), "--url", url, "--concurrency", "2"]);
    var scheduler = Data.Read(PathTo("scheduler/probe.json"));
    Check(scheduler["rows"]!.AsArray().Count == 2 && (double)scheduler["max_running"]! == 2, "Scheduler evidence");
    await ShortProbes.Run("speculation", ["--out", PathTo("speculation"), "--url", url]);
    Check(JsonNode.Parse(File.ReadAllText(PathTo("speculation/results.json")))!.AsArray().Count == 6 && File.Exists(PathTo("speculation/after.prom")), "Speculation first attempts");
    await Qualification.Run("agent", ["--phase", "agents", "--out", PathTo("agents"), "--url", url, "--agent-thinking", "--agent-concurrency", "1", "2", "--no-lmcache-metrics", "--agent-sessions", "2", "--agent-turns", "2", "--agent-output-tokens", "8192"]);
    var agent = JsonNode.Parse(File.ReadAllText(PathTo("agents/summary.json")))!.AsArray();
    Check(agent.Count == 4 && agent.All(r => (int)r!["correct_tasks"]! == 4 && (int)r["max_output_tokens"]! == 8192), "Multi-turn agent qualification");
    Check(File.ReadAllText(PathTo("agents/agent-0-c1-before-vllm.prom")).Contains("\u2192"), "UTF-8 metric text");
    await Capacity.Run(["--out", PathTo("capacity"), "--profile", "fixture", "--url", url, "--context-limit", "4096", "--output-tokens", "512", "--concurrency", "1", "8", "--repeats", "1"]);
    var capacity = Data.Read(PathTo("capacity/summary.json")); Check((bool)capacity["quality_passed"]!, "Capacity task scoring");
    await Capacity.Run(["--out", PathTo("fallback"), "--prepared-from", PathTo("capacity"), "--profile", "fixture", "--url", url, "--context-limit", "4096", "--output-tokens", "512", "--concurrency", "6", "--repeats", "1"]);
    Equal(JsonNode.Parse(File.ReadAllText(PathTo("capacity/prepared-requests.json"))), JsonNode.Parse(File.ReadAllText(PathTo("fallback/prepared-requests.json"))));
    Data.Save(PathTo("host.json"), new { });
    using (var longTools = new LongTools(["--out", PathTo("near"), "--host", PathTo("host.json"), "--url", url, "--target", "1024", "--turns", "2", "--concurrency", "2", "--repeats", "1"], false)) await longTools.Run(false);
    Check((int)JsonNode.Parse(File.ReadAllText(PathTo("near/summary.json")))![0]!["correct_tasks"]! == 4, "Near-full tool calls");
    await CampaignTests.Run(PathTo("campaign"));
    RepeatTests.Run();
    MatrixTests.Run(PathTo("matrix"));
    Console.WriteLine("Benchmark client and reporting checks passed.");
}
finally { listener.Stop(); await server; Directory.Delete(root, true); }
