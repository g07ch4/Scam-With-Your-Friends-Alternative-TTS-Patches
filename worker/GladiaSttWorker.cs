// Drop-in replacement for the game's Moonshine streaming speech helper
// (StreamingAssets/Moonshine/runtime/ArmSpeechWorker.exe) that sends the player's speech to the
// Gladia speech-to-text API (https://gladia.io) using the player's own API key.
//
// Game <-> worker protocol (BinaryReader/BinaryWriter over stdin/stdout, little endian;
// text = i32 byte length + UTF-8 bytes):
//   1                                         -> 1, "X64"                        (hello)
//   1 model:text language:text n:i32 n*f32    -> 1, transcript:text, conf:f32    (transcribe, 16 kHz mono)
//   anything else                             -> 4 message:text
// An error reply (4) makes the game turn speech recognition off for the whole session, so
// network or API problems are answered with an empty transcript instead and written to gladia.log.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

static class Worker
{
    const int Rate = 16000;
    const int MaxSamples = 480000;   // the game never sends more than 30 s
    const int MaxText = 32768;
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 64 << 20 };

    static Dictionary<string, object> config;
    static string logPath;
    static bool hello;

    static int Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        logPath = Path.Combine(dir, "gladia.log");
        var output = new BinaryWriter(Console.OpenStandardOutput());
        var input = new BinaryReader(Console.OpenStandardInput());
        ServicePointManager.Expect100Continue = false;
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        config = LoadConfig(Path.Combine(dir, "gladia.json"));
        while (true)
        {
            int command;
            try { command = input.ReadInt32(); }
            catch (EndOfStreamException) { return 0; }

            if (command == 1 && !hello)
            {
                hello = true;
                output.Write(1);
                WriteText(output, "X64");
                output.Flush();
                Log("started; mode=" + Str("mode", "prerecorded") + (ApiKey() == "" ? " (NO API KEY)" : ""));
            }
            else if (command == 1)
            {
                string model = ReadText(input);   // local Moonshine model folder - unused
                string language = ReadText(input);
                int count = input.ReadInt32();
                if (count < 0 || count > MaxSamples) return 1;
                byte[] raw = input.ReadBytes(count * 4);
                if (raw.Length != count * 4) return 0;
                var samples = new float[count];
                Buffer.BlockCopy(raw, 0, samples, 0, raw.Length);

                string text = "";
                float confidence = 0f;
                var watch = Stopwatch.StartNew();
                try
                {
                    Transcribe(samples, language, out text, out confidence);
                    Log(string.Format(CultureInfo.InvariantCulture, "ok lang={0} audio={1:F1}s took={2:F2}s conf={3:F2} text={4}",
                        language, count / (double)Rate, watch.Elapsed.TotalSeconds, confidence, Bool("log_text", true) ? Quote(text) : "(hidden)"));
                }
                catch (Exception e)
                {
                    text = ""; confidence = 0f;
                    Log(string.Format(CultureInfo.InvariantCulture, "FAILED lang={0} audio={1:F1}s took={2:F2}s: {3}",
                        language, count / (double)Rate, watch.Elapsed.TotalSeconds, Describe(e)));
                }
                if (Utf8.GetByteCount(text) > MaxText) text = text.Substring(0, MaxText / 4);
                output.Write(1);
                WriteText(output, text);
                output.Write(Math.Max(0f, Math.Min(1f, confidence)));
                output.Flush();
            }
            else
            {
                output.Write(4);
                WriteText(output, "The Gladia speech helper only supports speech recognition.");
                output.Flush();
                return 1;
            }
        }
    }

    // ------------------------------------------------------------------ protocol

    static string ReadText(BinaryReader input)
    {
        int length = input.ReadInt32();
        if (length < 0 || length > MaxText) throw new InvalidDataException("Invalid text length.");
        byte[] bytes = input.ReadBytes(length);
        if (bytes.Length != length) throw new EndOfStreamException();
        return Utf8.GetString(bytes);
    }

    static void WriteText(BinaryWriter output, string text)
    {
        byte[] bytes = Utf8.GetBytes(text ?? "");
        output.Write(bytes.Length);
        output.Write(bytes);
    }

    // ------------------------------------------------------------------ Gladia

    static void Transcribe(float[] samples, string gameLanguage, out string text, out float confidence)
    {
        if (ApiKey() == "") throw new Exception("no API key - set api_key in gladia.json");
        string language = Str("language", "");
        if (language == "") language = gameLanguage ?? "";
        language = language.Trim().ToLowerInvariant();
        if (language == "auto") language = "";
        byte[] pcm = ToPcm16(samples);
        if (Str("mode", "prerecorded").Equals("live", StringComparison.OrdinalIgnoreCase))
            TranscribeLive(pcm, language, out text, out confidence);
        else
            TranscribePrerecorded(pcm, language, out text, out confidence);
        text = (text ?? "").Trim();
    }

    static Dictionary<string, object> LanguageConfig(string language)
    {
        var languages = new ArrayList();
        if (language != "") languages.Add(language);
        return new Dictionary<string, object> { { "languages", languages }, { "code_switching", Bool("code_switching", false) } };
    }

    static void TranscribePrerecorded(byte[] pcm, string language, out string text, out float confidence)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(Num("timeout_seconds", 20));
        string baseUrl = BaseUrl();

        // 1. upload the utterance as a WAV file
        string boundary = "----swyf" + Guid.NewGuid().ToString("N");
        var body = new MemoryStream();
        byte[] head = Utf8.GetBytes("--" + boundary + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"speech.wav\"\r\n" +
                                    "Content-Type: audio/wav\r\n\r\n");
        body.Write(head, 0, head.Length);
        byte[] wav = Wav(pcm);
        body.Write(wav, 0, wav.Length);
        byte[] tail = Utf8.GetBytes("\r\n--" + boundary + "--\r\n");
        body.Write(tail, 0, tail.Length);
        var upload = Request("POST", baseUrl + "/v2/upload", "multipart/form-data; boundary=" + boundary, body.ToArray(), deadline);
        string audioUrl = Field(upload, "audio_url") as string;
        if (string.IsNullOrEmpty(audioUrl)) throw new Exception("upload returned no audio_url");

        // 2. start the transcription
        var request = new Dictionary<string, object> { { "audio_url", audioUrl }, { "language_config", LanguageConfig(language) } };
        if (Str("model", "") != "") request["model"] = Str("model", "");
        Merge(request, "extra_body");
        var job = Request("POST", baseUrl + "/v2/pre-recorded", "application/json", Utf8.GetBytes(Json.Serialize(request)), deadline);
        string id = Field(job, "id") as string;
        if (string.IsNullOrEmpty(id)) throw new Exception("pre-recorded init returned no id");

        // 3. poll for the result
        int interval = (int)Num("poll_interval_ms", 250);
        while (true)
        {
            if (DateTime.UtcNow > deadline) throw new TimeoutException("no result within timeout_seconds");
            Thread.Sleep(interval);
            var result = Request("GET", baseUrl + "/v2/pre-recorded/" + Uri.EscapeDataString(id), null, null, deadline);
            string status = Field(result, "status") as string;
            if (status == "error") throw new Exception("transcription failed, error_code " + Field(result, "error_code"));
            if (status != "done") continue;
            var transcription = Field(Field(result, "result"), "transcription");
            text = Field(transcription, "full_transcript") as string ?? "";
            confidence = AverageConfidence(Field(transcription, "utterances") as IEnumerable, text);
            return;
        }
    }

    static void TranscribeLive(byte[] pcm, string language, out string text, out float confidence)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(Num("timeout_seconds", 20));
        var request = new Dictionary<string, object> {
            { "encoding", "wav/pcm" }, { "sample_rate", Rate }, { "bit_depth", 16 }, { "channels", 1 },
            { "language_config", LanguageConfig(language) },
            { "messages_config", new Dictionary<string, object> { { "receive_partial_transcripts", false }, { "receive_final_transcripts", true } } } };
        if (Str("live_endpointing", "") != "") request["endpointing"] = Num("live_endpointing", 0.05);
        Merge(request, "extra_body");
        string region = Str("live_region", "");
        var session = Request("POST", BaseUrl() + "/v2/live" + (region != "" ? "?region=" + Uri.EscapeDataString(region) : ""),
                              "application/json", Utf8.GetBytes(Json.Serialize(request)), deadline);
        string url = Field(session, "url") as string;
        if (string.IsNullOrEmpty(url)) throw new Exception("live init returned no url");

        var parts = new List<string>();
        var confidences = new List<double>();
        using (var socket = new ClientWebSocket())
        using (var cancel = new CancellationTokenSource(Remaining(deadline)))
        {
            socket.ConnectAsync(new Uri(url), cancel.Token).Wait();
            const int chunk = 3200; // 100 ms
            for (int at = 0; at < pcm.Length; at += chunk)
                socket.SendAsync(new ArraySegment<byte>(pcm, at, Math.Min(chunk, pcm.Length - at)), WebSocketMessageType.Binary, true, cancel.Token).Wait();
            byte[] stop = Utf8.GetBytes("{\"type\":\"stop_recording\"}");
            socket.SendAsync(new ArraySegment<byte>(stop), WebSocketMessageType.Text, true, cancel.Token).Wait();

            var buffer = new byte[65536];
            var message = new MemoryStream();
            while (socket.State == WebSocketState.Open || socket.State == WebSocketState.CloseSent)
            {
                WebSocketReceiveResult received;
                try { received = socket.ReceiveAsync(new ArraySegment<byte>(buffer), cancel.Token).Result; }
                catch (AggregateException e)
                {
                    if (cancel.IsCancellationRequested) throw new TimeoutException("no end of session within timeout_seconds");
                    throw e.InnerException;
                }
                if (received.MessageType == WebSocketMessageType.Close) break;
                message.Write(buffer, 0, received.Count);
                if (!received.EndOfMessage) continue;
                string json = Utf8.GetString(message.ToArray());
                message.SetLength(0);
                object parsed;
                try { parsed = Json.DeserializeObject(json); } catch { continue; }
                string type = Field(parsed, "type") as string;
                if (type == "transcript" && Field(Field(parsed, "data"), "is_final") is bool && (bool)Field(Field(parsed, "data"), "is_final"))
                {
                    var utterance = Field(Field(parsed, "data"), "utterance");
                    string part = Field(utterance, "text") as string;
                    if (!string.IsNullOrEmpty(part)) parts.Add(part.Trim());
                    object c = Field(utterance, "confidence");
                    if (c != null) confidences.Add(Convert.ToDouble(c, CultureInfo.InvariantCulture));
                }
                else if (type == "error")
                    throw new Exception("live error: " + json);
                else if (type == "post_final_transcript" || type == "end_session")
                    break;
            }
            if (socket.State == WebSocketState.Open)
            {
                try { socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None).Wait(1000); } catch { }
            }
        }
        text = string.Join(" ", parts);
        double sum = 0; foreach (double c in confidences) sum += c;
        confidence = confidences.Count > 0 ? (float)(sum / confidences.Count) : (text != "" ? 0.9f : 0f);
    }

    static float AverageConfidence(IEnumerable utterances, string text)
    {
        double sum = 0; int n = 0;
        if (utterances != null)
            foreach (object u in utterances)
            {
                object c = Field(u, "confidence");
                if (c != null) { sum += Convert.ToDouble(c, CultureInfo.InvariantCulture); n++; }
            }
        return n > 0 ? (float)(sum / n) : (string.IsNullOrEmpty(text) ? 0f : 0.9f);
    }

    static object Request(string method, string url, string contentType, byte[] body, DateTime deadline)
    {
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.Method = method;
        request.Proxy = null;
        request.Timeout = request.ReadWriteTimeout = Math.Max(1000, (int)Remaining(deadline).TotalMilliseconds);
        request.Headers["x-gladia-key"] = ApiKey();
        request.Accept = "application/json";
        if (body != null)
        {
            request.ContentType = contentType;
            request.ContentLength = body.Length;
            using (var stream = request.GetRequestStream()) stream.Write(body, 0, body.Length);
        }
        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                return Json.DeserializeObject(reader.ReadToEnd());
        }
        catch (WebException e)
        {
            var response = e.Response as HttpWebResponse;
            if (response == null) throw;
            string detail;
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8)) detail = reader.ReadToEnd();
            if (detail.Length > 300) detail = detail.Substring(0, 300);
            throw new Exception(string.Format("HTTP {0} from {1} {2}: {3}", (int)response.StatusCode, method, new Uri(url).AbsolutePath, detail));
        }
    }

    // ------------------------------------------------------------------ audio

    static byte[] ToPcm16(float[] samples)
    {
        var pcm = new byte[samples.Length * 2];
        for (int i = 0; i < samples.Length; i++)
        {
            float s = samples[i];
            if (float.IsNaN(s)) s = 0;
            int v = (int)Math.Round(Math.Max(-1f, Math.Min(1f, s)) * 32767f);
            pcm[2 * i] = (byte)v;
            pcm[2 * i + 1] = (byte)(v >> 8);
        }
        return pcm;
    }

    static byte[] Wav(byte[] pcm)
    {
        var ms = new MemoryStream();
        var w = new BinaryWriter(ms);
        w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(36 + pcm.Length); w.Write(Encoding.ASCII.GetBytes("WAVE"));
        w.Write(Encoding.ASCII.GetBytes("fmt ")); w.Write(16); w.Write((short)1); w.Write((short)1);
        w.Write(Rate); w.Write(Rate * 2); w.Write((short)2); w.Write((short)16);
        w.Write(Encoding.ASCII.GetBytes("data")); w.Write(pcm.Length); w.Write(pcm);
        w.Flush();
        return ms.ToArray();
    }

    // ------------------------------------------------------------------ config & helpers

    static Dictionary<string, object> LoadConfig(string path)
    {
        try { return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)); }
        catch (Exception e) { Log("cannot read " + path + ": " + e.Message); return new Dictionary<string, object>(); }
    }

    static string ApiKey()
    {
        string env = Environment.GetEnvironmentVariable("GLADIA_API_KEY");
        return (string.IsNullOrEmpty(env) ? Str("api_key", "") : env).Trim();
    }

    static string BaseUrl()
    {
        string env = Environment.GetEnvironmentVariable("GLADIA_BASE_URL");
        return (string.IsNullOrEmpty(env) ? Str("base_url", "https://api.gladia.io") : env).TrimEnd('/');
    }

    static void Merge(Dictionary<string, object> target, string key)
    {
        object extra;
        if (config.TryGetValue(key, out extra) && extra is Dictionary<string, object>)
            foreach (var pair in (Dictionary<string, object>)extra) target[pair.Key] = pair.Value;
    }

    static object Field(object obj, string key)
    {
        var dict = obj as Dictionary<string, object>;
        object value;
        return dict != null && dict.TryGetValue(key, out value) ? value : null;
    }

    static string Str(string key, string fallback)
    {
        object v;
        return config.TryGetValue(key, out v) && v != null ? Convert.ToString(v, CultureInfo.InvariantCulture) : fallback;
    }

    static double Num(string key, double fallback)
    {
        object v;
        if (!config.TryGetValue(key, out v) || v == null) return fallback;
        try { return Convert.ToDouble(v, CultureInfo.InvariantCulture); } catch { return fallback; }
    }

    static bool Bool(string key, bool fallback)
    {
        object v;
        return config.TryGetValue(key, out v) && v is bool ? (bool)v : fallback;
    }

    static TimeSpan Remaining(DateTime deadline)
    {
        TimeSpan left = deadline - DateTime.UtcNow;
        return left > TimeSpan.FromSeconds(1) ? left : TimeSpan.FromSeconds(1);
    }

    static string Describe(Exception e)
    {
        while (e is AggregateException && e.InnerException != null) e = e.InnerException;
        return e.GetType().Name + ": " + e.Message;
    }

    static string Quote(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }

    static void Log(string line)
    {
        try { File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + line + Environment.NewLine, Encoding.UTF8); }
        catch { }
    }
}
