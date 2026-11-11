import app.prokbot.bridge.HermesPatch;
import app.prokbot.bridge.Origin;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;

/** Tests use a locally extracted APK bundle, never distributed in this repository. */
public final class PatchTest {
    public static void main(String[] args) throws Exception {
        byte[] original = Files.readAllBytes(Path.of(args[0]));
        byte[] before = original.clone();
        byte[] patched = HermesPatch.patch(original, "http://127.0.0.1:18081",
            "PROKBOT_ASSESSMENT_ONLY_NOT_A_REAL_TOKEN_0000");
        require(Arrays.equals(original, before), "input mutated");
        int changes = 0;
        for (int i = 0; i < original.length - 20; i++) {
            if (original[i] != patched[i]) {
                require((i >= 32 && i < 36) || (i >= 251264 && i < 251276), "unrelated original data modified at " + i);
                changes++;
            }
        }
        require(changes > 0, "function not changed");
        require(Arrays.equals(MessageDigest.getInstance("SHA-1").digest(Arrays.copyOf(patched, patched.length - 20)),
            Arrays.copyOfRange(patched, patched.length - 20, patched.length)), "footer invalid");
        // Independent earlier Python generator: full output must match, not only patched headers.
        Path reference = Path.of(args[0]).resolveSibling("probe.android.hbc");
        if (Files.exists(reference)) require(Arrays.equals(patched, Files.readAllBytes(reference)), "probe differs from independent generator");
        original[1000] ^= 1;
        rejected(() -> HermesPatch.patch(original, "https://bot.example.com", "a".repeat(32)));
        for (String bad : new String[]{"http://example.com", "https://user:pass@example.com", "https://example.com/api",
            "https://example.com?x=1", "https://example.com#x", "https://example.com:99999", "https://example.com:0", "javascript:alert(1)"}) {
            rejected(() -> Origin.normalize(bad));
        }
        require(Origin.normalize(" HTTPS://EXAMPLE.COM:443/ ").equals("https://example.com"), "origin normalization");
        rejected(() -> Origin.validateToken("short"));
        rejected(() -> Origin.validateToken("a".repeat(32) + "\r\nAuthorization: bad"));
        byte[] max = HermesPatch.patch(before, "https://" + "a".repeat(240) + ".example.com", "_aB09-".repeat(42));
        require(max.length > patched.length, "long input lost");
        System.out.println("PASS: exact recipe, independent probe match, shared body preservation, integrity rejection, origin/token validation");
    }
    interface Operation { void run() throws Exception; }
    static void rejected(Operation operation) throws Exception {
        try { operation.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("invalid input accepted");
    }
    static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
}
