#:property PublishAot=false
using System.Text.Json;
using System.Text.Json.Nodes;

try
{
    if (args.Length != 2) throw new ArgumentException("Expected TARGET OUTPUT");
    string target = Path.GetFullPath(args[0]);
    string output = Path.GetFullPath(args[1]);
    if (Directory.Exists(output) || File.Exists(output))
        throw new IOException("Draft destination already exists; use a fresh directory");
    var config = JsonNode.Parse(File.ReadAllText(Path.Combine(target, "config.json")))!.AsObject();
    var text = config["text_config"] ?? config;
    if ((int?)text["num_experts_per_tok"] != 5 || (int?)text["shared_expert_intermediate_size"] != 1280)
        throw new InvalidDataException("Expected FP4-Local-AZ five-expert target with padded MTP shared expert");
    text["num_experts_per_tok"] = 10;
    using var index = JsonDocument.Parse(File.ReadAllText(Path.Combine(target, "model.safetensors.index.json")));
    var tensors = index.RootElement.GetProperty("weight_map").EnumerateObject()
        .Where(p => p.Name.StartsWith("mtp.", StringComparison.Ordinal) || p.Name.StartsWith("lm_head.", StringComparison.Ordinal) || p.Name.EndsWith("embed_tokens.weight", StringComparison.Ordinal))
        .ToDictionary(p => p.Name, p => p.Value.GetString()!);
    if (!tensors.Keys.Any(k => k.StartsWith("mtp.", StringComparison.Ordinal)))
        throw new InvalidDataException("No MTP tensors found");
    string[] items = Directory.GetFileSystemEntries(target);
    // Publish only after every link and both JSON files are ready.
    string staging = output + "." + Guid.NewGuid().ToString("N") + ".partial";
    Directory.CreateDirectory(staging);
    try
    {
        foreach (string path in items)
        {
            string name = Path.GetFileName(path);
            if (name is "config.json" or "model.safetensors.index.json" or ".cache") continue;
            string link = Path.Combine(staging, name);
            if (Directory.Exists(path)) Directory.CreateSymbolicLink(link, path);
            else File.CreateSymbolicLink(link, path);
        }
        File.WriteAllText(Path.Combine(staging, "config.json"), config.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n");
        var draftIndex = new { metadata = new JsonObject(), weight_map = tensors };
        File.WriteAllText(Path.Combine(staging, "model.safetensors.index.json"), JsonSerializer.Serialize(draftIndex) + "\n");
        Directory.Move(staging, output);
    }
    finally
    {
        if (Directory.Exists(staging)) Directory.Delete(staging, true);
    }
    Console.WriteLine(JsonSerializer.Serialize(new { draft = args[1], tensors = tensors.Count, shards = tensors.Values.Distinct().Order(StringComparer.Ordinal) }));
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
