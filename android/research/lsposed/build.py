#!/usr/bin/env python3
"""Build the small Java-only LSPosed module with an installed Android SDK + JDK 17.

No official APK, Hermes bundle, credential, or Xposed runtime is included.
The Xposed API jar is compile-only and must match the pinned checksum.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
API_SHA256 = "f48c635f1c7469fdec0e00ad2ea0b7a6b2f5b55065784a35b7ca3a84615e8e25"


def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--xposed-api", type=Path, required=True,
                        help="https://api.xposed.info/de/robv/android/xposed/api/82/api-82.jar")
    parser.add_argument("--output", type=Path, default=ROOT.parents[2] / "output.noindex/android-lsposed")
    parser.add_argument("--bundle-test", type=Path, help="Optional local official HBC for pinned-recipe tests")
    parser.add_argument("--load-only-probe", action="store_true", help="Diagnostic APK: logs module load and registers NO hooks")
    parser.add_argument("--startup-probe", action="store_true", help="Diagnostic APK: isolate the exact protected startup program")
    parser.add_argument("--experimental-lsposed", action="store_true", help="Explicitly build the currently incompatible LSPosed prototype")
    args = parser.parse_args()
    if not (args.load_only_probe or args.startup_probe or args.experimental_lsposed):
        raise SystemExit("LSPosed crashes this tested app/device combination, even without hooks. Use android/tools/root_cache.py; see android/README.md. For research only, pass --experimental-lsposed or a probe flag.")
    if hashlib.sha256(args.xposed_api.read_bytes()).hexdigest() != API_SHA256:
        raise SystemExit("Xposed API jar checksum mismatch")
    sdk, jdk, output = args.sdk.resolve(), args.java_home.resolve(), args.output.resolve()
    tools = sdk / "build-tools/34.0.0"
    android_jar = sdk / "platforms/android-34/android.jar"
    suffix = ".exe" if os.name == "nt" else ""
    java, javac, keytool = [jdk / "bin" / (name + suffix) for name in ("java", "javac", "keytool")]
    output.mkdir(parents=True, exist_ok=True)
    # Keep each build isolated. No recursive deletion, stale classes, or global SDK changes.
    build = Path(tempfile.mkdtemp(prefix="build-", dir=output))
    classes, dex = build / "classes", build / "dex"
    classes.mkdir(); dex.mkdir()
    sources = ROOT / "app/src/main"
    run(javac, "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
        "-classpath", os.pathsep.join(map(str, [android_jar, args.xposed_api.resolve()])),
        "-d", classes, *sorted((sources / "java").rglob("*.java")))
    assets = sources / "assets"
    if args.load_only_probe and args.startup_probe:
        raise SystemExit("Choose one probe")
    if args.load_only_probe or args.startup_probe:
        entry = "LoadOnlyEntry" if args.load_only_probe else "StartupEntry"
        run(javac, "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
            "-classpath", os.pathsep.join(map(str, [android_jar, args.xposed_api.resolve()])),
            "-d", classes, ROOT / "probes" / (entry + ".java"))
        assets = build / "assets"
        assets.mkdir()
        (assets / "xposed_init").write_text("app.prokbot.bridge." + entry + "\n", encoding="utf-8")
    if args.bundle_test:
        run(javac, "-encoding", "UTF-8", "-classpath", classes, "-d", classes, ROOT / "tests/PatchTest.java")
        run(java, "-cp", classes, "PatchTest", args.bundle_test.resolve())
    # Only module classes enter DEX; no Xposed API or test classes.
    run(java, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--min-api", "27",
        "--lib", android_jar, "--classpath", args.xposed_api.resolve(), "--output", dex,
        *sorted((classes / "app").rglob("*.class")))
    unsigned = build / "unsigned.apk"
    run(tools / ("aapt" + suffix), "package", "-f", "-M", sources / "AndroidManifest.xml",
        "-S", sources / "res", "-A", assets, "-I", android_jar, "-F", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(dex / "classes.dex", "classes.dex")
    aligned = build / "aligned.apk"
    run(tools / ("zipalign" + suffix), "-f", "4", unsigned, aligned)
    keystore = output / "local-debug.p12"
    if not keystore.exists():
        run(keytool, "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12", "-storepass", "android",
            "-keypass", "android", "-alias", "prokbot", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "3650", "-dname", "CN=ProkBot Local Development")
    target = output / ("prokbot-load-only-probe.apk" if args.load_only_probe else
        "prokbot-startup-probe.apk" if args.startup_probe else "prokbot-bridge-0.1.0.apk")
    run(java, "-jar", tools / "lib/apksigner.jar", "sign", "--ks", keystore, "--ks-pass", "pass:android",
        "--ks-key-alias", "prokbot", "--out", target, aligned)
    run(java, "-jar", tools / "lib/apksigner.jar", "verify", "--verbose", target)
    print(f"APK: {target}\nSHA256: {hashlib.sha256(target.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
