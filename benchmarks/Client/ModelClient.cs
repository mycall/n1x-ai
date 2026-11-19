using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;

namespace N1x.Benchmarks;

sealed class ModelClient : IDisposable
{
    readonly HttpClient http;
    readonly TimeSpan timeout;
    public ModelClient(string url, double seconds)
    {
        timeout = TimeSpan.FromSeconds(seconds);
        http = new(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri(url.TrimEnd('/') + "/"), Timeout = timeout };
    }
    public Task<string> Text(string path) => http.GetStringAsync(path);
    public void Dispose() => http.Dispose();
    public async Task<JsonNode?> Get(string path, object? body = null)
    {
        using var response = body == null ? await http.GetAsync(path) : await http.PostAsJsonAsync(path, body);
        response.EnsureSuccessStatusCode();
        string data = await response.Content.ReadAsStringAsync();
        return string.IsNullOrWhiteSpace(data) ? null : JsonNode.Parse(data);
    }

    public async Task<JsonObject> Generate(JsonObject request)
    {
        var time = Stopwatch.StartNew();
        using var cancel = new CancellationTokenSource(timeout);
        using var message = new HttpRequestMessage(HttpMethod.Post, "/v1/chat/completions") { Content = JsonContent.Create(request) };
        using var response = await http.SendAsync(message, HttpCompletionOption.ResponseHeadersRead, cancel.Token);
        response.EnsureSuccessStatusCode();
        using var reader = new StreamReader(await response.Content.ReadAsStreamAsync(cancel.Token));
        JsonNode? usage = null, metrics = new JsonObject();
        double? first = null, last = null, firstContent = null;
        var content = new StringBuilder();
        var reasoning = new StringBuilder();
        var tools = new SortedDictionary<int, JsonObject>();
        int packets = 0, chars = 0;
        string? finish = null;
        bool done = false;
        while (await reader.ReadLineAsync(cancel.Token) is string line)
        {
            if (!line.StartsWith("data:", StringComparison.Ordinal)) continue;
            string data = line[5..].Trim();
            if (data == "[DONE]") { done = true; break; }
            var e = JsonNode.Parse(data)!;
            if (e["usage"] is JsonObject { Count: > 0 } u) usage = u;
            if (e["metrics"] is JsonObject { Count: > 0 } m) metrics = m;
            foreach (var choice in e["choices"]?.AsArray() ?? [])
            {
                var delta = choice!["delta"];
                foreach (var call in delta?["tool_calls"]?.AsArray() ?? [])
                {
                    int index = (int?)call!["index"] ?? 0;
                    if (!tools.TryGetValue(index, out var item))
                        tools[index] = item = Data.Obj(new { id = (string?)null, type = "function", function = new { name = "", arguments = "" } });
                    if ((string?)call["id"] is { Length: > 0 } id) item["id"] = id;
                    foreach (string key in new[] { "name", "arguments" })
                        item["function"]![key] = (string?)item["function"]![key] + (string?)call["function"]?[key];
                }
                string text = (string?)delta?["content"] ?? "";
                string thought = (string?)delta?["reasoning"] ?? "";
                string other = (string?)delta?["reasoning_content"] ?? "";
                if (text.Length + thought.Length + other.Length > 0)
                {
                    double now = time.Elapsed.TotalSeconds;
                    first ??= now; last = now; packets++;
                    chars += (text + thought + other).EnumerateRunes().Count();
                    if (text.Length > 0) firstContent ??= now;
                    content.Append(text); reasoning.Append(thought.Length > 0 ? thought : other);
                }
                if ((string?)choice["finish_reason"] is { Length: > 0 } reason) finish = reason;
            }
        }
        var timing = Timing(usage, metrics, time.Elapsed.TotalSeconds, first);
        return Data.Obj(new
        {
            usage,
            metrics,
            timing,
            finish_reason = finish,
            content = content.ToString(),
            reasoning = reasoning.ToString(),
            tool_calls = tools.Values,
            first_content_s = firstContent,
            stream_done = done,
            generated_packets = packets,
            generated_chars = chars,
            client_ttft_s = first,
            client_first_to_last_s = last - first
        });
    }

    public static JsonObject Timing(JsonNode? usage, JsonNode? metrics, double elapsed, double? first)
    {
        double? pp = Data.Positive(metrics?["time_to_first_token_ms"]) / 1000, decode = Data.Positive(metrics?["generation_time_ms"]) / 1000;
        string? decodeSource = decode.HasValue ? "server-first-to-last-token" : null, ppSource = pp.HasValue ? "server-scheduled-to-first-token" : null;
        if (!decode.HasValue && first > 0 && first < elapsed) { decode = elapsed - first; decodeSource = "client-first-token-to-completion"; }
        if (!pp.HasValue && decode < elapsed) { pp = elapsed - decode; ppSource = "derived-e2e-minus-decode-includes-overhead"; }
        int? prompt = Data.Integer(usage?["prompt_tokens"]), completion = Data.Integer(usage?["completion_tokens"]);
        double? read = prompt >= 0 ? prompt / pp : null, write = completion > 1 ? (completion - 1) / decode : null;
        return Data.Obj(new
        {
            e2e_s = elapsed,
            pp_s = pp,
            decode_s = decode,
            pp_source = ppSource,
            decode_source = decodeSource,
            prompt_tokens = usage?["prompt_tokens"],
            completion_tokens = usage?["completion_tokens"],
            cached_tokens = usage?["prompt_tokens_details"]?["cached_tokens"],
            read_tks = read,
            write_tks = write,
            read_write_tks = new[] { read, write },
            aggregation = "per-request phase rates",
            read_basis = "full prompt including cached tokens",
            decode_token_offset = 1
        });
    }
}
