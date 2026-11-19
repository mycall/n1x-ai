using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

// Keep the installed Transformers tokenizer and its model-specific chat template
// in the serving environment. Calibration and workload generation live in C#.
sealed class MatrixTokenizer : IDisposable
{
    const string Adapter = """
import json, sys
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained(sys.argv[1], local_files_only=True)
for line in sys.stdin:
    messages = json.loads(line)
    text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False, enable_thinking=True, reasoning_effort='xhigh')
    print(json.dumps([text, len(tokenizer.encode(text, add_special_tokens=False))]), flush=True)
""";
    readonly Process process;
    public MatrixTokenizer(string path)
    {
        var start = new ProcessStartInfo("python3") { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardOutput = true };
        foreach (string arg in new[] { "-u", "-c", Adapter, path }) start.ArgumentList.Add(arg);
        process = Process.Start(start)!;
    }
    internal async Task<(string Prompt, int Count)> Prepare(int target, string identity)
    {
        string[] verbs = ["validates input", "reads indexed records", "schedules work", "stores responses", "checks dependencies", "rebuilds indexes", "routes requests", "tracks latency", "restores state"];
        var rng = new MatrixRandom(identity); var filler = new StringBuilder();
        for (int i = 0; i < target / 10 + 100; i++)
            filler.Append($"Record {i}: The service {verbs[rng.Below(verbs.Length)]} for partition {rng.Below(10000)} with revision {rng.Below(10000)}.\n");
        string lead = $"Reference stream {identity}.\n";
        const string tail = "\nContinue with a detailed technical explanation of request handling and data storage.\n";
        int lo = 0, hi = filler.Length, count = 0; string? best = null;
        while (lo <= hi)
        {
            int mid = (lo + hi) / 2;
            var messages = new[] { new { role = "system", content = "Read the reference notes. Continue writing detailed reference notes when asked." }, new { role = "user", content = lead + filler.ToString(0, mid) + tail } };
            await process.StandardInput.WriteLineAsync(System.Text.Json.JsonSerializer.Serialize(messages));
            string reply = await process.StandardOutput.ReadLineAsync() ?? throw new IOException("Tokenizer exited during calibration");
            var result = JsonNode.Parse(reply)!;
            if ((int)result[1]! <= target) { best = (string)result[0]!; count = (int)result[1]!; lo = mid + 1; }
            else hi = mid - 1;
        }
        if (best == null || target - count > 4) throw new InvalidDataException($"Prompt calibration failed: {target}, {count}");
        return (best, count);
    }
    public void Dispose() { process.StandardInput.Close(); process.WaitForExit(); process.Dispose(); }
}

