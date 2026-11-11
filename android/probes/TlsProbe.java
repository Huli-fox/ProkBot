package app.prokbot.probe;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.util.Enumeration;
import javax.net.ssl.HttpsURLConnection;

/** Standalone Android TLS diagnostic. No trust manager or hostname verifier overrides. */
public final class TlsProbe {
    private static String fingerprint(X509Certificate cert) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(cert.getEncoded());
        StringBuilder result = new StringBuilder();
        for (byte value : digest) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !args[0].equals("https://127.0.0.1:18443/healthz")
                || !args[1].matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("Expected the loopback health URL and CA SHA-256 fingerprint");
        }
        KeyStore anchors = KeyStore.getInstance("AndroidCAStore");
        anchors.load(null, null);
        String matchingAlias = "missing";
        Enumeration<String> aliases = anchors.aliases();
        while (aliases.hasMoreElements()) {
            String alias = aliases.nextElement();
            X509Certificate certificate = (X509Certificate) anchors.getCertificate(alias);
            if (certificate != null && fingerprint(certificate).equals(args[1])) matchingAlias = alias;
        }
        System.out.println("CA_ALIAS=" + matchingAlias);
        HttpsURLConnection connection = (HttpsURLConnection) new URL(args[0]).openConnection();
        connection.setConnectTimeout(8000);
        connection.setReadTimeout(8000);
        connection.setInstanceFollowRedirects(false);
        try {
            System.out.println("HTTP_STATUS=" + connection.getResponseCode());
            System.out.println("CIPHER=" + connection.getCipherSuite());
            X509Certificate leaf = (X509Certificate) connection.getServerCertificates()[0];
            System.out.println("LEAF_SHA256=" + fingerprint(leaf));
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                byte[] buffer = new byte[256];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (output.size() + count > 4096) throw new IllegalStateException("Health response too large");
                    output.write(buffer, 0, count);
                }
            }
            System.out.println("HEALTH=" + output.toString("UTF-8"));
        } catch (Exception error) {
            System.out.println("TLS_ERROR=" + error.getClass().getName());
            for (Throwable reason = error; reason != null; reason = reason.getCause()) {
                System.out.println("CAUSE=" + reason.getClass().getSimpleName() + ": " + reason.getMessage());
            }
            System.exit(1);
        } finally {
            connection.disconnect();
        }
    }
}
