#:property PublishAot=false
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

const string Revision = "50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14";
const string Manifest = "n1x-copy-manifest.json";
try
{
    switch (args)
    {
        case ["check", var folder]:
            Check(folder);
            break;
        case ["copy", var source, var target]:
            Copy(source, target);
            break;
        default:
            throw new ArgumentException("Expected check TABLE or copy SOURCE TARGET");
    }
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static void Check(string folder)
{
    using var json = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(folder, Manifest)));
    var manifest = json.RootElement;
    if (manifest.GetProperty("sourceRevision").GetString() != Revision)
        throw new InvalidDataException("Unexpected native PLE revision");
    var sizes = manifest.GetProperty("files").EnumerateArray().ToDictionary(
        file => file.GetProperty("name").GetString()!, file => file.GetProperty("bytes").GetInt64());
    for (int index = 5; index <= 37; index++)
    {
        string name = $"model-{index:D5}-of-00131.safetensors";
        if (!sizes.TryGetValue(name, out long size) || size <= 0 || new FileInfo(Path.Combine(folder, name)).Length != size)
            throw new InvalidDataException($"Missing or incomplete shard: {name}");
    }
    Console.WriteLine("Native PLE revision and file sizes verified.");
}

static string Digest(string path)
{
    using var input = File.OpenRead(path);
    return Convert.ToHexStringLower(SHA256.HashData(input));
}

static void Copy(string source, string target)
{
    var files = new DirectoryInfo(source).GetFiles().OrderBy(file => file.Name, StringComparer.Ordinal).ToArray();
    if (!files.Any(file => file.Extension == ".safetensors"))
        throw new InvalidDataException("Missing source table");
    long needed = files.Where(f => !File.Exists(Path.Combine(target, f.Name))).Sum(f => f.Length);
    if (new DriveInfo(Path.GetFullPath(target)).AvailableFreeSpace < needed + (1L << 30))
        throw new IOException("Insufficient Linux-volume space");
    var records = new List<object>();
    var elapsed = Stopwatch.StartNew();
    foreach (var file in files)
    {
        string destination = Path.Combine(target, file.Name);
        long length = file.Length;
        var modified = file.LastWriteTimeUtc;
        bool existing = File.Exists(destination);
        string hash;
        if (existing)
        {
            hash = Digest(file.FullName);
            if (new FileInfo(destination).Length != length || Digest(destination) != hash)
                throw new IOException($"Existing destination differs: {destination}; inspect before replacing");
        }
        else
        {
            string partial = destination + ".n1x-partial";
            using (var input = file.OpenRead())
            using (var output = File.Create(partial))
            using (var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
            {
                byte[] buffer = new byte[4 * 1024 * 1024];
                int count;
                while ((count = input.Read(buffer)) > 0)
                {
                    digest.AppendData(buffer, 0, count);
                    output.Write(buffer, 0, count);
                }
                output.Flush(true);
                hash = Convert.ToHexStringLower(digest.GetHashAndReset());
            }
            if (Digest(partial) != hash)
                throw new IOException($"Copy checksum mismatch: {partial}");
            File.Move(partial, destination);
        }
        file.Refresh();
        if (file.Length != length || file.LastWriteTimeUtc != modified)
            throw new IOException($"Source changed during copy: {file.FullName}");
        records.Add(new { name = file.Name, bytes = length, sha256 = hash });
        Console.WriteLine($"{file.Name}: {(existing ? "verified existing" : "copied and verified")}");
    }
    var manifest = new { sourceRevision = Revision, verification = "Source and destination SHA256 compared; original Windows files retained.", seconds = elapsed.Elapsed.TotalSeconds, files = records };
    string temporary = Path.Combine(target, "n1x-copy-manifest.partial");
    File.WriteAllText(temporary, JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }));
    File.Move(temporary, Path.Combine(target, Manifest), true);
    Console.WriteLine($"Completed {records.Count} files in {elapsed.Elapsed.TotalSeconds:F1}s");
}