static class SpeedMatrix
{
    static void Save(string file, object value) { Data.Save(file + ".tmp", value); File.Move(file + ".tmp", file, true); }
    public static async Task Run(string[] args)
    {
        var options = new Options(args, ["--smoke"], ["--contexts"], ["--base", "--model", "--tokenizer", "--out", "--repeats", "--proxy-port"]);
        string folder = Path.GetFullPath(options.Get("--out")), model = options.Get("--model", "qwen/qwen38fn-best"), url = options.Get("--base", "http://127.0.0.1:8000"), tokenizer = options.Get("--tokenizer", "/model");
        int[] contexts = options.Has("--contexts") ? options.Ints("--contexts", 4096) : [4096, 8192, 65536, 261632];
        int repeats = options.Int("--repeats", 3), port = options.Int("--proxy-port", 18001);
        foreach (string key in new[] { "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "VLLM_NO_USAGE_STATS", "HF_HUB_DISABLE_TELEMETRY" }) Environment.SetEnvironmentVariable(key, "1");
        Directory.CreateDirectory(folder);
        string PathTo(string file) => Path.Combine(folder, file);
        string path = PathTo("manifest.json"); JsonObject manifest;
        if (File.Exists(path)) manifest = Data.Read(path);
        else
        {
            var versions = await RecipeHost.Execute(folder, ["python3", "-c", "import importlib.metadata as m,json; print(json.dumps({k:m.version(k) for k in ['vllm','torch','transformers','pandas','aiohttp']}))"], 60);
            if (versions.Code != 0) throw new IOException(versions.Error);
            var packages = JsonNode.Parse(versions.Output)!;
            manifest = Data.Obj(new
            {
                protocol = "n1x-vllm-speed-matrix-v1",
                run_id = Guid.NewGuid().ToString("N"),
                started_utc = DateTimeOffset.UtcNow,
                vllm = packages["vllm"],
                model,
                contexts,
                concurrency = Enumerable.Range(1, 8),
                repeats,
                output_tokens = 512,
                seed = 42,
                thinking = true,
                reasoning_effort = "xhigh",
                cold_prefixes = true,
                finished = Array.Empty<string>(),
                packages,
                source_sha256 = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(SpeedMatrix).Assembly.Location)))
            });
            Save(path, manifest);
        }
        if (!contexts.SequenceEqual(manifest["contexts"]!.AsArray().Select(n => (int)n!)) || repeats != (int)manifest["repeats"]! || model != (string)manifest["model"]!)
            throw new InvalidDataException("Resume requires matching model, contexts and repeats");
        using var client = new ModelClient(url, 14400); await client.Text("/health");
        using var tokens = new MatrixTokenizer(tokenizer);
        await using var proxy = new MatrixProxy(url, port, folder, (string)manifest["run_id"]!);
        var cells = (from r in Enumerable.Range(0, repeats) from c in Enumerable.Range(1, 8) from n in contexts select (r, c, n)).ToList();
        var rng = new MatrixRandom(42);
        for (int i = cells.Count - 1; i > 0; i--) { int j = rng.Below(i + 1); (cells[i], cells[j]) = (cells[j], cells[i]); }
        cells.InsertRange(0, [(-1, 8, 8192), (-1, 1, contexts.Max())]); if (options.Has("--smoke")) cells = [(0, 1, 4096)];
        var finished = manifest["finished"]!.AsArray();
        foreach (var (repeat, c, n) in cells)
        {
            string name = $"r{repeat + 1}-c{c}-n{n}", dataset = PathTo(name + ".jsonl");
            if (finished.Any(f => (string?)f == name)) continue;
            Console.WriteLine($"{DateTimeOffset.UtcNow:u} preparing {name}");
            var counts = new List<int>();
            using (var writer = File.CreateText(dataset))
                for (int i = 0; i < c; i++)
                {
                    var item = await tokens.Prepare(n, $"{manifest["run_id"]}-{name}-{i}");
                    await writer.WriteLineAsync(Data.Obj(new { prompt = item.Prompt, output_tokens = 512 }).ToJsonString()); counts.Add(item.Count);
                }
            proxy.Begin(name);
            string[] command = ["vllm","bench","serve","--backend","openai","--base-url",$"http://127.0.0.1:{port}","--endpoint","/v1/completions","--model",model,"--tokenizer",tokenizer,
                "--dataset-name","custom","--dataset-path",dataset,"--skip-chat-template","--custom-output-len","512","--num-prompts",c.ToString(),"--max-concurrency",c.ToString(),"--request-rate","inf",
                "--num-warmups","0","--ready-check-timeout-sec","0","--ignore-eos","--temperature","0","--seed","42","--save-result","--save-detailed","--result-dir",folder,"--result-filename",name+"-vllm.json","--disable-tqdm"];
            Save(PathTo(name + "-command.json"), new { command, counts });
            File.WriteAllText(PathTo(name + "-before.prom"), await client.Text("/metrics"));
            var start = Stopwatch.StartNew(); var result = await RecipeHost.Execute(folder, command, 14400, PathTo(name + ".log"));
            File.WriteAllText(PathTo(name + "-after.prom"), await client.Text("/metrics"));
            string resultPath = PathTo(name + "-vllm.json"); var data = File.Exists(resultPath) ? Data.Read(resultPath) : new JsonObject();
            var responses = proxy.Responses();
            bool valid = result.Code == 0 && (int?)data["completed"] == c && (int?)data["failed"] == 0 && responses.Length == c && responses.All(r =>
                (bool?)r["done"] == true && (int?)r["status"] == 200 && (string?)r["finish_reason"] == "length" && (int?)r["usage"]?["completion_tokens"] == 512 &&
                (int?)r["usage"]?["prompt_tokens"] >= n - 4 && (int?)r["usage"]?["prompt_tokens"] <= n && (int?)r["usage"]?["prompt_tokens_details"]?["cached_tokens"] == 0 && Data.Positive(r["metrics"]?["generation_time_ms"]) != null);
            Save(PathTo(name + "-receipt.json"), new { name, repeat = repeat + 1, concurrency = c, warmup = repeat < 0, target_input = n, counts, elapsed_s = start.Elapsed.TotalSeconds, valid, exit_code = result.Code, responses });
            if (!valid) throw new InvalidDataException("Invalid benchmark wave: " + name);
            finished.Add(name); manifest["updated_utc"] = DateTimeOffset.UtcNow; Save(path, manifest); File.Delete(dataset);
        }
        manifest["completed_utc"] = DateTimeOffset.UtcNow; Save(path, manifest);
    }
}
