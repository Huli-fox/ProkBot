package app.prokbot.bridge;

import java.net.URI;
import java.util.Locale;

/** Pairing never follows redirects or sends a device credential to a different origin. */
public final class Origin {
    private Origin() {}

    public static String normalize(String input) {
        try {
            URI uri = new URI(input.trim());
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            String host = uri.getHost();
            if (host == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null
                    || uri.getRawFragment() != null || uri.getPort() == 0 || uri.getPort() > 65535
                    || !(uri.getRawPath().isEmpty() || uri.getRawPath().equals("/"))
                    || !(scheme.equals("https") || (scheme.equals("http") && host.equals("127.0.0.1")))) {
                throw new IllegalArgumentException();
            }
            int port = uri.getPort();
            if ((scheme.equals("https") && port == 443) || (scheme.equals("http") && port == 80)) port = -1;
            String result = new URI(scheme, null, host.toLowerCase(Locale.ROOT), port, null, null, null).toASCIIString();
            if (result.length() > 512) throw new IllegalArgumentException();
            return result;
        } catch (Exception error) {
            throw new IllegalArgumentException("请输入 HTTPS 服务根地址，例如 https://bot.example.com。USB 测试可用 http://127.0.0.1:端口。");
        }
    }

    public static void validateToken(String token) {
        if (token == null || !token.matches("[A-Za-z0-9_-]{32,256}")) {
            throw new IllegalArgumentException("Host 返回的设备令牌格式无效");
        }
    }
}
