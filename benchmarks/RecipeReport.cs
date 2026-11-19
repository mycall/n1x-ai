#:property PublishAot=false
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

var format = new JsonSerializerOptions { WriteIndented = true };
try
{
    if (args is ["--trial", var trial])
    {
        Console.WriteLine(JsonSerializer.Serialize(Summarize(trial), format));
        return 0;
    }
    if (args is not [_, "--out", _] and not ["--out", _, _])
        throw new ArgumentException("Expected DIRECTORY --out FILE or --trial DIRECTORY");
    var (root, output) = args[0] == "--out" ? (args[2], args[1]) : (args[0], args[2]);
    var report = new
    {
        provenance = Read(Path.Combine(root, "provenance.json")),
        model_verification = Read(Path.Combine(root, "az-verification.json")),
        trials = Directory.GetDirectories(root).Where(d => File.Exists(Path.Combine(d, "status.json")))
            .Order(StringComparer.Ordinal).Select(Summarize).ToArray()
    };
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
    File.WriteAllText(output, JsonSerializer.Serialize(report, format) + "\n");
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static JsonNode? Read(string path) => JsonNode.Parse(File.ReadAllText(path));
static IEnumerable<JsonObject> Rows(string path) =>
    File.ReadLines(path).Select(line => JsonNode.Parse(line)!.AsObject());

static Dictionary<string, object?> Summarize(string folder)
{
    string Local(string path) => Path.Combine(folder, path);
    var result = new Dictionary<string, object?> { ["name"] = new DirectoryInfo(folder).Name, ["status"] = Read(Local("status.json")) };
    foreach (string key in new[] { "variant", "config", "failure", "intentional-stop", "measurement-plan", "quality-screens" })
        if (File.Exists(Local(key + ".json"))) result[key] = Read(Local(key + ".json"));
    foreach (string key in new[] { "recipe.yaml", "environment.psd1" })
        if (File.Exists(Local(key))) result[key] = File.ReadAllText(Local(key)).ReplaceLineEndings("\n");

    if (File.Exists(Local("speed/requests.jsonl")))
        result["speed"] = Speed(Rows(Local("speed/requests.jsonl")));
    if (File.Exists(Local("quality/xhigh-t06/quality/summary.json")))
        result["archive"] = Read(Local("quality/xhigh-t06/quality/summary.json"));
    if (File.Exists(Local("quality/xhigh-t06/recovery/summary.json")))
    {
        var recovery = Read(Local("quality/xhigh-t06/recovery/summary.json"))!.AsObject();
        recovery.Remove("rows");
        result["recovery"] = recovery;
    }
    if (File.Exists(Local("near-full/summary.json")))
    {
        var near = Read(Local("near-full/summary.json"))!.AsArray();
        foreach (var group in near)
        {
            var requests = group!["sessions"]!.AsArray().SelectMany(s => s!["requests"]!.AsArray())
                .Where(r => (bool?)r!["diagnostic"] != true).GroupBy(r => (string)r!["phase"]!);
            var evidence = new JsonObject();
            foreach (var phase in requests)
            {
                var counts = phase.Select(r => (long?)r!["usage"]?["prompt_tokens_details"]?["cached_tokens"] ?? 0).ToArray();
                evidence[phase.Key] = JsonSerializer.SerializeToNode(new { requests = counts.Length, requests_with_cached_tokens = counts.Count(n => n > 0), cached_tokens = counts });
            }
            group.AsObject().Remove("sessions");
            group["cache_evidence"] = evidence;
        }
        result["near_full"] = near;
    }
    if (File.Exists(Local("restore/summary.json")))
    {
        var restore = Read(Local("restore/summary.json"))!.AsObject();
        if (File.Exists(Local("restore/responses.jsonl")))
        {
            var config = result.GetValueOrDefault("config") as JsonNode;
            int chunk = int.Parse(config?["LmcacheChunkTokens"]?.ToString() ?? "4096");
            var verification = Rows(Local("restore/responses.jsonl")).TakeLast(2).Select(r =>
            {
                var usage = r["response"]!["usage"]!;
                long prompt = (long)usage["prompt_tokens"]!;
                long cached = (long?)usage["prompt_tokens_details"]?["cached_tokens"] ?? 0;
                long eligible = prompt / chunk * chunk;
                return new { prompt_tokens = prompt, cached_tokens = cached, complete_chunk_tokens = eligible,
                    prompt_coverage = (double)cached / prompt, complete_chunk_coverage = eligible > 0 ? (double)cached / eligible : (double?)null };
            });
            restore["verification_requests"] = JsonSerializer.SerializeToNode(verification);
        }
        result["restore"] = restore;
    }
    if (File.Exists(Local("telemetry.jsonl")))
    {
        var telemetry = Rows(Local("telemetry.jsonl")).ToArray();
        var gpu = telemetry.Select(r => (string?)r["gpu"]).Where(s => !string.IsNullOrEmpty(s)).Select(s => s!.Split(',')).ToArray();
        static int MiB(string text) => int.Parse(text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)[0]);
        var host = telemetry.Where(r => r["host"] is JsonObject h && h.Count > 0 &&
            (double)r["unix_s"]! - ((double?)h["updatedUnixSeconds"] ?? 0) is >= 0 and <= 15);
        result["resources"] = new { peak_gpu_used_mib = gpu.Max(s => (int?)MiB(s[0])),
            minimum_gpu_free_mib = gpu.Min(s => (int?)MiB(s[1])), minimum_host_available_gib = host.Min(r => (double?)r["host"]!["availableGiB"]) };
    }
    var hashes = new SortedDictionary<string, string>(StringComparer.Ordinal);
    foreach (string path in Directory.EnumerateFiles(folder, "*.json", SearchOption.AllDirectories))
    {
        if (Path.GetFileName(path) is not ("status.json" or "summary.json" or "comparison.json" or "completed.json" or "host.json")) continue;
        using var stream = File.OpenRead(path);
        hashes[Path.GetRelativePath(folder, path).Replace(Path.DirectorySeparatorChar, '/')] = Convert.ToHexStringLower(SHA256.HashData(stream));
    }
    result["evidence_sha256"] = hashes;
    return result;
}

static List<object> Speed(IEnumerable<JsonObject> rows)
{
    var points = rows.GroupBy(r => (Concurrency: (int)r["concurrency"]!, Depth: (int)r["depth"]!)).OrderBy(g => g.Key);
    var speed = new List<object>();
    foreach (var point in points)
    {
        var valid = point.Where(r => (string?)r["status"] == "ok").ToArray();
        var item = new Dictionary<string, object> { ["concurrency"] = point.Key.Concurrency, ["depth"] = point.Key.Depth,
            ["recorded"] = point.Count(), ["valid"] = valid.Length };
        if (valid.Length > 0)
        {
            var rates = Rates(valid);
            item["read_tokens_s"] = rates.Read;
            item["write_tokens_s"] = rates.Write;
            var second = valid.Where(r => (int)r["repeat"]! == 1).ToArray();
            if (second.Length > 0)
            {
                rates = Rates(second);
                item["second_repetition"] = new { samples = second.Length, read_tokens_s = rates.Read, write_tokens_s = rates.Write };
            }
        }
        speed.Add(item);
    }
    return speed;
}

static (double Read, double Write) Rates(JsonObject[] rows) =>
    (rows.Sum(r => (long)r["read_tokens"]!) / rows.Sum(r => (double)r["timing"]!["pp_s"]!),
     rows.Sum(r => (long)r["usage"]!["completion_tokens"]! - 1) / rows.Sum(r => (double)r["timing"]!["decode_s"]!));
