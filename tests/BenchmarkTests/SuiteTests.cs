using System.Text.Json.Nodes;
using N1x.Benchmarks;

static class SuiteTests
{
    public static void Run(string root)
    {
        string[] Args(params string[] args) => new BenchmarkSuite(args).ProbeArgs();
        var defaultArgs = Args("--suite", "agents");
        if (!defaultArgs.Contains("--agent-thinking") || !defaultArgs.Skip(Array.IndexOf(defaultArgs, "--agent-concurrency") + 1).Take(3).SequenceEqual(new[] { "1", "2", "4" }))
            throw new Exception("Agent routing defaults");
        var explicitArgs = Args("--suite", "agents", "--agent-sessions", "2", "--agent-turns", "12", "--agent-output-tokens", "8192", "--agent-concurrency", "1", "2");
        foreach (var (key, value) in new[] { ("sessions", "2"), ("turns", "12"), ("output-tokens", "8192") })
            if (explicitArgs[Array.IndexOf(explicitArgs, "--agent-" + key) + 1] != value) throw new Exception("Agent option routing");
        if (Args("--suite", "restores").Contains("--agent-concurrency")) throw new Exception("Unexpected restore controls");
        foreach (var options in new[] { new[] { "--suite", "agents", "--agent-output-tokens", "0" }, ["--suite", "agents", "--agent-concurrency", "17"], ["--suite", "restores", "--agent-turns", "12"] })
        {
            try { Args(options); throw new Exception("Expected invalid controls to fail"); } catch (ArgumentException) { }
        }
        string dir = Path.Combine(root, "aiperf"); Directory.CreateDirectory(Path.Combine(dir, "artifacts"));
        Data.Save(Path.Combine(dir, "expected.json"), new Dictionary<string, string[]> { { "session-0", ["ABC", "ABC", "ABC", "ABC"] } });
        foreach (bool truncate in new[] { false, true })
        {
            var raw = Enumerable.Range(0, 4).Select(turn =>
            {
                var packets = new[] { ("A", (string?)null), ("BC", truncate ? "length" : "stop") }.Select(pair => new { name = "data", value = Data.Obj(new { choices = new[] { new { delta = new { content = pair.Item1 }, finish_reason = pair.Item2 } } }).ToJsonString() });
                return Data.Obj(new
                {
                    metadata = new { benchmark_phase = "profiling", conversation_id = "session-0", turn_index = turn, request_start_ns = (turn + 1) * 1000000000L, request_end_ns = (turn + 2) * 1000000000L },
                    status = 200,
                    start_perf_ns = 100,
                    responses = new[] { new { perf_ns = 500000100, packets } }
                }).ToJsonString();
            });
            File.WriteAllLines(Path.Combine(dir, "artifacts/profile_export_raw.jsonl"), raw);
            var result = BenchmarkSuite.Accuracy(dir, 4);
            if ((int)result["correct"]! != (truncate ? 0 : 4) || (double)result["followup_mean_ttft_s"]! != .5 || (double)result["correct_turns_per_s"]! != (truncate ? 0 : 1))
                throw new Exception("AIPerf stream score");
            try { BenchmarkSuite.Accuracy(dir, 8); throw new Exception("Missing turns accepted"); } catch (InvalidDataException) { }
        }
    }
}
