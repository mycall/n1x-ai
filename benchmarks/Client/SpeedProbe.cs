using System.Text.Json.Nodes;
using System.Runtime.CompilerServices;

namespace N1x.Benchmarks;

sealed class SpeedProbe
{
    const string SystemText = "Read the reference notes. Continue writing detailed reference notes when asked.";
    const string Instruction = "\nContinue with a detailed technical explanation of request handling and data storage.\n";
    const string Unit = "The service validates input, reads indexed records, schedules work, and stores the resulting response.\n";
    const string Model = "qwen/qwen38fn-best";
    readonly string directory, profile, mode;
    readonly string? effort, hostPath;
    readonly int[] depths, concurrencies;
    readonly int repeats, extension, output, context, tolerance;
    readonly bool thinking, planOnly;
    readonly string url;
    readonly double timeout;
    readonly List<JsonObject> records = [];
    readonly string runId = Guid.NewGuid().ToString("N");
    readonly record struct Cell(string Mode, int Concurrency, int Depth);
    readonly record struct StreamInput(int Stream, string Salt, string Prefix, int History, string Text, int Input);
    public SpeedProbe(string[] args)
    {
        var o = new Options(args, ["--no-thinking", "--thinking", "--plan-only"], ["--depths", "--concurrency"],
            ["--out", "--profile", "--host-record", "--url", "--repeats", "--extension-tokens", "--output-tokens", "--context-limit", "--mode", "--reasoning-effort", "--timeout", "--tolerance"]);
        profile = o.Get("--profile"); directory = o.Get("--out"); mode = o.Get("--mode", "cold");
        depths = o.Ints("--depths", 4096); concurrencies = o.Ints("--concurrency", 1);
        repeats = o.Int("--repeats", 3); extension = o.Int("--extension-tokens", 2048); output = o.Int("--output-tokens", 128);
        context = int.Parse(o.Get("--context-limit")); tolerance = o.Int("--tolerance", mode == "cold" && depths.SequenceEqual([4096]) ? 0 : 8);
        thinking = !o.Has("--no-thinking"); effort = thinking ? o.Get("--reasoning-effort", "xhigh") : null;
        hostPath = o.Has("--host-record") ? o.Get("--host-record") : null; planOnly = o.Has("--plan-only");
        url = o.Get("--url", "http://127.0.0.1:8000"); timeout = double.Parse(o.Get("--timeout", "3600"), System.Globalization.CultureInfo.InvariantCulture);
        if (depths.Any(x => x < 0) || concurrencies.Any(x => x is < 1 or > 16) || repeats < 1 || extension < 128 || output < 2 || context < 128 ||
            tolerance is < 0 or > 32 || !double.IsFinite(timeout) || timeout <= 0 || depths.Distinct().Count() != depths.Length ||
            concurrencies.Distinct().Count() != concurrencies.Length || mode is not ("cold" or "incremental" or "both") ||
            effort is not (null or "low" or "medium" or "xhigh") || !thinking && o.Has("--reasoning-effort"))
            throw new ArgumentException("Invalid speed workload");
    }

    string[] Modes => mode == "both" ? ["incremental", "cold"] : [mode];
    Cell[] Grid => (from m in Modes from c in concurrencies from d in depths select new Cell(m, c, d)).ToArray();
    long Required(Cell c) => (long)c.Depth + (c.Mode == "incremental" ? extension : 0) + output;
    string Status(Cell c) => c.Mode == "cold" && c.Depth == 0 ? "not-applicable" : Required(c) + 2L * tolerance > context ? "skipped" : "planned";
    object Plan()
    {
        var cells = Grid.Select(c => new
        {
            mode = c.Mode,
            concurrency = c.Concurrency,
            depth = c.Depth,
            status = Status(c),
            measured_requests = Status(c) == "planned" ? repeats * c.Concurrency : 0,
            prime_requests = Status(c) == "planned" && c.Mode == "incremental" && c.Depth > 0 ? repeats * c.Concurrency : 0,
            minimum_context_with_output = Required(c)
        }).ToArray();
        return new
        {
            protocol = "n1x-speed-v1",
            profile,
            context_limit = context,
            thinking,
            reasoning_effort = effort,
            output_tokens = output,
            extension_tokens = extension,
            repeats,
            token_tolerance = tolerance,
            cells,
            total_measured_requests = cells.Sum(c => c.measured_requests),
            total_prime_requests = cells.Sum(c => c.prime_requests),
            note = "Plan only; calibration calls excluded; actual token counts, cache coverage and hardware are unmeasured."
        };
    }
    object Messages(string text) => new[] { new { role = "system", content = SystemText }, new { role = "user", content = text } };
    object Template => thinking ? (object)new { enable_thinking = true, reasoning_effort = effort } : new { enable_thinking = false };
    JsonObject Body(string text, string salt, int tokens) => Data.Obj(new
    {
        model = Model,
        messages = Messages(text),
        max_tokens = tokens,
        ignore_eos = true,
        temperature = 0,
        seed = 42,
        stream = true,
        stream_options = new { include_usage = true },
        cache_salt = salt,
        chat_template_kwargs = Template
    });

