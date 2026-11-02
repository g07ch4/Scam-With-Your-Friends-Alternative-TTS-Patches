// Drop-in replacement for QwenTtsWorker.exe that forwards speech requests to an
// OpenAI-compatible TTS server (POST /v1/audio/speech) in the local network.
//
// Game <-> worker protocol (BinaryReader/BinaryWriter over stdin/stdout):
//   1 model:str backend:str              -> 1, 2, backend:str           (load)
//   2 text:str language:str n:i32 [n*f32] -> {2 count:i32 count*f32}* 3  (synthesize, 24 kHz mono)
//   any error                              -> 4 message:str
// n == 0 means "same voice reference as last time".
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

static class Worker
{
    const int Rate = 24000;
    const int MaxSamples = 720000;   // the game rejects more than 30 s per request
    const int ChunkSamples = 4800;   // 200 ms

    static BinaryWriter output;
    static Dictionary<string, object> config;
    static float[] reference;
    static string referenceHash;
    static string logPath;

    static int Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        logPath = Path.Combine(dir, "qwen-remote.log");
        output = new BinaryWriter(Console.OpenStandardOutput());
        var input = new BinaryReader(Console.OpenStandardInput());
        try
        {
            config = LoadConfig(Path.Combine(dir, "qwen-remote.json"));
            ServicePointManager.Expect100Continue = false;
            while (true)
            {
                int command;
                try { command = input.ReadInt32(); }
                catch (EndOfStreamException) { return 0; }

                if (command == 1)
                {
                    input.ReadString(); // model path - unused, the server owns the model
                    input.ReadString(); // backend   - unused
                    CheckServer();
                    output.Write(1);
                    output.Write(2);
                    output.Write("cpu");
                    output.Flush();
                    Log("loaded; server " + Str("url", ""));
                }
                else if (command == 2)
                {
                    string text = input.ReadString();
                    string language = input.ReadString();
                    int count = input.ReadInt32();
                    if (count < 0 || count > 240000) throw new InvalidDataException("Invalid Qwen reference length.");
                    if (count > 0)
                    {
                        byte[] raw = input.ReadBytes(count * 4);
                        if (raw.Length != count * 4) return 0;
                        reference = new float[count];
                        Buffer.BlockCopy(raw, 0, reference, 0, raw.Length);
                        using (var sha = SHA1.Create())
                            referenceHash = BitConverter.ToString(sha.ComputeHash(raw)).Replace("-", "").Substring(0, 12).ToLowerInvariant();
                        DumpReference();
                    }
                    try
                    {
                        Synthesize(text, language);
                        output.Write(3);
                        output.Flush();
                    }
                    catch (Exception e)
                    {
                        // Report and keep running; the game falls back to its other voice engine.
                        Log("ERROR " + e.Message);
                        WriteError(e);
                    }
                }
                else
                {
                    throw new InvalidDataException("Unknown Qwen command.");
                }
            }
        }
        catch (Exception e)
        {
            Log("FATAL " + e);
            WriteError(e);
            return 1;
        }
    }

    static void WriteError(Exception e)
    {
        try
        {
            string message = "Remote TTS: " + e.Message;
            output.Write(4);
            output.Write(message.Substring(0, Math.Min(1000, message.Length)));
            output.Flush();
        }
        catch { }
    }

    // ---------------------------------------------------------------- config

    static Dictionary<string, object> LoadConfig(string path)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("qwen-remote.json is missing next to QwenTtsWorker.exe.");
        var json = new JavaScriptSerializer();
        var result = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
        string url = Environment.GetEnvironmentVariable("QWEN_REMOTE_URL");
        if (!string.IsNullOrEmpty(url)) result["url"] = url;
        if (string.IsNullOrEmpty(result.ContainsKey("url") ? result["url"] as string : null))
            throw new InvalidDataException("qwen-remote.json: 'url' is not set.");
        return result;
    }

    static string Str(string key, string fallback)
    {
        object value;
        return config.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : fallback;
    }

    static bool Bool(string key, bool fallback)
    {
        object value;
        return config.TryGetValue(key, out value) && value is bool ? (bool)value : fallback;
    }

    static int Int(string key, int fallback)
    {
        object value;
        return config.TryGetValue(key, out value) && value != null ? Convert.ToInt32(value) : fallback;
    }

    static Dictionary<string, object> Map(string key)
    {
        object value;
        return config.TryGetValue(key, out value) ? value as Dictionary<string, object> : null;
    }

    // ---------------------------------------------------------------- server

    static void CheckServer()
    {
        // Fail fast at load time so the game keeps its own voices when the server is offline.
        var uri = new Uri(Str("url", ""));
        using (var client = new TcpClient())
        {
            var connect = client.BeginConnect(uri.Host, uri.Port, null, null);
            if (!connect.AsyncWaitHandle.WaitOne(TimeSpan.FromSeconds(3)) || !client.Connected)
                throw new IOException("TTS server " + uri.Host + ":" + uri.Port + " is not reachable.");
            client.EndConnect(connect);
        }
    }

    static void Synthesize(string text, string language)
    {
        var started = DateTime.UtcNow;
        string format = Str("response_format", "wav").ToLowerInvariant();
        var body = new Dictionary<string, object>();
        body["model"] = Str("model", "tts-1");
        body["input"] = text;
        body["voice"] = Voice();
        body["response_format"] = format;
        if (Bool("send_language", true)) body["language"] = language;
        if (Bool("send_reference_audio", false) && reference != null)
            body[Str("reference_audio_field", "ref_audio")] = "data:audio/wav;base64," + Convert.ToBase64String(EncodeWav(reference));
        var extra = Map("extra_body");
        if (extra != null)
            foreach (var pair in extra) body[pair.Key] = pair.Value;

        var json = new JavaScriptSerializer();
        json.MaxJsonLength = int.MaxValue;
        byte[] payload = Encoding.UTF8.GetBytes(json.Serialize(body));

        var request = (HttpWebRequest)WebRequest.Create(Str("url", ""));
        request.Method = "POST";
        request.ContentType = "application/json";
        request.Timeout = request.ReadWriteTimeout = Int("timeout_seconds", 25) * 1000;
        request.Proxy = null;
        string key = Str("api_key", "");
        if (key.Length > 0) request.Headers["Authorization"] = "Bearer " + key;
        using (var stream = request.GetRequestStream())
            stream.Write(payload, 0, payload.Length);

        int sent;
        try
        {
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            {
                if (format == "pcm")
                    sent = StreamPcm(stream, Int("pcm_sample_rate", Rate));
                else
                    sent = Emit(DecodeWav(ReadAll(stream)));
            }
        }
        catch (WebException e)
        {
            var failed = e.Response as HttpWebResponse;
            if (failed == null) throw;
            string detail;
            using (var reader = new StreamReader(failed.GetResponseStream()))
                detail = reader.ReadToEnd();
            throw new IOException("HTTP " + (int)failed.StatusCode + ": " + detail.Substring(0, Math.Min(300, detail.Length)));
        }
        if (sent == 0) throw new IOException("Server returned no audio.");
        Log(string.Format("ok voice={0} ref={1} lang={2} chars={3} audio={4:0.0}s took={5:0.00}s",
            body["voice"], referenceHash, language, text.Length, sent / (double)Rate, (DateTime.UtcNow - started).TotalSeconds));
    }

    static string Voice()
    {
        var map = Map("voice_map");
        object mapped;
        if (map != null && referenceHash != null && map.TryGetValue(referenceHash, out mapped))
            return Convert.ToString(mapped);
        return Str("voice", "default");
    }

    // ---------------------------------------------------------------- audio

    // Raw 16-bit little-endian mono PCM, streamed to the game while it downloads.
    static int StreamPcm(Stream stream, int rate)
    {
        int total = 0;
        var buffer = new byte[rate / 5 * 2];
        int filled = 0, read;
        while ((read = stream.Read(buffer, filled, buffer.Length - filled)) > 0)
        {
            filled += read;
            if (filled < buffer.Length) continue;
            total = EmitPart(Resample(Pcm16(buffer, filled), rate), total);
            filled = 0;
        }
        filled -= filled % 2;
        if (filled > 0) total = EmitPart(Resample(Pcm16(buffer, filled), rate), total);
        return total;
    }

    static float[] Pcm16(byte[] data, int length)
    {
        var samples = new float[length / 2];
        for (int i = 0; i < samples.Length; i++)
            samples[i] = BitConverter.ToInt16(data, i * 2) / 32768f;
        return samples;
    }

    static int Emit(float[] samples)
    {
        return EmitPart(samples, 0);
    }

    static int EmitPart(float[] samples, int total)
    {
        for (int offset = 0; offset < samples.Length && total < MaxSamples; )
        {
            int count = Math.Min(Math.Min(ChunkSamples, samples.Length - offset), MaxSamples - total);
            var chunk = new float[count];
            for (int i = 0; i < count; i++)
            {
                float s = samples[offset + i];
                chunk[i] = float.IsNaN(s) || float.IsInfinity(s) ? 0f : Math.Max(-1f, Math.Min(1f, s));
            }
            var bytes = new byte[count * 4];
            Buffer.BlockCopy(chunk, 0, bytes, 0, bytes.Length);
            output.Write(2);
            output.Write(count);
            output.Write(bytes);
            output.Flush();
            offset += count;
            total += count;
        }
        return total;
    }

    static float[] DecodeWav(byte[] data)
    {
        if (data.Length < 12 || Encoding.ASCII.GetString(data, 0, 4) != "RIFF" || Encoding.ASCII.GetString(data, 8, 4) != "WAVE")
            throw new InvalidDataException("Server did not return a WAV file (set response_format).");
        int format = 0, channels = 0, rate = 0, bits = 0, pos = 12;
        while (pos + 8 <= data.Length)
        {
            string id = Encoding.ASCII.GetString(data, pos, 4);
            int size = BitConverter.ToInt32(data, pos + 4);
            int start = pos + 8;
            if (id == "fmt ")
            {
                format = BitConverter.ToUInt16(data, start);
                channels = BitConverter.ToUInt16(data, start + 2);
                rate = BitConverter.ToInt32(data, start + 4);
                bits = BitConverter.ToUInt16(data, start + 14);
                if (format == 0xFFFE && size >= 26) format = BitConverter.ToUInt16(data, start + 24);
            }
            else if (id == "data")
            {
                // Streaming servers often write 0 or 0xFFFFFFFF as the data size.
                int length = size <= 0 || start + size > data.Length ? data.Length - start : size;
                return Resample(Samples(data, start, length, format, channels, bits), rate);
            }
            pos = start + size + (size & 1);
            if (size < 0) break;
        }
        throw new InvalidDataException("WAV without audio data.");
    }

    static float[] Samples(byte[] data, int start, int length, int format, int channels, int bits)
    {
        if (channels < 1) throw new InvalidDataException("Invalid WAV channel count.");
        int width = bits / 8;
        if (width < 1 || !(format == 1 || (format == 3 && bits == 32)))
            throw new InvalidDataException("Unsupported WAV encoding " + format + "/" + bits + " bit.");
        int frames = length / (width * channels);
        var mono = new float[frames];
        for (int f = 0; f < frames; f++)
        {
            float sum = 0;
            for (int c = 0; c < channels; c++)
            {
                int at = start + (f * channels + c) * width;
                if (format == 3) sum += BitConverter.ToSingle(data, at);
                else if (bits == 16) sum += BitConverter.ToInt16(data, at) / 32768f;
                else if (bits == 24) sum += ((data[at] << 8 | data[at + 1] << 16 | data[at + 2] << 24) >> 8) / 8388608f;
                else if (bits == 32) sum += BitConverter.ToInt32(data, at) / 2147483648f;
                else sum += (data[at] - 128) / 128f;
            }
            mono[f] = sum / channels;
        }
        return mono;
    }

    static float[] Resample(float[] samples, int rate)
    {
        if (rate == Rate || rate <= 0 || samples.Length == 0) return samples;
        double step = rate / (double)Rate;
        var result = new float[(int)(samples.Length / step)];
        for (int i = 0; i < result.Length; i++)
        {
            double at = i * step;
            int index = (int)at;
            float next = index + 1 < samples.Length ? samples[index + 1] : samples[index];
            result[i] = (float)(samples[index] + (next - samples[index]) * (at - index));
        }
        return result;
    }

    static byte[] EncodeWav(float[] samples)
    {
        using (var memory = new MemoryStream())
        using (var writer = new BinaryWriter(memory))
        {
            writer.Write(Encoding.ASCII.GetBytes("RIFF"));
            writer.Write(36 + samples.Length * 2);
            writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
            writer.Write(16);
            writer.Write((short)1);
            writer.Write((short)1);
            writer.Write(Rate);
            writer.Write(Rate * 2);
            writer.Write((short)2);
            writer.Write((short)16);
            writer.Write(Encoding.ASCII.GetBytes("data"));
            writer.Write(samples.Length * 2);
            foreach (float s in samples)
                writer.Write((short)Math.Round(Math.Max(-1f, Math.Min(1f, s)) * 32767));
            writer.Flush();
            return memory.ToArray();
        }
    }

    static byte[] ReadAll(Stream stream)
    {
        using (var memory = new MemoryStream())
        {
            stream.CopyTo(memory);
            return memory.ToArray();
        }
    }

    // ---------------------------------------------------------------- diagnostics

    // Saves each game voice once as remote-voices/<hash>.wav so it can be registered on the server
    // and mapped in "voice_map".
    static void DumpReference()
    {
        if (!Bool("dump_references", true)) return;
        try
        {
            string dir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "remote-voices");
            string path = Path.Combine(dir, referenceHash + ".wav");
            if (File.Exists(path)) return;
            Directory.CreateDirectory(dir);
            File.WriteAllBytes(path, EncodeWav(reference));
            Log("new voice reference " + referenceHash + " (" + reference.Length / (double)Rate + " s) -> remote-voices\\" + referenceHash + ".wav");
        }
        catch { }
    }

    static void Log(string line)
    {
        try
        {
            var info = new FileInfo(logPath);
            if (info.Exists && info.Length > 1 << 20) info.Delete();
            File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + line + Environment.NewLine);
            Console.Error.WriteLine("[Qwen3 TTS remote] " + line);
        }
        catch { }
    }
}
