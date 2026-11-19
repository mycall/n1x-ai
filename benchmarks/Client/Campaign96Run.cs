using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

sealed partial class Campaign96
{
    bool interrupted;
    async Task Workloads()
    {
        if (options.Has("--finish-from"))
        {
            string finish = Path.GetFullPath(options.Get("--finish-from"));
            foreach (string source in Directory.GetFiles(finish, "*-retained.json")) results[Path.GetFileNameWithoutExtension(source)] = Data.Read(source);
            string replay = Path.Combine(finish, "kv11-off-replay-attempt1", "summary.json");
            var groups = JsonNode.Parse(File.ReadAllText(replay))!.AsArray();
            if (groups.Count != 2) throw new InvalidDataException("Expected two completed cache-off replay groups");
            results["retained-off-replay"] = Data.Obj(new { groups, imported_from = replay });
            await Probe("kv11-on-replay", new(11, true, 8192), true); await Probe("kv11-on-4k", new(11, true, 4096)); return;
        }
        JsonObject a;
        if (options.Has("--baseline-from"))
        {
            string source = Path.GetFullPath(options.Get("--baseline-from")); a = await Report(source);
            a["qualified"] = false; a["imported_from"] = source; a["reason"] = "Retained failed baseline; not eligible for promotion comparisons";
            results["retained-kv11-baseline"] = a; Save("retained-baseline.json", a);
        }
        else a = await Probe("kv11-on-8k", new(11, true, 8192));
        var b = await Probe("kv15-on-8k", new(15, true, 8192));
        static double Rate(JsonObject summary)
        {
            var rows = summary["results"]!.AsArray(); double duration = rows.Sum(r => (double)r!["elapsed_s"]!);
            if (duration <= 0) throw new InvalidDataException("Expected positive combined task duration");
            return rows.Sum(r => (int)r!["correct_tasks"]!) / duration;
        }
        double before = Rate(a); double? ratio = before > 0 ? Rate(b) / before : null;
        bool eligible = (bool)a["qualified"]! && (bool)b["qualified"]!;
        int chosen = eligible && ratio >= 1.05 ? 15 : 11;
        var control = chosen == 15 ? b : a;
        decisions["kv"] = Data.Obj(new { chosen_for_followups = chosen, kv15_over_kv11 = ratio, kv15_qualified = b["qualified"], comparison_eligible = eligible, by_concurrency = Comparisons(a, b) });
        Save("decisions.json", decisions);
        var off = await Probe($"kv{chosen}-off-8k", new(chosen, false, 8192)); decisions["cache_off_vs_on"] = Comparisons(control, off);
        await Probe($"kv{chosen}-off-replay", new(chosen, false, 8192), true); await Probe($"kv{chosen}-on-replay", new(chosen, true, 8192), true);
        var small = await Probe($"kv{chosen}-on-4k", new(chosen, true, 4096)); decisions["batch4k_vs_8k"] = Comparisons(control, small); Save("decisions.json", decisions);
    }
    void Markdown(string? error, bool restored)
    {
        var lines = new List<string>{"# 96 GiB comparison campaign","",error==null?"Status: complete.":"Status: failed: "+error,$"Original configuration restored: {restored}.","",
            "| Configuration | C | Correct tasks | Batch seconds | Correct tasks/s | Warm task seconds |","| --- | ---: | ---: | ---: | ---: | ---: |"};
        foreach (var (name, summary) in results)
            foreach (var r in summary?["results"]?.AsArray() ?? [])
            {
                var warm = ((double?)r!["appended_task_mean_s"])?.ToString("F2") ?? "unavailable";
                lines.Add($"| {name} | {r["concurrency"]} | {r["correct_tasks"]}/{r["planned_tasks"]} | {(double)r["elapsed_s"]!:F2} | {(double)r["correct_tasks_s"]!:F5} | {warm} |");
            }
        lines.AddRange(["", "## Displaced replay", "", "| Configuration | Repeat | Correct tasks | Replay seconds | Native displacement verified | External restore verified |", "| --- | ---: | ---: | ---: | --- | --- |"]);
        foreach (var (name, summary) in results)
            foreach (var g in summary?["groups"]?.AsArray() ?? [])
                lines.Add($"| {name} | {g!["repeat"]} | {g["correct_tasks"]}/{g["planned_tasks"]} | {(double)g["elapsed_s"]!:F2} | {g["native_displacement_verified"]} | {g["external_restore_verified"]} |");
        lines.AddRange(["","Configurations ran in a fixed order. The campaign used no matched 88 GiB control. Inspect first scores, cache counters and raw logs before promoting a setting.",
            "The provisional KV choice controls follow-up tests. The campaign restores the original settings."]);
        File.WriteAllLines(Output("comparison.md"), lines);
    }
    internal async Task Run()
    {
        Directory.CreateDirectory(folder);
        string lockPath = Path.Combine(root, ".state", "campaign96.lock"); Directory.CreateDirectory(Path.GetDirectoryName(lockPath)!);
        using var campaignLock = new FileStream(lockPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 4096, FileOptions.DeleteOnClose);
        JsonSerializer.Serialize(campaignLock, new { pid = Environment.ProcessId, @out = folder }); campaignLock.Flush(true);
        if (File.Exists(Output("status.json"))) throw new IOException("Campaign directory already contains a run");
        original = File.ReadAllBytes(config); expected = original;
        void Interrupt(object? sender, ConsoleCancelEventArgs args) { args.Cancel = true; Volatile.Write(ref interrupted, true); }
        Console.CancelKeyPress += Interrupt;
        string? error = null; bool restored = false;
        try
        {
            File.WriteAllBytes(Output("config.local.original.psd1"), original);
            string[] sources = ["benchmarks/Client/Campaign96.cs", "benchmarks/Client/Campaign96Run.cs", "benchmarks/campaign96_host.ps1", "benchmarks/NearFullToolsReport.cs", "benchmarks/Client/LongTools.cs"];
            Save("plan.json", new
            {
                protocol = "n1x-campaign96-v1",
                partition_mib = 98304,
                input_target = 250000,
                output_allowance = 8192,
                sessions = 4,
                turns = 3,
                repeats = 2,
                concurrency = new[] { 2, 4 },
                concurrency_order = "2,4 then 4,2",
                stages = new[] { "KV11 on batch8K", "KV15 on batch8K", "chosen KV cache off batch8K", "cache-off displaced C2 replay", "cache-on displaced C2 replay", "chosen KV cache on batch4K" },
                selection = "Choose KV15 for follow-up tests if both configurations qualify and correct-work throughput improves by at least 5%.",
                limits = "Configuration order is fixed. The campaign has no matched 88 GiB control.",
                restore_original = true,
                started_utc = DateTimeOffset.UtcNow,
                recovery_policy = "After three health failures, interrupt the probe. Retain failed attempts and allow up to two restarts.",
                source_sha256 = sources.ToDictionary(p => Path.GetFileName(p), p => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(root, p)))))
            });
            await Workloads();
        }
        catch (Exception ex) { error = ex.Message; File.WriteAllText(Output("failure-traceback.txt"), ex.ToString()); Save("failure.json", new { error, stage = state, utc = DateTimeOffset.UtcNow }); }
        finally
        {
            try
            {
                Guard(); if (changed) { ReplaceConfig(config, expected, original); expected = original; await Restart("restore-original", true); }
                restored = true;
            }
            catch (Exception ex) { error = (error == null ? "" : error + "; ") + "RESTORE: " + ex.Message; }
            finally { Console.CancelKeyPress -= Interrupt; }
            string status = error == null ? "complete" : "failed";
            Save("summary.json", new { status, error, original_configuration_restored = restored, decisions, results, failed_attempt_files = Directory.GetFiles(folder, "*-attempt*-failure.json").Select(Path.GetFileName) });
            Markdown(error, restored); Status(status, "finished", new { error, original_configuration_restored = restored });
        }
        if (error != null) throw new IOException(error);
    }
}
