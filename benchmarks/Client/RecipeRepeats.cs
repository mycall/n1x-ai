using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class RecipeRepeats
{
    static IEnumerable<JsonNode> Rows(JsonNode? array) => array?.AsArray().OfType<JsonNode>() ?? [];
    internal static JsonObject Stats(IEnumerable<double> numbers)
    {
        double[] values = numbers.Order().ToArray();
        int n = values.Length;
        double? mean = n > 0 ? values.Average() : null;
        return Data.Obj(new
        {
            n,
            mean,
            median = n > 0 ? (values[(n - 1) / 2] + values[n / 2]) / 2 : (double?)null,
            minimum = n > 0 ? values[0] : (double?)null,
            maximum = n > 0 ? values[^1] : (double?)null,
            sample_sd = n > 1 ? Math.Sqrt(values.Sum(v => Math.Pow(v - mean!.Value, 2)) / (n - 1)) : (double?)null
        });
    }

    internal static JsonObject Report(JsonObject plan, List<JsonObject> trials)
    {
        var groups = new JsonObject();
        foreach (int batch in new[] { 4096, 8192 })
        {
            var rows = trials.Where(t => (int)t["batch"]! == batch).ToArray();
            JsonNode[] Field(string name) => rows.SelectMany(r => Rows(r[name])).ToArray();
            var longs = Field("near_full").Where(g => (int)g["concurrency"]! == 4).ToArray();
            var screens = Field("quality-screens");
            var restores = rows.Select(r => r["restore"]).OfType<JsonObject>().ToArray();
            var evidence = longs.SelectMany(g => g["cache_evidence"]!.AsObject()).Where(p => p.Key != "cold-selection").Select(p => p.Value!).ToArray();
            var speeds = new JsonObject();
            foreach (int c in new[] { 1, 2 }) foreach (int d in new[] { 4096, 32768 })
            {
                var points = Field("speed").Where(p => (int)p["concurrency"]! == c && (int)p["depth"]! == d && (int?)p["valid"] == 2 * c && (int?)p["recorded"] == 2 * c && p["write_tokens_s"] != null).ToArray();
                speeds[$"c{c}-d{d}"] = Data.Obj(new { read_tokens_s = Stats(points.Select(p => (double)p["read_tokens_s"]!)), write_tokens_s = Stats(points.Select(p => (double)p["write_tokens_s"]!)) });
            }
            groups[batch.ToString()] = Data.Obj(new
            {
                planned_trials = 3,
                recorded_trials = rows.Length,
                finished_trials = rows.Count(r => (string?)r["status"]?["stage"] == "finished"),
                long_elapsed_s = Stats(longs.Select(g => (double)g["elapsed_s"]!)),
                long_correct = longs.Sum(g => (int)g["correct_tasks"]!),
                long_planned = longs.Sum(g => (int)g["planned_tasks"]!),
                followup_hits = evidence.Sum(v => (int)v["requests_with_cached_tokens"]!),
                followup_requests = evidence.Sum(v => (int)v["requests"]!),
                short_screens = screens.Length,
                short_planned = 32 * screens.Length,
                short_correct = screens.Sum(s => Rows(s["archive"]).Sum(a => (int)a["correct"]!) + ((int?)s["recovery"]?["correct"] ?? 0)),
                restore_elapsed_s = Stats(restores.Select(r => (double)r["elapsed_s"]!)),
                restore_correct = restores.Sum(r => (int)r["correct"]!),
                restore_requests = 2 * restores.Length,
                strict_restore_passes = restores.Count(r => (bool)r["qualified"]!),
                restore_chunk_coverage = Stats(restores.SelectMany(r => Rows(r["verification_requests"])).Select(q => (double)q["complete_chunk_coverage"]!)),
                minimum_gpu_free_mib = rows.Select(r => (double?)r["resources"]?["minimum_gpu_free_mib"]).Min(),
                speed = speeds
            });
        }
        var pairs = new List<object>();
        foreach (int pair in new[] { 1, 2, 3 })
        {
            var times = trials.Where(t => (int)t["pair"]! == pair && Rows(t["near_full"]).Any()).ToDictionary(t => (int)t["batch"]!, t => (double)t["near_full"]![0]!["elapsed_s"]!);
            if (times.Count == 2) pairs.Add(new { pair, batch4k_s = times[4096], batch8k_s = times[8192], batch8k_elapsed_reduction_pct = 100 * (1 - times[8192] / times[4096]) });
        }
        return Data.Obj(new { plan, groups, paired_results = pairs, trials });
    }

    public static async Task Run(string[] args)
    {
        var options = new Options(args, ["--report-only"], [], ["--tag", "--directory", "--out"]);
        string root = RecipeHost.Root(), folder = Path.GetFullPath(options.Get("--directory")), tag = options.Get("--tag", "20261117-averages"), output = Path.GetFullPath(options.Get("--out"));
        string planPath = Path.Combine(folder, tag + "-plan.json");
        JsonObject plan;
        if (File.Exists(planPath)) plan = Data.Read(planPath);
        else
        {
            var runs = new List<object>();
            foreach (int pair in new[] { 1, 2, 3 }) foreach (int batch in pair == 2 ? new[] { 8192, 4096 } : new[] { 4096, 8192 })
            {
                string name = $"w4-kv20-batch{batch / 1024}k-k5-{tag}-r{pair}", volume = "n1x-recipe-" + name;
                Data.Save(Path.Combine(folder, name + ".json"), new
                {
                    flags = new Dictionary<string, string> { { "mamba-ssm-cache-dtype", "bfloat16" } },
                    config = new { Container = "n1x-recipe-trial", LmcacheNamespace = "qwen-recipe-" + name, LmcacheVolume = volume, KvCacheBytes = "21474836480", BatchedTokens = batch, DFlashTokens = 5 }
                });
                runs.Add(new { name, pair, batch, seed = 44 + pair, volume });
            }
            plan = Data.Obj(new
            {
                created_utc = DateTimeOffset.UtcNow,
                scope = "Three new paired full trials per batch; prior exploratory results excluded from primary averages.",
                order = "4K/8K, 8K/4K, 4K/8K",
                quality_seeds = new[] { 45, 46, 47 },
                failure_policy = "Retain all first scores; continue long/restore after short failures; average all completed workloads, not only passes.",
                runs
            });
            Data.Save(planPath, plan);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        async Task<string> Checked(params string[] command)
        {
            var result = await RecipeHost.Execute(root, command, 600);
            if (result.Code != 0) throw new IOException(command[0] + " failed: " + result.Error);
            return result.Output;
        }
        async Task SaveReport()
        {
            var trials = new List<JsonObject>();
            foreach (var item in Rows(plan["runs"]))
            {
                string dir = Path.Combine(folder, (string)item["name"]!);
                if (!File.Exists(Path.Combine(dir, "status.json"))) continue;
                var summary = JsonNode.Parse(await Checked("dotnet", "run", "--file", Path.Combine(root, "benchmarks", "RecipeReport.cs"), "--", "--trial", dir))!.AsObject();
                trials.Add(Data.Merge(Data.Obj(new { pair = item["pair"], batch = item["batch"], seed = item["seed"] }), summary));
            }
            Data.Save(output, Report(plan, trials));
        }
        if (!options.Has("--report-only"))
            foreach (var item in Rows(plan["runs"]))
            {
                string name = (string)item["name"]!, volume = (string)item["volume"]!, dir = Path.Combine(folder, name);
                if (File.Exists(Path.Combine(folder, "STOP"))) break;
                if (!Directory.Exists(dir))
                {
                    if (new DriveInfo(Path.GetPathRoot(folder)!).AvailableFreeSpace < 80L * 1024 * 1024 * 1024) throw new IOException("Less than 80 GiB disk headroom");
                    int code = 0;
                    try { await RecipeTrial.Run(["--variant", Path.Combine(folder, name + ".json"), "--out", dir, "--name", name, "--quality-seeds", item["seed"]!.ToString(), "--continue-after-quality-failure", "--long", "--long-concurrency", "4", "--restore"]); }
                    catch (Exception ex) { Console.Error.WriteLine(ex.Message); code = 1; }
                    Data.Save(Path.Combine(dir, "runner-returncode.json"), new { returncode = code });
                }
                if ((string?)Data.Read(Path.Combine(dir, "status.json"))["stage"] != "finished") throw new IOException("Existing unfinished trial requires inspection: " + name);
                await SaveReport();
                string cleanup = Path.Combine(dir, "cleanup.json");
                if (File.Exists(cleanup)) continue;
                var inspected = JsonNode.Parse(await Checked("wslc", "inspect", "n1x-recipe-trial"))!;
                var container = inspected is JsonArray ? inspected[0]! : inspected;
                if ((bool?)container["State"]?["Running"] != false || !Rows(container["Mounts"]).Any(m => (string?)m["Name"] == volume))
                    throw new IOException("Cleanup requires a stopped trial container with the planned volume");
                await Checked("wslc", "rm", "n1x-recipe-trial");
                await Checked("wslc", "volume", "rm", volume);
                var trim = await RecipeHost.Execute(root, ["wslc", "system", "session", "run", "/usr/sbin/fstrim", "-av"], 600);
                Data.Save(cleanup, new { volume, removed = true, trim_returncode = trim.Code, trim_stdout = trim.Output, trim_stderr = trim.Error, raw_evidence_preserved = true });
            }
        await SaveReport();
    }
}
