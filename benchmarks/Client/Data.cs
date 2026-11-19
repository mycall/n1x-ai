using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

static class Data
{
    public static readonly JsonSerializerOptions Pretty = new() { WriteIndented = true };
    public static JsonObject Obj(object value) => JsonSerializer.SerializeToNode(value)!.AsObject();
    public static JsonObject Read(string path) => JsonNode.Parse(File.ReadAllText(path))!.AsObject();
    public static void Save(string path, object value) => File.WriteAllText(path, JsonSerializer.Serialize(value, Pretty) + "\n");
    public static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    public static int? Integer(JsonNode? node) => node is JsonValue v && v.TryGetValue<int>(out var i) ? i : null;
    public static double? Positive(JsonNode? node) => double.TryParse(node?.ToJsonString(), CultureInfo.InvariantCulture, out double n) && double.IsFinite(n) && n > 0 ? n : null;
    public static JsonObject Merge(JsonObject source, params JsonObject[] others)
    {
        var result = source.DeepClone().AsObject();
        foreach (var other in others)
            foreach (var (key, value) in other) result[key] = value?.DeepClone();
        return result;
    }
    public static void NewFolder(string path)
    {
        string full = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        var parent = Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        string empty = Directory.CreateDirectory(Path.Combine(parent.FullName, ".n1x-new-" + Guid.NewGuid().ToString("N"))).FullName;
        try { Directory.Move(empty, full); }
        finally { if (Directory.Exists(empty)) Directory.Delete(empty); }
    }
}

sealed class Options
{
    readonly Dictionary<string, List<string>> values = [];
    public Options(string[] args, string[] flags, string[] lists, string[] singles)
    {
        for (int i = 0; i < args.Length; i++)
        {
            string key = args[i];
            if ((!flags.Contains(key) && !lists.Contains(key) && !singles.Contains(key)) || !values.TryAdd(key, []))
                throw new ArgumentException($"Unknown or repeated argument: {key}");
            if (flags.Contains(key)) continue;
            do
            {
                if (++i == args.Length || args[i].StartsWith("--")) throw new ArgumentException($"Missing value for {key}");
                values[key].Add(args[i]);
            } while (lists.Contains(key) && i + 1 < args.Length && !args[i + 1].StartsWith("--"));
        }
    }
    public bool Has(string name) => values.ContainsKey(name);
    public string Get(string name, string? fallback = null) => values.TryGetValue(name, out var v) ? v.Single() : fallback ?? throw new ArgumentException("Missing " + name);
    public string[] List(string name) => values.TryGetValue(name, out var v) ? v.ToArray() : [];
    public int Int(string name, int fallback) => int.Parse(Get(name, fallback.ToString()), CultureInfo.InvariantCulture);
    public int[] Ints(string name, int fallback) => Has(name) ? List(name).Select(s => int.Parse(s, CultureInfo.InvariantCulture)).ToArray() : [fallback];
}
