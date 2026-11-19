using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class RecipeQueue
{
    public static async Task Run(string[] args)
    {
        string? directory = null, after = null;
        bool longRun = false, restore = false;
        var concurrency = new List<string>();
        var variants = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            string Value() => i + 1 < args.Length ? args[++i] : throw new ArgumentException("Missing value for " + args[i]);
            switch (args[i])
            {
                case "--directory": directory = Value(); break;
                case "--after": after = Value(); break;
                case "--long": longRun = true; break;
                case "--restore": restore = true; break;
                case "--long-concurrency":
                    while (i + 1 < args.Length && args[i + 1] is "2" or "4") concurrency.Add(args[++i]);
                    if (concurrency.Count == 0) throw new ArgumentException("Expected --long-concurrency 2 or 4");
                    break;
                default:
                    if (args[i].StartsWith("--")) throw new ArgumentException("Unknown argument " + args[i]);
                    variants.Add(args[i]); break;
            }
        }
        if (directory == null || after == null || variants.Count == 0) throw new ArgumentException("Expected --directory DIRECTORY --after PREVIOUS VARIANT...");
        string folder = Path.GetFullPath(directory);
        while (true)
        {
            try
            {
                var state = Data.Read(Path.Combine(folder, after, "status.json"));
                if ((string?)state["stage"] == "finished")
                {
                    if ((bool?)state["success"] != true) throw new InvalidOperationException("Previous control failed; queue stopped");
                    break;
                }
            }
            catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException or JsonException) { }
            await Task.Delay(5000);
        }
        var results = new List<object>();
        foreach (string name in variants)
        {
            if (File.Exists(Path.Combine(folder, "STOP"))) break;
            var trial = new List<string> { "--variant", Path.Combine(folder, name + ".json"), "--out", Path.Combine(folder, name), "--name", name };
            if (longRun) { trial.AddRange(["--long", "--long-concurrency"]); trial.AddRange(concurrency.Count > 0 ? concurrency : ["2", "4"]); }
            if (restore) trial.Add("--restore");
            int code = 0;
            try { await RecipeTrial.Run(trial.ToArray()); }
            catch (Exception ex) { Console.Error.WriteLine(ex.Message); code = 1; }
            results.Add(new { name, returncode = code }); Data.Save(Path.Combine(folder, "queue-results.json"), results);
        }
    }
}
