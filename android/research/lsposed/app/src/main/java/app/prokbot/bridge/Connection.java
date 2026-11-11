package app.prokbot.bridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class Connection {
    static final String PREFS = "prokbot_connection_v1";
    final String origin, token, deviceId;

    Connection(String origin, String token, String deviceId) {
        this.origin = Origin.normalize(origin);
        Origin.validateToken(token);
        this.token = token;
        this.deviceId = deviceId;
    }

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static Connection read(Context context) {
        try (InputStream in = credentials(context).openRead()) {
            JSONObject data = new JSONObject(new String(readLimited(in, 4096), StandardCharsets.UTF_8));
            return new Connection(data.getString("origin"), data.getString("token"), data.getString("deviceId"));
        } catch (Exception ignored) { return null; }
    }

    void save(Context context) throws Exception {
        AtomicFile file = credentials(context);
        FileOutputStream out = null;
        try {
            out = file.startWrite();
            out.write(new JSONObject().put("origin", origin).put("token", token).put("deviceId", deviceId)
                .toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(out);
        } catch (Exception error) { file.failWrite(out); throw error; }
        if (!prefs(context).edit().putBoolean("enabled", true)
                .putInt("pendingStarts", 0).commit()) throw new Exception("无法保存设备连接");
    }

    static AtomicFile credentials(Context context) {
        return new AtomicFile(new File(context.getNoBackupFilesDir(), "prokbot/connection.json"));
    }

    static Connection pair(String address, String key, String deviceName) throws Exception {
        String origin = Origin.normalize(address);
        if (deviceName.trim().isEmpty() || deviceName.length() > 80) throw new IllegalArgumentException("设备名称需要 1–80 个字符");
        key = key.replaceAll("[\\s-]", "").toUpperCase(java.util.Locale.ROOT);
        if (!key.matches("[A-Z2-9]{6}")) throw new IllegalArgumentException("请输入 Host 管理页的六位配对码");
        JSONObject request = new JSONObject().put("platform", "android").put("pairingKey", key).put("deviceName", deviceName.trim());
        JSONObject result = request(origin + "/connect/pair", "POST", null, request, 201);
        if (!origin.equals(Origin.normalize(result.getString("gatewayUrl")))) {
            throw new IllegalArgumentException("Host 返回的地址与输入不一致，请检查 Host 的公开地址配置后重新配对");
        }
        return new Connection(origin, result.getString("token"), result.getString("deviceId"));
    }

    void register() throws Exception {
        request(origin + "/local/device", "PUT", token, new JSONObject()
            .put("kind", "android").put("bundleId", HookEntry.TARGET).put("appVersion", "1.19.1")
            .put("push", new JSONObject().put("provider", "none")), 200);
    }

    static JSONObject request(String address, String method, String token, JSONObject input, int expected) throws Exception {
        HttpURLConnection connection = (HttpURLConnection)new URL(address).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        if (token != null) connection.setRequestProperty("Authorization", "Bearer " + token);
        try {
            if (input != null) {
                byte[] bytes = input.toString().getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(bytes.length);
                connection.setRequestProperty("Content-Type", "application/json");
                try (java.io.OutputStream out = connection.getOutputStream()) { out.write(bytes); }
            }
            int status = connection.getResponseCode();
            if (status != expected) {
                // Do not reflect untrusted server text (or request credentials) into diagnostics.
                if (status == 401) throw new IllegalArgumentException("配对码无效、已使用或已过期，请在 Host 管理页重新生成");
                if (status == 400) throw new IllegalArgumentException("Host 拒绝了设备资料，请确认已安装支持 Android 的 Host 更新");
                throw new IllegalArgumentException("Host 返回 HTTP " + status + "，请检查服务地址和 Host 状态");
            }
            try (InputStream in = connection.getInputStream()) {
                return new JSONObject(new String(readLimited(in, 65536), StandardCharsets.UTF_8));
            }
        } finally { connection.disconnect(); }
    }

    static byte[] readLimited(InputStream in, int limit) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[16384];
        int size;
        while ((size = in.read(buffer)) != -1) {
            if (out.size() + size > limit) throw new IllegalArgumentException("文件或响应超出大小限制");
            out.write(buffer, 0, size);
        }
        return out.toByteArray();
    }
}
