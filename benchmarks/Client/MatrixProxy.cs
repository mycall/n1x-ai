using System.Diagnostics;
using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

sealed class MatrixProxy : IAsyncDisposable
{
    readonly HttpListener listener = new();
    readonly HttpClient client;
    readonly string folder, runId;
    readonly Task loop;
    readonly HashSet<Task> active = [];
    readonly object sync = new();
    List<JsonObject> rows = [];
    string wave = "";
    public MatrixProxy(string url, int port, string folder, string runId)
    {
        this.folder = folder; this.runId = runId;
        client = new(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri(url), Timeout = TimeSpan.FromHours(4) };
        listener.Prefixes.Add($"http://127.0.0.1:{port}/"); listener.Start(); loop = Listen();
    }
    internal void Begin(string name) { lock (sync) { wave = name; rows = []; } }
    internal JsonObject[] Responses() { lock (sync) return rows.ToArray(); }
    async Task Listen()
    {
        while (listener.IsListening)
        {
            HttpListenerContext ctx;
            try { ctx = await listener.GetContextAsync(); } catch (Exception) when (!listener.IsListening) { return; }
            var task = Forward(ctx);
            lock (sync) active.Add(task);
            _ = task.ContinueWith(t => { lock (sync) active.Remove(t); }, TaskScheduler.Default);
        }
    }
    async Task Forward(HttpListenerContext ctx)
    {
        var clock = Stopwatch.StartNew(); JsonObject? row = null;
        try
        {
            string uri = ctx.Request.Url!.PathAndQuery;
            using var message = new HttpRequestMessage(ctx.Request.HttpMethod == "POST" ? HttpMethod.Post : HttpMethod.Get, uri);
            if (message.Method == HttpMethod.Post)
            {
                var body = (await JsonNode.ParseAsync(ctx.Request.InputStream))!.AsObject();
                string salt = runId + "-" + wave + "-" + Guid.NewGuid().ToString("N");
                body["cache_salt"] = salt; message.Content = JsonContent.Create(body);
                row = Data.Obj(new { wave, salt, started_utc = DateTimeOffset.UtcNow, status = (int?)null, usage = (object?)null, metrics = (object?)null, finish_reason = (string?)null, done = false, prompt_sha256 = Data.Hash((string)body["prompt"]!) });
            }
            using var response = await client.SendAsync(message, HttpCompletionOption.ResponseHeadersRead);
            ctx.Response.StatusCode = (int)response.StatusCode;
            ctx.Response.ContentType = response.Content.Headers.ContentType?.ToString();
            if (row != null) row["status"] = (int)response.StatusCode;
            using var source = await response.Content.ReadAsStreamAsync();
            var buffer = new byte[32768]; using var line = new MemoryStream();
            int count;
            while ((count = await source.ReadAsync(buffer)) != 0)
            {
                if (row != null)
                    for (int offset = 0; offset < count;)
                    {
                        int end = Array.IndexOf(buffer, (byte)10, offset, count - offset);
                        if (end < 0) { line.Write(buffer, offset, count - offset); break; }
                        line.Write(buffer, offset, end - offset);
                        string text = Encoding.UTF8.GetString(line.GetBuffer(), 0, (int)line.Length); line.SetLength(0);
                        ReadEvent(row, text); offset = end + 1;
                    }
                await ctx.Response.OutputStream.WriteAsync(buffer.AsMemory(0, count));
                await ctx.Response.OutputStream.FlushAsync();
            }
        }
        catch (Exception ex) { if (row != null) row["error"] = ex.Message; else Console.Error.WriteLine(ex.Message); }
        finally
        {
            if (row != null)
            {
                row["elapsed_s"] = clock.Elapsed.TotalSeconds;
                lock (sync) { rows.Add(row); File.AppendAllText(Path.Combine(folder, "responses.jsonl"), row.ToJsonString() + "\n"); }
            }
            ctx.Response.Close();
        }
    }
    internal static void ReadEvent(JsonObject row, string line)
    {
        if (!line.StartsWith("data:", StringComparison.Ordinal)) return;
        string data = line[5..].Trim();
        if (data == "[DONE]") { row["done"] = true; return; }
        var item = JsonNode.Parse(data)!;
        foreach (string key in new[] { "usage", "metrics" })
            if (item[key] is JsonObject { Count: > 0 } value) row[key] = value.DeepClone();
        foreach (var choice in item["choices"]?.AsArray() ?? [])
            if ((string?)choice!["finish_reason"] is { Length: > 0 } finish) row["finish_reason"] = finish;
    }
    public async ValueTask DisposeAsync()
    {
        listener.Stop(); await loop;
        Task[] pending; lock (sync) pending = active.ToArray();
        await Task.WhenAll(pending); listener.Close(); client.Dispose();
    }
}
