using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class RecipeHost
{
    internal static string Root()
    {
        foreach (string start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
            for (var dir = new DirectoryInfo(start); dir != null; dir = dir.Parent)
                if (File.Exists(Path.Combine(dir.FullName, "benchmarks", "recipe_trial_host.ps1"))) return dir.FullName;
        throw new DirectoryNotFoundException("Cannot locate recipe_trial_host.ps1");
    }

    internal static async Task<(int Code, string Output, string Error)> Execute(string root, string[] command, int timeout, string? log = null, Func<Process, CancellationToken, Task>? monitor = null, bool disableClientConfig = false)
    {
        var info = new ProcessStartInfo(command[0])
        {
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        if (disableClientConfig) info.Environment["N1X_CLIENT_CONFIG"] = "off";
        foreach (string arg in command.Skip(1)) info.ArgumentList.Add(arg);
        using var process = Process.Start(info) ?? throw new IOException("Cannot start " + command[0]);
        using var writer = log == null ? null : File.CreateText(log);
        async Task<string> Drain(StreamReader reader)
        {
            if (writer == null) return await reader.ReadToEndAsync();
            while (await reader.ReadLineAsync() is string line) lock (writer) writer.WriteLine(line);
            return "";
        }
        var stdout = Drain(process.StandardOutput);
        var stderr = Drain(process.StandardError);
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(timeout));
        using var monitors = CancellationTokenSource.CreateLinkedTokenSource(cancel.Token);
        var watch = monitor?.Invoke(process, monitors.Token) ?? Task.CompletedTask;
        try { var exit = process.WaitForExitAsync(cancel.Token); if (monitor != null && await Task.WhenAny(watch, exit) == watch) await watch; await exit; }
        catch (OperationCanceledException) { if (!process.HasExited) process.Kill(true); await Task.WhenAll(stdout, stderr); throw new TimeoutException(command[0] + " timed out"); }
        catch { if (!process.HasExited) process.Kill(true); await Task.WhenAll(stdout, stderr); throw; }
        finally { monitors.Cancel(); try { await watch; } catch (OperationCanceledException) when (monitors.IsCancellationRequested) { } }
        return (process.ExitCode, await stdout, await stderr);
    }
}

static class RecipeTrial
{
    const string Container = "n1x-recipe-trial", Url = "http://127.0.0.1:8000";
    public static async Task Run(string[] args)
    {
        var options = new Options(args, ["--long", "--restore", "--skip-screen", "--continue-after-quality-failure"],
            ["--depths", "--quality-seeds", "--long-concurrency"], ["--variant", "--out", "--name"]);
        string root = RecipeHost.Root(), folder = Path.GetFullPath(options.Get("--out")), variant = Path.GetFullPath(options.Get("--variant")), name = options.Get("--name");
        bool longRun = options.Has("--long"), restore = options.Has("--restore"), skip = options.Has("--skip-screen"), keep = options.Has("--continue-after-quality-failure");
        int[] seeds = options.Ints("--quality-seeds", 42);
        string[] concurrency = options.Has("--long-concurrency") ? options.List("--long-concurrency") : ["2", "4"];
        if (seeds.Distinct().Count() != seeds.Length || concurrency.Any(c => c != "2" && c != "4") || (skip && !longRun && !restore)) throw new ArgumentException("Invalid quality seeds, concurrency or screen selection");
        string PathTo(string file) => Path.Combine(folder, file);
        string configPath = Path.Combine(root, "config.local.psd1");
        byte[] config = File.ReadAllBytes(configPath);
        var variantJson = Data.Read(variant);
        Data.NewFolder(folder);
        Data.Save(PathTo("variant.json"), variantJson);
        Data.Save(PathTo("measurement-plan.json"), new { quality_seeds = seeds, continue_after_quality_failure = keep, skip_screen = skip, @long = longRun, long_concurrency = concurrency, restore });
        string bench = Path.Combine(root, "benchmarks"), host = Path.Combine(bench, "recipe_trial_host.ps1");
        Data.Save(PathTo("source-hashes.json"), Directory.GetFiles(Path.Combine(bench, "Client"), "*.cs").Append(host)
            .ToDictionary(p => Path.GetRelativePath(root, p), p => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(p)))));
        string stage = "starting";
        using var stop = new CancellationTokenSource();
        static double Now() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000d;
        void Status(string next, object? extra = null)
        {
            Volatile.Write(ref stage, next);
            var status = Data.Obj(new { stage = next, unix_s = Now() });
            if (extra != null) status = Data.Merge(status, Data.Obj(extra));
            Data.Save(PathTo("status.json.tmp"), status); File.Move(PathTo("status.json.tmp"), PathTo("status.json"), true);
            Console.WriteLine(status.ToJsonString());
        }
        async Task Command(string label, int timeout, string[] command, bool required = true)
        {
            Status(label);
            var result = await RecipeHost.Execute(root, command, timeout, PathTo(label + ".log"));
            if (required && result.Code != 0) throw new IOException($"{label} failed ({result.Code})");
        }
        string[] Host(string action) => ["pwsh", "-NoProfile", "-File", host, "-Variant", variant, "-Out", folder, "-Action", action];
        string[] Client(params string[] arguments) => ["dotnet", typeof(RecipeTrial).Assembly.Location, .. arguments];
        async Task Ready()
        {
            using var client = new ModelClient(Url, 5); Status("waiting-ready"); var elapsed = Stopwatch.StartNew();
            int stopped = 0;
            while (elapsed.Elapsed.TotalMinutes < 40)
            {
                try { await client.Text("/health"); return; }
                catch (Exception e) when (e is HttpRequestException or TaskCanceledException) { }
                var inspect = await RecipeHost.Execute(root, ["wslc", "inspect", Container], 60);
                JsonNode? node = null;
                try { if (inspect.Code == 0) node = JsonNode.Parse(inspect.Output); } catch (JsonException) { }
                var entry = node is JsonArray list ? list.FirstOrDefault() : node;
                if (entry == null)
                {
                    Data.Save(PathTo("inspection-transient.json"), new { unix_s = Now(), returncode = inspect.Code, stdout = inspect.Output, stderr = inspect.Error }); stopped = 0;
                }
                else if ((bool)entry["State"]!["Running"]!) stopped = 0;
                else { Data.Save(PathTo("inspection-stopped.json"), node!); if (++stopped >= 2) throw new IOException("Trial container stopped before readiness (confirmed twice)"); }
                await Task.Delay(5000);
            }
            throw new TimeoutException("Readiness exceeded 40 minutes");
        }
        async Task Monitor()
        {
            using var log = File.CreateText(PathTo("telemetry.jsonl"));
            while (!stop.IsCancellationRequested)
            {
                string gpu = "";
                try { gpu = (await RecipeHost.Execute(root, ["nvidia-smi", "--id=0", "--query-gpu=memory.used,memory.free,clocks.sm,power.draw,temperature.gpu", "--format=csv,noheader"], 15)).Output.Trim(); }
                catch (Exception ex) { Console.Error.WriteLine(ex.Message); }
                JsonNode? memory = null;
                try { memory = Data.Read(Path.Combine(root, ".state", Container, "host.json")); } catch (Exception ex) when (ex is IOException or JsonException) { }
                await log.WriteLineAsync(Data.Obj(new { unix_s = Now(), stage = Volatile.Read(ref stage), gpu, host = memory }).ToJsonString()); await log.FlushAsync();
                try { await Task.Delay(5000, stop.Token); } catch (OperationCanceledException) { return; }
            }
        }
        var watcher = Monitor(); string? failure = null; bool launched = false;
        try
        {
            await Command("launch", 180, Host("launch")); launched = true; await Ready(); await Command("capture", 90, Host("capture"));
            Status("warmup"); using var client = new ModelClient(Url, 180);
            var warmup = new { model = "qwen/qwen38fn-best", messages = new[] { new { role = "user", content = "What is 17 plus 25? Reply with the number." } }, max_tokens = 8192, temperature = 0, chat_template_kwargs = new { enable_thinking = true } };
            var warm = await client.Get("/v1/chat/completions", warmup); Data.Save(PathTo("warmup.json"), warm!);
            if (string.IsNullOrWhiteSpace((string?)warm?["choices"]?[0]?["message"]?["content"]))
            {
                Data.Save(PathTo("warmup-retry.json"), (await client.Get("/v1/chat/completions", warmup))!); throw new IOException("Empty first warmup answer");
            }
            if (!skip)
            {
                string[] depths = options.Has("--depths") ? options.List("--depths") : ["4096", "32768"];
                await Command("speed", 5400, Client(["speed", "--out", PathTo("speed"), "--profile", name, "--host-record", PathTo("host.json"), "--depths", .. depths, "--concurrency", "1", "2", "--repeats", "2", "--output-tokens", "512", "--context-limit", "262144", "--mode", "cold", "--timeout", "900"]));
                var screens = new List<object>();
                foreach (int seed in seeds)
                {
                    string label = screens.Count == 0 ? "quality" : "quality-seed-" + seed;
                    await Command(label, 2400, Client("recipe-quality", "--out", PathTo(label), "--variants", "xhigh-t06", "--phases", "quality", "recovery", "--quality-depth", "32768", "--seed", seed.ToString()));
                    var failures = Data.Read(PathTo(label + "/completed.json"))["failures"]!.AsArray();
                    string archive = PathTo(label + "/xhigh-t06/quality/summary.json"), recoveryPath = PathTo(label + "/xhigh-t06/recovery/summary.json");
                    var scores = File.Exists(archive) ? JsonNode.Parse(File.ReadAllText(archive))!.AsArray() : new JsonArray();
                    var recovery = File.Exists(recoveryPath) ? Data.Read(recoveryPath) : new JsonObject();
                    bool passed = failures.Count == 0 && scores.Count == 2 && scores.All(r => (int?)r!["correct"] == 4 && (int?)r["planned"] == 4) && (int?)recovery["correct"] == 24 && (int?)recovery["planned"] == 24;
                    recovery.Remove("rows");
                    screens.Add(new { seed, folder = label, passed, failures, archive = scores, recovery }); Data.Save(PathTo("quality-screens.json"), screens);
                    if (!passed) { failure = "Quality screen failed; retained first scores"; if (!keep) throw new IOException(failure); }
                }
            }
            if (longRun) await Command("near-full", 3600, Client(["near-full", "--out", PathTo("near-full"), "--host", PathTo("host.json"), "--target", "250000", "--concurrency", .. concurrency, "--sessions", "4", "--turns", "3", "--repeats", "1"]));
            if (restore)
            {
                if ((bool?)Data.Read(PathTo("config.json"))["UseLMCache"] != true) throw new IOException("SSD restore qualification requires an LMCache candidate");
                Data.NewFolder(PathTo("restore"));
                foreach (string phase in new[] { "seed", "verify" })
                {
                    if (phase == "verify") { await Command("restart", 180, Host("restart")); await Ready(); }
                    await Command("restore-" + phase, 1800, ["wslc", "run", "--rm", "--network", "container:" + Container, "--volume", bench + ":/benchmarks:ro", "--volume", PathTo("restore") + ":/results", "--entrypoint", "dotnet", "mcr.microsoft.com/dotnet/sdk:10.0", "run", "--project", "/benchmarks/Client", "--artifacts-path", "/tmp/n1x-build", "--", "restart", "--out", "/results", "--stage", phase]);
                }
            }
        }
        catch (Exception ex) { failure = ex.Message; Data.Save(PathTo("failure.json"), new { error = failure, traceback = ex.ToString() }); }
        finally
        {
            if (launched)
                foreach (var (label, seconds, cmd) in new[] { ("server", 90, new[] { "wslc", "logs", Container }), ("stop", 180, Host("stop")), ("server-final", 90, new[] { "wslc", "logs", Container }) })
                    try { await Command(label, seconds, cmd, false); } catch (Exception ex) { failure = string.Join(" ", failure, ex.Message); }
            stop.Cancel(); await watcher;
            if (!File.Exists(configPath) || !config.SequenceEqual(File.ReadAllBytes(configPath))) failure += " Selected configuration changed externally; not overwritten.";
            if (failure != null && !File.Exists(PathTo("failure.json"))) Data.Save(PathTo("failure.json"), new { error = failure });
            Status("finished", new { success = failure == null, error = failure });
        }
        if (failure != null) throw new IOException(failure);
    }
}
