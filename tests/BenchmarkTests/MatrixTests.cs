using N1x.Benchmarks;

static class MatrixTests
{
    public static void Run(string folder)
    {
        void CheckSeed(MatrixRandom random, int[] expected)
        {
            if (!expected.SequenceEqual(Enumerable.Range(0, expected.Length).Select(_ => random.Below(10000))))
                throw new Exception("Matrix corpus no longer matches archived runs");
        }
        CheckSeed(new MatrixRandom(42), [1824, 409, 4506, 4012, 3657, 2286]);
        CheckSeed(new MatrixRandom("test-stream"), [9083, 7975, 9835, 2365, 6309, 1007]);
        var receipt = new System.Text.Json.Nodes.JsonObject();
        MatrixProxy.ReadEvent(receipt, """data: {"choices":[{"finish_reason":"length"}],"usage":{"completion_tokens":512}}""");
        MatrixProxy.ReadEvent(receipt, "data: [DONE]");
        if ((string?)receipt["finish_reason"] != "length" || (bool?)receipt["done"] != true || (int?)receipt["usage"]?["completion_tokens"] != 512)
            throw new Exception("Matrix SSE receipt lost usage or finish evidence");
        Directory.CreateDirectory(folder);
        string PathTo(string file) => Path.Combine(folder, file);
        Data.Save(PathTo("manifest.json"), new { protocol = "test", repeats = 2, contexts = new[] { 4096 }, concurrency = new[] { 1 } });
        void Receipt(int index, int cached = 0)
        {
            string name = $"r{index}-c1-n4096";
            int pp = index == 1 ? 2 : 6, decode = index == 1 ? 10 : 30;
            var response = new
            {
                done = true,
                status = 200,
                finish_reason = "length",
                usage = new { prompt_tokens = 4096, completion_tokens = 512, prompt_tokens_details = new { cached_tokens = cached } },
                metrics = new { time_to_first_token_ms = pp * 1000, generation_time_ms = decode * 1000, queue_time_ms = 100 }
            };
            Data.Save(PathTo(name + "-receipt.json"), new { name, repeat = index, concurrency = 1, target_input = 4096, valid = true, responses = new[] { response } });
            Data.Save(PathTo(name + "-vllm.json"), new { duration = pp + decode, ttfts = new[] { pp }, latencies = new[] { pp + decode }, mean_tpot_ms = decode / 511.0 * 1000 });
        }
        void Reject(string message)
        {
            try { MatrixReport.Summarize(folder, false); }
            catch (InvalidDataException ex) when (ex.Message.Contains(message)) { return; }
            throw new Exception("Expected matrix validation error: " + message);
        }
        Receipt(1);
        Reject("Incomplete");
        if ((bool)MatrixReport.Summarize(folder, true)["complete"]!) throw new Exception("Missing wave marked complete");
        Receipt(2);
        var report = MatrixReport.Summarize(folder, false);
        var cell = report["cells"]![0]!;
        if ((int)report["measured_requests"]! != 2 || (bool)report["complete"]! != true ||
            (double)cell["read_tks"]! != 8192.0 / 8 || (double)cell["write_tks"]! != 1022.0 / 40 ||
            (double)cell["common_output_throughput"]! != 1024.0 / 48 ||
            (double)cell["common_output_wave_range"]![0]! != 512.0 / 36 || (double)cell["common_output_wave_range"]![1]! != 512.0 / 12)
            throw new Exception("Incorrect matrix phase weighting or throughput");
        Receipt(1, 4096);
        Reject("Invalid response");
        Receipt(1);
        File.WriteAllText(PathTo("r1-c1-n4096-before.prom"), "vllm:request_success_total 0\n");
        File.WriteAllText(PathTo("r1-c1-n4096-after.prom"), "vllm:request_success_total 2\n");
        Reject("Unexpected server completion count");
    }
}
