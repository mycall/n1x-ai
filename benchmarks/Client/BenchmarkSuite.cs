using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

sealed class BenchmarkSuite
{
    const string Model = "qwen/qwen38fn-best", Python = "/opt/venv/bin/python";
    readonly Options o;
    readonly string suite, url, folder, runId = Guid.NewGuid().ToString("N");
    readonly bool thinking;
    readonly int[] concurrency, lengths, agents, contexts;
    readonly int requests, output, conversations, samples, seed, sessions, turns;
    public BenchmarkSuite(string[] args)
    {
        o = new Options(args, ["--agent-thinking", "--thinking", "--no-thinking"], ["--concurrency", "--input-lengths", "--agent-concurrency", "--context-lengths"],
            ["--suite", "--url", "--out", "--requests", "--output-tokens", "--conversations", "--samples", "--seed", "--scheduler-concurrency", "--scheduler-output-tokens", "--agent-output-tokens", "--agent-sessions", "--agent-turns"]);
        suite = o.Get("--suite", "all"); url = o.Get("--url", "http://127.0.0.1:8000"); folder = o.Get("--out", "/results"); thinking = !o.Has("--no-thinking");
        concurrency = Ints("--concurrency", 1, 2, 4); lengths = Ints("--input-lengths", 4096); agents = Ints("--agent-concurrency", 1, 2, 4);
        contexts = Ints("--context-lengths", 16384, 65536, 131072, 262144);
        requests = o.Int("--requests", 16); output = o.Int("--output-tokens", 128); conversations = o.Int("--conversations", 16);
        samples = o.Int("--samples", 2); seed = o.Int("--seed", 42); sessions = o.Int("--agent-sessions", 4); turns = o.Int("--agent-turns", 3);
        if (suite is not ("all" or "vllm" or "aiperf" or "ruler" or "scheduler" or "speculation" or "agents" or "restores" or "soak" or "recovery" or "mixed") ||
           sessions is < 1 or > 16 || turns is < 1 or > 100 || o.Int("--agent-output-tokens", 1) < 1 || suite == "agents" && agents.Any(c => c is < 1 or > 16) ||
           suite != "agents" && (o.Has("--agent-output-tokens") || sessions != 4 || turns != 3)) throw new ArgumentException("Invalid suite or agent workload controls");
    }
    int[] Ints(string name, params int[] defaults) => o.Has(name) ? o.Ints(name, 0) : defaults;
    internal string[] ProbeArgs()
    {
        List<string> args = [suite is "agents" or "restores" or "soak" ? "agent" : suite, "--out", Path.Combine(folder, suite), "--url", url];
        if (args[0] == "agent")
        {
            args.AddRange(["--phase", suite]); if (thinking || o.Has("--agent-thinking")) args.Add("--agent-thinking");
            if (suite == "agents")
            {
                args.Add("--agent-concurrency"); args.AddRange(agents.Select(x => x.ToString()));
                args.AddRange(["--agent-sessions", sessions.ToString(), "--agent-turns", turns.ToString()]);
                if (o.Has("--agent-output-tokens")) args.AddRange(["--agent-output-tokens", o.Get("--agent-output-tokens")]);
            }
        }
        if (suite == "scheduler") args.AddRange(["--concurrency", o.Get("--scheduler-concurrency", "4"), "--output-tokens", o.Get("--scheduler-output-tokens", "256")]);
        if (suite is "scheduler" or "speculation" && !thinking) args.Add("--no-thinking");
        return args.ToArray();
    }