    async Task<(string Text, int Count)> Calibrate(ModelClient client, int target, int stream, string prefix)
    {
        string lead = $"\nReference stream {stream:D4}.\n";
        int size = Math.Max(256, checked(target * 12));
        string filler = string.Concat(Enumerable.Repeat(Unit, size / Unit.Length + 1))[..size];
        string Candidate(int n) => prefix + lead + filler[..n] + Instruction;
        async Task<int> Count(string text)
        {
            var r = await client.Get("/tokenize", new { model = Model, messages = Messages(text), chat_template_kwargs = Template, add_generation_prompt = true });
            return Data.Integer(r?["count"]) is int n && n > 0 ? n : throw new InvalidDataException("Invalid rendered token count");
        }
        if (await Count(Candidate(0)) > target + tolerance) throw new InvalidDataException($"Target {target} below template size");
        int high = size;
        for (int i = 0; await Count(Candidate(high)) < target; i++)
        {
            if (i == 3) throw new InvalidDataException("Could not bound rendered prompt length");
            filler += filler; high = filler.Length;
        }
        int low = 0;
        while (low <= high)
        {
            int middle = low + (high - low) / 2;
            string text = Candidate(middle);
            int n = await Count(text);
            if (Math.Abs(n - target) <= tolerance) return (text, n);
            if (n < target) low = middle + 1; else high = middle - 1;
        }
        throw new InvalidDataException($"Cannot calibrate {target} tokens within {tolerance}");
    }

    static List<string> Errors(JsonObject r, int expected, int output, string mode)
    {
        var errors = new List<string>();
        var u = r["usage"];
        int? prompt = Data.Integer(u?["prompt_tokens"]), cached = Data.Integer(u?["prompt_tokens_details"]?["cached_tokens"]);
        if (prompt != expected) errors.Add("rendered-input-mismatch");
        if (Data.Integer(u?["completion_tokens"]) != output) errors.Add("fixed-output-not-completed");
        if ((bool?)r["stream_done"] != true || (string?)r["finish_reason"] is not ("length" or "stop") || (int?)r["generated_packets"] is not > 0) errors.Add("incomplete-generation-stream");
        if (prompt == null || cached == null || cached < 0 || cached > prompt) errors.Add("cache-coverage-unavailable");
        else if (mode == "cold" && cached != 0) errors.Add("cold-request-reused-cache");
        foreach (string name in new[] { "pp_s", "decode_s" }) if (Data.Positive(r["timing"]?[name]) == null) errors.Add("missing-" + name);
        return errors;
    }

    void Record(JsonObject row)
    {
        lock (records)
        {
            File.AppendAllText(Path.Combine(directory, "requests.jsonl"), row.ToJsonString() + "\n");
            records.Add(row);
        }
    }

