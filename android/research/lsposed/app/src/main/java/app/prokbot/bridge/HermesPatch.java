package app.prokbot.bridge;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Exact recipe for Android 1.19.1 (3050), Hermes hermes-v250829098.0.16. */
public final class HermesPatch {
    public static final String INPUT_SHA256 = "e4e58266c8380d6ac4696ece4f293eca872bd6dc3e470d2db33fb3d44b0f3290";
    public static final int INPUT_SIZE = 23889920;
    private static final int HEADER = 128 + 20928 * 12;
    private static final int OLD_BODY = 9817452;
    private HermesPatch() {}

    public static byte[] patch(byte[] original, String origin, String token) throws Exception {
        origin = Origin.normalize(origin);
        Origin.validateToken(token);
        if (original.length != INPUT_SIZE || !digest("SHA-256", original).equals(INPUT_SHA256)) {
            throw new IllegalArgumentException("不支持的 Grok Bot bundle；已停止应用补丁");
        }
        if (u32(original, 8) != 98 || u32(original, 32) != original.length
                || (u32(original, HEADER) & 0x1ffffff) != OLD_BODY
                || (u32(original, HEADER + 4) & 0x3fff) != 4
                || !Arrays.equals(Arrays.copyOfRange(original, OLD_BODY, OLD_BODY + 4), new byte[]{(byte)147, 0, 118, 0})
                || !Arrays.equals(MessageDigest.getInstance("SHA-1").digest(Arrays.copyOf(original, original.length - 20)),
                    Arrays.copyOfRange(original, original.length - 20, original.length))) {
            throw new IllegalArgumentException("Hermes 输入校验失败");
        }
        Map<String, Integer> strings = strings(original);
        if (!Integer.valueOf(32).equals(strings.get("url")) || !Integer.valueOf(244).equals(strings.get("token"))) {
            throw new IllegalArgumentException("Hermes 字符串索引不匹配");
        }
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        // Opcodes are from the matching upstream BytecodeList.def, not Hermes main.
        body.write(4); body.write(0); // NewObject r0
        property(body, strings, "url", origin, 0);
        property(body, strings, "token", token, 1);
        body.write(118); body.write(0); // Ret r0
        byte[] code = body.toByteArray();
        int offset = (original.length - 20 + 3) & ~3;
        if (offset >= (1 << 25) || code.length >= (1 << 14)) throw new IllegalArgumentException("补丁超出函数头范围");
        // 631 functions share OLD_BODY. Relocate only this function; never write OLD_BODY.
        byte[] result = Arrays.copyOf(original, offset + code.length + 20);
        Arrays.fill(result, original.length - 20, offset, (byte)0);
        System.arraycopy(code, 0, result, offset, code.length);
        put32(result, HEADER, (u32(original, HEADER) & ~0x1ffffff) | offset);
        put32(result, HEADER + 4, (u32(original, HEADER + 4) & ~0x3fff) | code.length);
        result[HEADER + 8] = (byte)Math.max(original[HEADER + 8] & 255, 3);
        result[HEADER + 10] = (byte)((original[HEADER + 10] & 0xc0) | 2);
        put32(result, 32, result.length);
        MessageDigest sha1 = MessageDigest.getInstance("SHA-1");
        sha1.update(result, 0, result.length - 20);
        System.arraycopy(sha1.digest(), 0, result, result.length - 20, 20);
        return result;
    }

    private static void property(ByteArrayOutputStream body, Map<String, Integer> strings,
            String key, String value, int cache) {
        string(body, 1, strings.get(""));
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            Integer index = strings.get(Character.toString(c));
            if (index != null) string(body, 2, index);
            else if (c >= '0' && c <= '9') {
                body.write(139); body.write(2); body.write(c - '0'); // LoadConstUInt8
            } else throw new IllegalArgumentException("连接地址包含不支持的字符");
            body.write(30); body.write(1); body.write(1); body.write(2); // Add r1,r1,r2
        }
        body.write(86); body.write(0); body.write(1); body.write(cache); // DefineOwnById
        little(body, strings.get(key), 2);
    }

    private static void string(ByteArrayOutputStream body, int register, Integer index) {
        if (index == null) throw new IllegalArgumentException("Hermes 字符串缺失");
        body.write(index < 65536 ? 144 : 145);
        body.write(register);
        little(body, index, index < 65536 ? 2 : 4);
    }

    private static Map<String, Integer> strings(byte[] data) {
        int count = u32(data, 52);
        int table = 128 + u32(data, 40) * 12 + u32(data, 44) * 4 + u32(data, 48) * 4;
        int overflow = table + count * 4;
        int storage = overflow + u32(data, 56) * 8;
        Map<String, Integer> strings = new HashMap<>();
        for (int i = 0; i < count; i++) {
            int entry = u32(data, table + i * 4);
            int offset = (entry >>> 1) & 0x7fffff, length = entry >>> 24;
            if (length == 255) { length = u32(data, overflow + offset * 8 + 4); offset = u32(data, overflow + offset * 8); }
            if (length > 5) continue;
            boolean utf16 = (entry & 1) != 0;
            String value = new String(data, storage + offset, length * (utf16 ? 2 : 1),
                utf16 ? StandardCharsets.UTF_16LE : StandardCharsets.UTF_8);
            strings.putIfAbsent(value, i);
        }
        return strings;
    }

    public static String digest(String algorithm, byte[] data) throws Exception {
        byte[] bytes = MessageDigest.getInstance(algorithm).digest(data);
        StringBuilder hex = new StringBuilder();
        for (byte b : bytes) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return hex.toString();
    }
    private static int u32(byte[] data, int offset) {
        return (data[offset] & 255) | ((data[offset + 1] & 255) << 8)
            | ((data[offset + 2] & 255) << 16) | ((data[offset + 3] & 255) << 24);
    }
    private static void put32(byte[] data, int offset, int value) {
        for (int i = 0; i < 4; i++) data[offset + i] = (byte)(value >>> (i * 8));
    }
    private static void little(ByteArrayOutputStream out, int value, int bytes) {
        for (int i = 0; i < bytes; i++) out.write(value >>> (i * 8));
    }
}
