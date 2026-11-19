using System.Buffers.Binary;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;

namespace N1x.Benchmarks;

// MT19937 with CPython's version-2 seed expansion and rejection sampling,
// so archived wave orders and run-id-derived reference records remain reproducible.
sealed class MatrixRandom
{
    readonly uint[] state = new uint[624];
    int index = 624;
    public MatrixRandom(uint seed) : this([seed]) { }
    public MatrixRandom(string seed) : this(Words(seed)) { }
    static uint[] Words(string seed)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(seed);
        byte[] key = [.. bytes, .. SHA512.HashData(bytes)];
        Array.Reverse(key); Array.Resize(ref key, (key.Length + 3) / 4 * 4);
        var words = new uint[key.Length / 4];
        for (int k = 0; k < words.Length; k++) words[k] = BinaryPrimitives.ReadUInt32LittleEndian(key.AsSpan(4 * k));
        return words;
    }
    MatrixRandom(uint[] key)
    {
        state[0] = 19650218;
        for (int k = 1; k < 624; k++) state[k] = 1812433253 * (state[k - 1] ^ (state[k - 1] >> 30)) + (uint)k;
        int i = 1, j = 0;
        void Advance() { if (++i == 624) { state[0] = state[623]; i = 1; } }
        for (int k = 0; k < Math.Max(624, key.Length); k++)
        {
            state[i] = (state[i] ^ ((state[i - 1] ^ (state[i - 1] >> 30)) * 1664525)) + key[j] + (uint)j;
            Advance(); j = (j + 1) % key.Length;
        }
        for (int k = 0; k < 623; k++)
        {
            state[i] = (state[i] ^ ((state[i - 1] ^ (state[i - 1] >> 30)) * 1566083941)) - (uint)i;
            Advance();
        }
        state[0] = 0x80000000;
    }
    uint Draw()
    {
        if (index == 624)
        {
            for (int i = 0; i < 624; i++)
            {
                uint v = (state[i] & 0x80000000) | (state[(i + 1) % 624] & 0x7fffffff);
                state[i] = state[(i + 397) % 624] ^ (v >> 1) ^ ((v & 1) == 0 ? 0u : 0x9908b0df);
            }
            index = 0;
        }
        uint y = state[index++];
        y ^= y >> 11; y ^= (y << 7) & 0x9d2c5680; y ^= (y << 15) & 0xefc60000; return y ^ (y >> 18);
    }
    internal int Below(int n)
    {
        int bits = 32 - BitOperations.LeadingZeroCount((uint)n);
        uint value; do value = Draw() >> (32 - bits); while (value >= n);
        return (int)value;
    }
}

