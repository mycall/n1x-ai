using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace N1x.Benchmarks;

sealed partial class Campaign96
{
    internal record Settings(int Kv, bool Cache, int Batch)
    {
        public static Settings From(JsonObject config) => new((int)(long.Parse(config["KvCacheBytes"]!.ToString()) >> 30), (bool)config["UseLMCache"]!, (int)config["BatchedTokens"]!);
        public byte[] Apply(byte[] original)
        {
            string text = Encoding.UTF8.GetString(original).TrimStart('\uFEFF');
            foreach (var (key, value) in new[] { ("KvCacheBytes", $"'{(long)Kv << 30}'"), ("UseLMCache", Cache ? "$true" : "$false"), ("BatchedTokens", Batch.ToString()) })
            {
                var pattern = new Regex("(?m)^[ \\t]*['\"]?" + key + "['\"]?\\s*=[^\\r\\n]*");
                string line = $"    {key} = {value}";
                switch (pattern.Count(text))
                {
                    case 1: text = pattern.Replace(text, _ => line); break;
                    case 0 when Regex.IsMatch(text, @"\}\s*$"): text = Regex.Replace(text, @"\}\s*$", _ => line + "\n}\n"); break;
                    default: throw new InvalidDataException("Cannot safely update local setting " + key);
                }
            }
            return Encoding.UTF8.GetBytes(text);
        }
    }
    internal sealed class TransportFailure(string reason) : IOException(reason);
    readonly string root, folder, config, shell;
    readonly Options options;
    readonly JsonObject results = new(), decisions = new();
    byte[] original = [], expected = [];
    JsonObject? baseline;
    Settings? current;
    JsonObject state = new();
    bool changed;
    internal Campaign96(string root, string[] args)
    {
        this.root = root;
        options = new(args, [], [], ["--out", "--baseline-from", "--resume-from", "--finish-from"]);
        folder = Path.GetFullPath(options.Get("--out")); config = Path.Combine(root, "config.local.psd1");
        shell = OperatingSystem.IsWindows() && !(Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator).Any(d => File.Exists(Path.Combine(d, "pwsh.exe"))) ? "powershell" : "pwsh";
    }
    string Output(string file) => Path.Combine(folder, file);
    void Save(string file, object value)
    {
        string path = Output(file); Data.Save(path + ".tmp", value); File.Move(path + ".tmp", path, true);
    }
    void Status(string phase, string stage, object? extra = null)
    {
        state = Data.Obj(new { state = phase, stage, pid = Environment.ProcessId, updated_utc = DateTimeOffset.UtcNow });
        if (extra != null) state = Data.Merge(state, Data.Obj(extra));
        Save("status.json", state); Console.WriteLine(state.ToJsonString());
    }
    static async Task<bool> Healthy()
    {
        using var client = new ModelClient("http://127.0.0.1:8000", 3);
        try { await client.Text("/health"); return true; } catch (Exception ex) when (ex is HttpRequestException or OperationCanceledException) { return false; }
    }
    async Task<int> Command(string name, string[] args, int timeout = 21600, bool allowFailure = false, bool restoring = false)
    {
        if (!restoring && (Volatile.Read(ref interrupted) || File.Exists(Output("STOP")))) throw new IOException("STOP requested");
        bool probe = args.Contains("near-full") || args.Contains("displaced");
        async Task Observe(Process child, CancellationToken cancel)
        {
            Status(restoring ? "restoring" : "running", name, new { child_pid = child.Id });
            var clock = Stopwatch.StartNew(); int unhealthy = 0;
            while (!child.HasExited)
            {
                await Task.Delay(TimeSpan.FromSeconds(10), cancel);
                Save("heartbeat.json", new { stage = name, child_pid = child.Id, utc = DateTimeOffset.UtcNow, elapsed_s = clock.Elapsed.TotalSeconds });
                if (!restoring && Volatile.Read(ref interrupted)) throw new OperationCanceledException("Campaign interrupted");
                if (!probe || child.HasExited) continue;
                unhealthy = await Healthy() ? 0 : unhealthy + 1;
                if (unhealthy == 3)
                {
                    Save(name + "-watchdog.json", new { reason = "Three consecutive health failures", elapsed_s = clock.Elapsed.TotalSeconds });
                    throw new TransportFailure("Probe lost service health");
                }
            }
        }
        var result = await RecipeHost.Execute(root, args, timeout, Output(name + ".log"), Observe, true);
        if (!allowFailure && result.Code != 0) throw new IOException($"{name} exited {result.Code}; see its log");
        return result.Code;
    }
    string[] Ps(string file, params string[] args) => [shell, "-NoProfile", "-File", Path.Combine(root, file), .. args];
    async Task Restart(string stage, bool restoring = false)
    {
        await Command(stage + "-recreate", Ps("n1x.ps1", "recreate", "-Profile", "qwen38fn-best"), 180, restoring: restoring);
        await Command(stage + "-ready", Ps("n1x.ps1", "wait", "-Profile", "qwen38fn-best", "-TimeoutSeconds", "1200"), 1250, restoring: restoring);
    }
    void Guard() { if (!File.ReadAllBytes(config).SequenceEqual(expected)) throw new IOException("Local configuration changed outside the campaign"); }
    internal static void ReplaceConfig(string path, byte[] expected, byte[] replacement)
    {
        using var file = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
        using var previous = new MemoryStream(); file.CopyTo(previous);
        if (!previous.ToArray().SequenceEqual(expected)) throw new IOException("Local configuration changed outside the campaign");
        file.Position = 0; file.Write(replacement); file.SetLength(replacement.Length); file.Flush(true);
    }
    async Task<(string, Settings)> Capture(string name)
    {
        string path = Output(name + "-host.json"); await Command(name + "-host", Ps("benchmarks/campaign96_host.ps1", "-Out", path), 60);
        var effective = Data.Read(path)["config"]!.AsObject();
        baseline ??= effective;
        foreach (var key in effective.Concat(baseline).Select(p => p.Key).Distinct())
            if (key is not ("KvCacheBytes" or "UseLMCache" or "BatchedTokens") && !JsonNode.DeepEquals(baseline[key], effective[key]))
                throw new InvalidDataException("Unexpected configuration difference: " + key);
        return (path, Settings.From(effective));
    }
    async Task<string> Configure(string name, Settings desired)
    {
        Guard();
        if (current == null)
        {
            await Command(name + "-start", Ps("n1x.ps1", "start", "-NoWait", "-Profile", "qwen38fn-best"), 180);
            await Command(name + "-ready", Ps("n1x.ps1", "wait", "-Profile", "qwen38fn-best", "-TimeoutSeconds", "1200"), 1250);
            (_, current) = await Capture("initial");
        }
        if (current != desired)
        {
            var bytes = desired.Apply(original); ReplaceConfig(config, expected, bytes); expected = bytes; changed = true;
            await Restart(name); current = desired;
        }
        var (path, actual) = await Capture(name); if (actual != desired) throw new InvalidDataException("Configuration mismatch: " + actual);
        Guard(); return path;
    }
    async Task<JsonObject> Report(string dir)
    {
        var command = await RecipeHost.Execute(root, ["dotnet", "run", "--file", Path.Combine(root, "benchmarks", "NearFullToolsReport.cs"), "--", dir], 300);
        if (command.Code != 0) throw new IOException(command.Error);
        return JsonNode.Parse(command.Output)!.AsObject();
    }
    internal static bool Qualified(JsonObject summary)
    {
        var rows = summary["results"]!.AsArray();
        return rows.Count == 2 && rows.Select(r => (int)r!["concurrency"]!).ToHashSet().SetEquals([2, 4]) &&
            rows.All(r => (int?)r!["correct_tasks"] == 24 && (int?)r["planned_tasks"] == 24);
    }
    internal static JsonArray Comparisons(JsonObject control, JsonObject candidate)
    {
        var rates = control["results"]!.AsArray().ToDictionary(r => (int)r!["concurrency"]!, r => (double)r!["correct_tasks_s"]!);
        var rows = new JsonArray();
        foreach (var r in candidate["results"]!.AsArray())
        {
            int concurrency = (int)r!["concurrency"]!; double rate = (double)r["correct_tasks_s"]!, before = rates[concurrency];
            rows.Add(Data.Obj(new
            {
                concurrency,
                control_tasks_s = before,
                candidate_tasks_s = rate,
                throughput_ratio = before > 0 ? rate / before : (double?)null,
                comparison_eligible = (bool?)control["qualified"] == true && (bool?)candidate["qualified"] == true,
                candidate_correct = r["correct_tasks"],
                candidate_planned = r["planned_tasks"]
            }));
        }
        return rows;
    }
    internal static async Task<T> Retry<T>(string name, Func<string, Task<T>> run, Func<Exception, int, string, Task<bool>> recover)
    {
        for (int attempt = 1; ; attempt++)
        {
            string label = $"{name}-attempt{attempt}";
            try { return await run(label); }
            catch (Exception ex) { if (!await recover(ex, attempt, label)) throw; }
        }
    }
    async Task<JsonObject> Probe(string name, Settings settings, bool replay = false)
    {
        if (!replay && options.Has("--resume-from"))
        {
            string previous = Path.GetFullPath(options.Get("--resume-from")), source = Path.Combine(previous, name + "-attempt1");
            if (File.Exists(Path.Combine(source, "summary.json")))
            {
                var summary = await Report(source); bool complete = File.Exists(Path.Combine(previous, name + "-attempt1-report.json"));
                summary["qualified"] = complete && Qualified(summary); summary["imported_from"] = source; summary["interrupted"] = !complete;
                results[name] = summary; Save(name + "-retained.json", summary); return summary;
            }
        }
        async Task<JsonObject> Attempt(string label)
        {
            string host = await Configure(label, settings), dir = Output(label);
            string[] cmd = ["dotnet", typeof(Campaign96).Assembly.Location, replay ? "displaced" : "near-full", "--out", dir, "--host", host, "--repeats", "2"];
            if (!replay) cmd = [.. cmd, "--sessions", "4", "--concurrency", "2", "4"];
            int code = await Command(label, cmd, allowFailure: true);
            await Command(label + "-server", ["wslc", "logs", "n1x-qwen38fn-best"], 60);
            string summaryPath = Path.Combine(dir, "summary.json"), errors = Path.Combine(dir, "errors.jsonl"); JsonObject summary;
            if (replay)
            {
                if (code != 0) throw new IOException($"{label} replay exited {code}");
                var groups = JsonNode.Parse(File.ReadAllText(summaryPath))!.AsArray();
                summary = Data.Obj(new
                {
                    groups,
                    complete = groups.Count == 2,
                    correctness_passed = groups.Count == 2 && groups.All(g => (int)g!["correct_tasks"]! == (int)g["planned_tasks"]!),
                    native_displacement_verified = groups.Count == 2 && groups.All(g => (bool)g!["native_displacement_verified"]!),
                    external_restore_verified = groups.Count == 2 && groups.All(g => (bool)g!["external_restore_verified"]!)
                });
            }
            else
            {
                if (code != 0 && File.Exists(errors) && Regex.IsMatch(File.ReadAllText(errors), "URLError|TimeoutError|ConnectionAbortedError|ConnectionResetError|HttpRequestException|TaskCanceledException")) throw new TransportFailure(label + " client transport failure");
                if (code != 0 && !File.Exists(summaryPath)) throw new IOException($"{label} probe exited {code}; inspect logs");
                summary = await Report(dir); summary["process_exit_code"] = code; summary["qualified"] = code == 0 && Qualified(summary); Save(label + "-report.json", summary);
            }
            results[label] = summary; await Capture(label + "-after"); Guard(); return summary;
        }
        try
        {
            return await Retry(name, Attempt, async (ex, attempt, label) =>
            {
                Save(label + "-failure.json", new { error = ex.Message, traceback = ex.ToString(), attempt, excluded_from_speed_comparison = true });
                if (attempt >= 3 || Volatile.Read(ref interrupted) || File.Exists(Output("STOP")) || (ex is not TransportFailure && await Healthy())) return false;
                Guard(); Status("recovering", name, new { failed_attempt = attempt, error = ex.Message }); await Restart(label + "-recover"); return true;
            });
        }
        catch (TransportFailure) when (!replay && !File.Exists(Output("STOP")) && File.Exists(Output(name + "-attempt3/summary.json")))
        {
            var summary = await Report(Output(name + "-attempt3")); summary["qualified"] = false; summary["recovery_exhausted"] = true;
            results[name] = summary; Save(name + "-unqualified.json", summary); return summary;
        }
    }
}
