#:property PublishAot=false
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

try
{
    var options = new Dictionary<string, string>();
    for (int i = 0; i < args.Length; i += 2)
    {
        if (i + 1 >= args.Length || args[i] is not ("--model" or "--manifest" or "--out" or "--wait"))
            throw new ArgumentException("Expected --model DIR --manifest FILE --out FILE [--wait SECONDS]");
        options[args[i]] = args[i + 1];
    }
    string root = ResolvePath(Path.GetFullPath(options["--model"]));
    string output = options["--out"];
    using var manifest = JsonDocument.Parse(File.ReadAllText(options["--manifest"]));
    var files = manifest.RootElement.EnumerateArray().Select(row => new
    {
        Name = row.GetProperty("path").GetString()!,
        Size = row.GetProperty("size").GetInt64(),
        Hash = row.GetProperty("lfs").GetProperty("oid").GetString()
    }).ToArray();
    string Shard(string name)
    {
        string path = ResolvePath(Path.GetFullPath(name, root));
        string relative = Path.GetRelativePath(root, path);
        if (Path.IsPathRooted(relative) || relative == ".." || relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Manifest path outside model directory");
        return path;
    }
    int wait = int.Parse(options.GetValueOrDefault("--wait", "0"));
    var timer = Stopwatch.StartNew();
    while (true)
    {
        var missing = files.Where(row => !File.Exists(Shard(row.Name)) || new FileInfo(Shard(row.Name)).Length != row.Size).ToArray();
        if (missing.Length == 0) break;
        if (timer.Elapsed.TotalSeconds >= wait)
            throw new IOException($"Missing or incomplete shards: {string.Join(", ", missing.Select(row => row.Name))}");
        Thread.Sleep(TimeSpan.FromSeconds(10));
    }
    var results = new List<object>();
    void Save(bool complete)
    {
        string text = JsonSerializer.Serialize(new { complete, files = results }, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(output, text + "\n");
    }
    foreach (var file in files)
    {
        using var stream = File.OpenRead(Shard(file.Name));
        string sha256 = Convert.ToHexStringLower(SHA256.HashData(stream));
        var result = new { path = file.Name, size = stream.Length, sha256, verified = sha256 == file.Hash };
        results.Add(result);
        Save(false);
        Console.WriteLine(JsonSerializer.Serialize(result));
        if (!result.verified) throw new InvalidDataException($"Checkpoint checksum mismatch: {file.Name}");
    }
    using var index = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "model.safetensors.index.json")));
    var indexed = index.RootElement.GetProperty("weight_map").EnumerateObject().Select(p => p.Value.GetString()).ToHashSet();
    if (!indexed.SetEquals(files.Select(f => f.Name)))
        throw new InvalidDataException("Shard inventory differs from checkpoint index");
    Save(true);
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

// Resolve parent-directory links as well as the shard itself before opening it.
static string ResolvePath(string absolute)
{
    string? parent = Path.GetDirectoryName(absolute);
    if (parent == null) return absolute;
    string path = Path.Combine(ResolvePath(parent), Path.GetFileName(absolute));
    FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
    return info.LinkTarget == null ? path : ResolvePath(info.ResolveLinkTarget(true)!.FullName);
}