    async Task Wave(ModelClient client, Cell c, int repeat)
    {
        var cell = Data.Obj(new { mode = c.Mode, concurrency = c.Concurrency, depth = c.Depth, repeat });
        string status = Status(c);
        if (status != "planned")
        {
            Record(Data.Merge(cell, Data.Obj(new { status, reason = status == "skipped" ? "context-limit-reserves-output" : "cold prompt cannot have zero rendered tokens" })));
            return;
        }
        var inputs = new List<StreamInput>();
        for (int stream = 0; stream < c.Concurrency; stream++)
        {
            var (prefix, history) = c.Mode == "incremental" && c.Depth > 0 ? await Calibrate(client, c.Depth, stream, "") : ("", 0);
            var (text, input) = await Calibrate(client, c.Mode == "incremental" ? history + extension : c.Depth, stream, prefix);
            if (input + output > context) throw new InvalidDataException("Actual rendered input leaves insufficient room for output");
            inputs.Add(new(stream, $"{runId}-{c.Mode}-{c.Concurrency}-{c.Depth}-{repeat}-{stream}", prefix, history, text, input));
        }
        await Task.WhenAll(inputs.Where(p => p.History > 0).Select(async p =>
        {
            var request = Body(p.Prefix, p.Salt, 1);
            JsonObject response;
            try { response = await client.Generate(request); }
            catch (Exception e) { Record(Data.Merge(cell, Data.Obj(new { stream = p.Stream, phase = "prime", status = "failed", error = e.Message, request }))); throw; }
            var errors = Errors(response, p.History, 1, "prime");
            errors.RemoveAll(e => e is "missing-pp_s" or "missing-decode_s");
            Record(Data.Merge(cell, response, Data.Obj(new { stream = p.Stream, phase = "prime", status = errors.Count == 0 ? "ok" : "invalid", errors, request })));
            if (errors.Count > 0) throw new InvalidDataException("Prefix prime failed: " + string.Join(", ", errors));
        }));
        await Task.WhenAll(inputs.Select(async p =>
        {
            var request = Body(p.Text, p.Salt, output);
            double started = (DateTime.UtcNow - DateTime.UnixEpoch).TotalSeconds;
            JsonObject row;
            try
            {
                var response = await client.Generate(request);
                var errors = Errors(response, p.Input, output, c.Mode);
                row = Data.Merge(cell, response, Data.Obj(new
                {
                    stream = p.Stream,
                    phase = "measured",
                    started_unix_s = started,
                    status = errors.Count == 0 ? "ok" : "invalid",
                    errors,
                    history_tokens = p.History,
                    expected_input_tokens = p.Input,
                    read_tokens = p.Input - p.History,
                    prompt_sha256 = Data.Hash(p.Text),
                    request
                }));
            }
            catch (Exception e) { row = Data.Merge(cell, Data.Obj(new { stream = p.Stream, phase = "measured", status = "failed", started_unix_s = started, request, error = e.Message })); }
            Record(row);
        }));
        Console.WriteLine($"{c.Mode} C{c.Concurrency} depth={c.Depth} repeat={repeat + 1}/{repeats}");
    }

    public async Task Run()
    {
        Data.NewFolder(directory);
        string PathTo(string name) => Path.Combine(directory, name);
        Data.Save(PathTo("plan.json"), Plan());
        if (planOnly) { Console.WriteLine(PathTo("plan.json")); return; }
        var hashes = typeof(SpeedProbe).Assembly.GetManifestResourceNames().Where(n => n.StartsWith("source/")).ToDictionary(n => n[7..], n =>
        {
            using var stream = typeof(SpeedProbe).Assembly.GetManifestResourceStream(n)!;
            return Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(stream));
        });
        var settings = new
        {
            protocol = "n1x-speed-v1",
            profile,
            depths,
            concurrency = concurrencies,
            repeats,
            modes = Modes,
            extension_tokens = extension,
            output_tokens = output,
            thinking,
            reasoning_effort = effort,
            context_limit = context,
            tolerance,
            seed = 42,
            prompt_recipe_sha256 = Data.Hash(SystemText + Instruction + Unit),
            read_basis = "added rendered tokens for incremental; full rendered prompt for cold",
            timing_policy = "direct-server-preferred; PP fallback e2e-minus-decode",
            repeat_order = "forward grid on even repeats, reverse on odd repeats",
            fixed_output = true,
            correctness_claim = false,
            generator_sha256 = Data.Hash(string.Join("\n", hashes.OrderBy(x => x.Key, StringComparer.Ordinal).Select(x => x.Key + ":" + x.Value)))
        };
        var metadata = Data.Obj(new { started_utc = DateTime.UtcNow.ToString("O"), run_id = runId, settings, status = "running", source_hashes = hashes });
        if (hostPath != null) metadata["host"] = Data.Read(hostPath);
        Data.Save(PathTo("run.json"), metadata);
        using var client = new ModelClient(url, timeout);
        try
        {
            await client.Get("/health");
            metadata["models"] = await client.Get("/v1/models");
            Data.Save(PathTo("run.json"), metadata);
            var grid = Grid;
            for (int i = 0; i < repeats; i++) foreach (var c in i % 2 == 0 ? grid.AsEnumerable() : grid.Reverse()) await Wave(client, c, i);
            metadata["status"] = records.All(r => (string?)r["status"] is "ok" or "not-applicable") ? "completed" : "incomplete";
        }
        catch (Exception error) { metadata["status"] = "failed"; metadata["error"] = error.Message; throw; }
        finally
        {
            metadata["finished_utc"] = DateTime.UtcNow.ToString("O");
            Data.Save(PathTo("run.json"), metadata);
            var summary = SpeedReport.Summarize(metadata, records);
            Data.Save(PathTo("summary.json"), summary);
            SpeedReport.Write([summary], directory);
        }
        if ((string?)metadata["status"] != "completed") throw new InvalidDataException("Speed matrix incomplete; first attempts and missing coverage retained");
    }
}