    static async Task Command(string dir, string name, params string[] args)
    {
        Directory.CreateDirectory(dir);
        Data.Save(Path.Combine(dir, name + "-command.json"), args);
        var p = new ProcessStartInfo(args[0]) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args.Skip(1)) p.ArgumentList.Add(arg);
        using var child = Process.Start(p)!;
        string path = Path.Combine(dir, name + ".log");
        using (var log = new StreamWriter(path))
        {
            async Task Pump(StreamReader input) { while (await input.ReadLineAsync() is string line) { lock (log) { log.WriteLine(line); log.Flush(); } } }
            await Task.WhenAll(Pump(child.StandardOutput), Pump(child.StandardError), child.WaitForExitAsync());
        }
        if (child.ExitCode != 0) { string log = File.ReadAllText(path); throw new InvalidOperationException($"{name} exited {child.ExitCode}\n{log[Math.Max(0, log.Length - 6000)..]}"); }
    }

    async Task Snapshot(string dir, string label, HttpClient http)
    {
        foreach (var (service, endpoint) in new[] { ("vllm", url + "/metrics"), ("lmcache", "http://127.0.0.1:8080/metrics") })
        {
            string text; try { text = await http.GetStringAsync(endpoint); } catch (HttpRequestException e) { text = "# unavailable: " + e.Message + "\n"; } catch (TaskCanceledException e) { text = "# unavailable: " + e.Message + "\n"; }
            await File.WriteAllTextAsync(Path.Combine(dir, $"{label}-{service}.prom"), text);
        }
    }

    async Task Vllm(HttpClient http)
    {
        foreach (int length in lengths) foreach (int c in concurrency)
        {
            string dir = Path.Combine(folder, $"vllm-{length}-c{c}"); Data.NewFolder(dir); await Snapshot(dir, "before", http);
            var extra = new { chat_template_kwargs = new { enable_thinking = thinking }, cache_salt = $"{runId}-vllm-{length}-{c}" };
            await Command(dir, "vllm", "vllm", "bench", "serve", "--base-url", url, "--backend", "openai-chat", "--endpoint", "/v1/chat/completions", "--model", Model,
                "--tokenizer", "/model", "--dataset-name", "random", "--random-input-len", length.ToString(), "--random-output-len", output.ToString(), "--random-range-ratio", "0",
                "--num-prompts", requests.ToString(), "--max-concurrency", c.ToString(), "--seed", seed.ToString(), "--num-warmups", "1", "--ignore-eos", "--extra-body", JsonSerializer.Serialize(extra),
                "--save-result", "--save-detailed", "--result-dir", dir, "--result-filename", "result.json", "--metric-percentiles", "50,95", "--percentile-metrics", "ttft,tpot,e2el", "--disable-tqdm");
            await Snapshot(dir, "after", http);
            if ((int?)Data.Read(Path.Combine(dir, "result.json"))["completed"] != requests) throw new InvalidDataException($"Incomplete vLLM benchmark: {dir}");
        }
    }

    internal static JsonObject Accuracy(string directory, int expectedCount)
    {
        var expected = Data.Read(Path.Combine(directory, "expected.json"));
        var rows = new List<JsonObject>();
        foreach (string line in File.ReadLines(Path.Combine(directory, "artifacts/profile_export_raw.jsonl")))
        {
            var record = JsonNode.Parse(line)!; var meta = record["metadata"]!;
            if ((string?)meta["benchmark_phase"] != "profiling") continue;
            var text = new StringBuilder(); string? finish = null; long? first = null;
            foreach (var response in record["responses"]?.AsArray() ?? [])
                foreach (var packet in response!["packets"]?.AsArray() ?? [])
                {
                    if ((string?)packet!["name"] != "data" || (string?)packet["value"] == "[DONE]") continue;
                    foreach (var choice in JsonNode.Parse((string)packet["value"]!)!["choices"]?.AsArray() ?? [])
                    {
                        string content = (string?)choice!["delta"]?["content"] ?? "";
                        if (content.Length > 0) first ??= (long)response["perf_ns"]!;
                        text.Append(content); finish = (string?)choice["finish_reason"] ?? finish;
                    }
                }
            string session = (string)meta["conversation_id"]!; int turn = (int)meta["turn_index"]!;
            long start = (long)meta["request_start_ns"]!, end = (long)meta["request_end_ns"]!;
            string answer = (string)expected[session]![turn]!;
            rows.Add(Data.Obj(new
            {
                session,
                turn,
                text = text.ToString(),
                expected = answer,
                finish_reason = finish,
                correct = (int?)record["status"] == 200 && finish == "stop" && text.ToString().Trim() == answer,
                start_ns = start,
                end_ns = end,
                latency_s = (end - start) / 1e9,
                ttft_s = first.HasValue ? (first - (long)record["start_perf_ns"]!) / 1e9 : null
            }));
        }
        if (rows.Count != expectedCount) throw new InvalidDataException($"Expected {expectedCount} turns, found {rows.Count}; inspect AIPerf errors");
        double duration = (rows.Max(r => (long)r["end_ns"]!) - rows.Min(r => (long)r["start_ns"]!)) / 1e9;
        int correct = rows.Count(r => (bool)r["correct"]!);
        var result = Data.Obj(new
        {
            turns = rows.Count,
            correct,
            duration_s = duration,
            correct_turns_per_s = correct / duration,
            first_turn_mean_ttft_s = rows.Where(r => (int)r["turn"]! == 0 && r["ttft_s"] != null).Average(r => (double)r["ttft_s"]!),
            followup_mean_ttft_s = rows.Where(r => (int)r["turn"]! > 0 && r["ttft_s"] != null).Average(r => (double)r["ttft_s"]!),
            responses = rows
        });
        Data.Save(Path.Combine(directory, "accuracy.json"), result); return result;
    }

    async Task Aiperf(HttpClient http)
    {
        // The tokenizer lives in the upstream model image. Ask it for the exact token slice used by this workload.
        const string prose = "Reference notes: the service accepts requests, checks inputs, and returns a response. ";
        await Command(folder, "tokenizer", Python, "-c", "from transformers import AutoTokenizer; import sys; t=AutoTokenizer.from_pretrained('/model',local_files_only=True); open(sys.argv[2],'w',encoding='utf-8').write(t.decode(t.encode(sys.argv[1]*3000,add_special_tokens=False)[:16000]))", prose, Path.Combine(folder, "tokenizer-output.txt"));
        string filler = File.ReadAllText(Path.Combine(folder, "tokenizer-output.txt"));
        foreach (int c in agents)
        {
            string dir = Path.Combine(folder, $"aiperf-c{c}"); Data.NewFolder(dir); var expected = new Dictionary<string, string[]>();
            string path = Path.Combine(dir, "conversations.jsonl");
            using (var file = new StreamWriter(path))
                for (int n = 0; n < conversations; n++)
                {
                    string id = $"session-{n}"; string[] codes = Enumerable.Range(0, 4).Select(i => $"K{n}{i}Z{seed}").ToArray(); expected[id] = codes;
                    string context = string.Join('\n', codes.Select((code, i) => $"Key {i + 1}: {code}"));
                    var turns = codes.Select((_, i) => new { text = (i == 0 ? $"Session {n}. Memorize these lookup keys.\n{context}\n{filler}\n" : "") + $"Return only the exact value for Key {i + 1} from this session.", output_length = thinking ? 1024 : 32 });
                    file.WriteLine(JsonSerializer.Serialize(new { session_id = id, turns }));
                }
            Data.Save(Path.Combine(dir, "expected.json"), expected); await Snapshot(dir, "before", http);
            await Command(dir, "aiperf", "/opt/aiperf/bin/aiperf", "profile", "--model", Model, "--tokenizer", "/model", "--url", url, "--endpoint-type", "chat", "--endpoint", "/v1/chat/completions", "--streaming",
                "--input-file", path, "--custom-dataset-type", "multi_turn", "--conversation-num", conversations.ToString(), "--concurrency", c.ToString(), "--random-seed", seed.ToString(),
                "--extra-inputs", JsonSerializer.Serialize(new { temperature = 0, chat_template_kwargs = new { enable_thinking = thinking }, cache_salt = $"{runId}-aiperf-{c}" }),
                "--artifact-dir", Path.Combine(dir, "artifacts"), "--export-level", "raw", "--ui", "simple", "--no-server-metrics", "--workers-max", "1");
            await Snapshot(dir, "after", http); Accuracy(dir, conversations * 4);
        }
    }

    async Task Ruler(HttpClient http, ModelClient client)
    {
        var summaries = new List<JsonObject>();
        foreach (int length in contexts) foreach (string task in new[] { "niah_single_1", "vt" })
        {
            int limit = thinking ? (task == "vt" ? 2048 : 1024) : (task == "vt" ? 512 : 128);
            string dir = Path.Combine(folder, $"ruler-{length}-{task}"); Data.NewFolder(dir);
            await Command(dir, "prepare", Python, "/opt/RULER/scripts/data/prepare.py", "--save_dir", Path.Combine(dir, "data"), "--benchmark", "synthetic", "--task", task, "--tokenizer_path", "/model",
                "--tokenizer_type", "hf", "--max_seq_length", (length - limit - 128).ToString(), "--model_template_type", "base", "--num_samples", samples.ToString(), "--random_seed", seed.ToString());
            var rows = File.ReadLines(Path.Combine(dir, "data", task, "validation.jsonl")).Select(l => JsonNode.Parse(l)!.AsObject()).ToArray();
            if (rows.Length != samples) throw new InvalidDataException("RULER generation returned wrong sample count");
            await Snapshot(dir, "before", http);
            string predictions = Path.Combine(dir, "predictions.jsonl");
            foreach (var r in rows)
            {
                var baseRequest = Data.Obj(new { model = Model, messages = new[] { new { role = "user", content = r["input"] } }, chat_template_kwargs = new { enable_thinking = thinking } });
                int count = (int)(await client.Get("/tokenize", baseRequest))!["count"]!;
                if (count + limit > length) throw new InvalidDataException($"Rendered input {count} exceeds {length} minus output budget");
                var body = Data.Merge(baseRequest, Data.Obj(new { temperature = 0, max_tokens = limit, cache_salt = $"{runId}-{task}-{length}-{r["index"]}" }));
                var timer = Stopwatch.StartNew(); var response = await client.Get("/v1/chat/completions", body);
                var choice = response!["choices"]![0]!;
                r["pred"] = (string?)choice["message"]!["content"] ?? ""; r["elapsed_s"] = timer.Elapsed.TotalSeconds; r["usage"] = response["usage"]!.DeepClone(); r["finish_reason"] = choice["finish_reason"]?.DeepClone();
                File.AppendAllText(predictions, r.ToJsonString() + "\n");
            }
            await Command(dir, "score", Python, "-c", "import runpy,sys,json; f=runpy.run_path('/opt/RULER/scripts/eval/synthetic/constants.py')['string_match_all']; rows=[json.loads(l) for l in open(sys.argv[1])]; print(f([r['pred'] for r in rows],[r['outputs'] for r in rows]))", predictions);
            var summary = Data.Obj(new
            {
                task,
                context_budget = length,
                output_limit = limit,
                samples = rows.Length,
                score_percent = double.Parse(File.ReadAllLines(Path.Combine(dir, "score.log"))[^1], System.Globalization.CultureInfo.InvariantCulture),
                prompt_tokens_min = rows.Min(r => (int)r["usage"]!["prompt_tokens"]!),
                prompt_tokens_max = rows.Max(r => (int)r["usage"]!["prompt_tokens"]!),
                mean_elapsed_s = rows.Average(r => (double)r["elapsed_s"]!),
                truncated = rows.Count(r => (string?)r["finish_reason"] == "length")
            });
            Data.Save(Path.Combine(dir, "summary.json"), summary); summaries.Add(summary); Data.Save(Path.Combine(folder, "ruler-summary.json"), summaries); await Snapshot(dir, "after", http);
        }
    }

    public async Task Run()
    {
        Directory.CreateDirectory(folder);
        Data.Save(Path.Combine(folder, "settings.json"), new
        {
            suite,
            url,
            @out = folder,
            concurrency,
            input_lengths = lengths,
            requests,
            output_tokens = output,
            agent_concurrency = agents,
            conversations,
            context_lengths = contexts,
            samples,
            seed,
            scheduler_concurrency = o.Int("--scheduler-concurrency", 4),
            scheduler_output_tokens = o.Int("--scheduler-output-tokens", 256),
            agent_thinking = o.Has("--agent-thinking"),
            agent_output_tokens = o.Has("--agent-output-tokens") ? (int?)o.Int("--agent-output-tokens", 0) : null,
            agent_sessions = sessions,
            agent_turns = turns,
            thinking,
            run_id = runId
        });
        using var http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromHours(1) };
        using var client = new ModelClient(url, 3600); await http.GetStringAsync(url + "/health");
        await Command(folder, "client-packages", "uv", "pip", "freeze", "--python", Python); await Command(folder, "aiperf-packages", "uv", "pip", "freeze", "--python", "/opt/aiperf/bin/python");
        if (suite is "all" or "vllm") await Vllm(http);
        if (suite is "all" or "aiperf") await Aiperf(http);
        if (suite is "all" or "ruler") await Ruler(http, client);
        if (suite is not ("all" or "vllm" or "aiperf" or "ruler"))
            await Command(folder, suite + "-probe", ["/opt/n1x-dotnet/dotnet", "/opt/n1x-client/Client.dll", .. ProbeArgs()]);
        Data.Save(Path.Combine(folder, "complete.json"), new { completed = true, suite });
    }
}
