package app.prokbot.bridge;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.res.AssetManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.security.NetworkSecurityPolicy;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public final class HookEntry implements IXposedHookLoadPackage {
    static final String TARGET = "ai.x.grok.bot";
    private static final String MAIN = "ai.x.grok.bot.MainActivity";
    private static final String TAG = "ProkBotBridge";
    private static volatile String status = "尚未配对";
    private static volatile boolean supported, loaded;
    private static File prepared;
    private static String preparedFor;
    private static boolean healthScheduled;

    @Override public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lp) throws Throwable {
        if (!TARGET.equals(lp.packageName) || !TARGET.equals(lp.processName) || !lp.isFirstApplication) return;
        log("module-loaded");
        XposedHelpers.findAndHookMethod(Application.class, "attach", Context.class, new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam param) {
                Application app = (Application)param.thisObject;
                if (!TARGET.equals(app.getPackageName())) return;
                try { initialize(app, lp.classLoader); }
                catch (Throwable error) { status = "模块初始化失败（" + error.getClass().getSimpleName() + "）"; log(status); }
            }
        });
    }

    private static void initialize(Application app, ClassLoader loader) throws Throwable {
        PackageInfo info = app.getPackageManager().getPackageInfo(TARGET, 0);
        supported = info.getLongVersionCode() == 3050 && "1.19.1".equals(info.versionName);
        app.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            public void onActivityResumed(Activity activity) {
                if (!MAIN.equals(activity.getClass().getName())) return;
                ConnectionUi.attach(activity);
            }
            public void onActivityCreated(Activity a, Bundle b) {}
            public void onActivityStarted(Activity a) {}
            public void onActivityPaused(Activity a) {}
            public void onActivityStopped(Activity a) {}
            public void onActivitySaveInstanceState(Activity a, Bundle b) {}
            public void onActivityDestroyed(Activity a) {}
        });
        if (!supported) { status = "仅支持 Grok Bot 1.19.1 (3050)，当前版本未应用补丁"; log("unsupported-version"); return; }
        // Only loopback HTTP for an explicit adb-reverse development connection. TLS is unchanged.
        XposedHelpers.findAndHookMethod(NetworkSecurityPolicy.class, "isCleartextTrafficPermitted", String.class,
            new XC_MethodHook() {
                @Override protected void beforeHookedMethod(MethodHookParam p) {
                    if ("127.0.0.1".equals(p.args[0])) p.setResult(true);
                }
            });
        SharedPreferences prefs = Connection.prefs(app);
        Connection connection = Connection.read(app);
        if (connection == null || !prefs.getBoolean("enabled", false)) { log("unconfigured"); return; }
        int pending = prefs.getInt("pendingStarts", 0);
        if (pending >= 2) {
            prefs.edit().putBoolean("enabled", false).putInt("pendingStarts", 0).commit();
            status = "连续两次启动未完成，已暂停连接。可从 ProkBot 入口重新启用。";
            log("recovery-disabled"); return;
        }
        prefs.edit().putInt("pendingStarts", pending + 1).commit();
        disableUpdates(app);
        Class<?> react = XposedHelpers.findClass("com.facebook.react.runtime.ReactInstance", loader);
        Method fileLoader = react.getDeclaredMethod("loadJSBundleFromFile", String.class, String.class);
        fileLoader.setAccessible(true);
        XposedBridge.hookMethod(fileLoader, new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                try { p.args[0] = prepare(app, connection).getAbsolutePath(); markLoaded(app); log("bundle-file"); }
                catch (Throwable error) { fail(p, error); }
            }
        });
        XposedHelpers.findAndHookMethod(react, "loadJSBundleFromAssets", AssetManager.class, String.class,
            new XC_MethodHook() {
                @Override protected void beforeHookedMethod(MethodHookParam p) {
                    try {
                        File bundle = prepare(app, connection);
                        XposedBridge.invokeOriginalMethod(fileLoader, p.thisObject, new Object[]{bundle.getAbsolutePath(), p.args[1]});
                        markLoaded(app); log("bundle-assets"); p.setResult(null);
                    } catch (Throwable error) { fail(p, error); }
                }
            });
        status = "正在加载自部署连接";
        log("startup-hooks-ready");
    }

    private static void disableUpdates(Application app) {
        // The process sees updates disabled; the signed APK and Expo cache remain untouched.
        XC_MethodHook metadata = new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                if (p.getResult() instanceof ApplicationInfo) {
                    ApplicationInfo original = (ApplicationInfo)p.getResult();
                    if (TARGET.equals(original.packageName) && original.metaData != null) {
                        ApplicationInfo copy = new ApplicationInfo(original);
                        copy.metaData = new Bundle(original.metaData);
                        copy.metaData.putBoolean("expo.modules.updates.ENABLED", false);
                        p.setResult(copy);
                    }
                }
            }
        };
        XposedBridge.hookAllMethods(XposedHelpers.findClass("android.app.ApplicationPackageManager", null), "getApplicationInfo", metadata);
        if (app.getApplicationInfo().metaData != null) app.getApplicationInfo().metaData.putBoolean("expo.modules.updates.ENABLED", false);
    }

    static synchronized File prepare(Context context, Connection connection) throws Exception {
        String identity = connection.origin + "\n" + connection.token;
        if (prepared != null && identity.equals(preparedFor) && prepared.isFile()) return prepared;
        byte[] input;
        try (ZipFile apk = new ZipFile(context.getApplicationInfo().sourceDir)) {
            ZipEntry entry = apk.getEntry("assets/index.android.bundle");
            if (entry == null || entry.getSize() != HermesPatch.INPUT_SIZE) throw new IllegalArgumentException("不支持的 bundle");
            try (InputStream stream = apk.getInputStream(entry)) { input = Connection.readLimited(stream, HermesPatch.INPUT_SIZE); }
        }
        byte[] bytes = HermesPatch.patch(input, connection.origin, connection.token);
        File directory = new File(context.getNoBackupFilesDir(), "prokbot");
        if (!directory.isDirectory() && !directory.mkdirs()) throw new java.io.IOException("无法创建私有目录");
        File target = new File(directory, "gateway.hbc"), temp = new File(directory, "gateway.tmp");
        try (FileOutputStream out = new FileOutputStream(temp)) { out.write(bytes); out.getFD().sync(); }
        if (!temp.renameTo(target)) { temp.delete(); throw new java.io.IOException("无法保存补丁"); }
        prepared = target; preparedFor = identity;
        return target;
    }

    static synchronized void forget(Context context) {
        Connection.prefs(context).edit().clear().commit();
        Connection.credentials(context).delete();
        new File(context.getNoBackupFilesDir(), "prokbot/gateway.hbc").delete();
        new File(context.getNoBackupFilesDir(), "prokbot/gateway.tmp").delete();
        prepared = null; preparedFor = null;
    }
    static String status() { return status; }
    static boolean supported() { return supported; }
    private static synchronized void markLoaded(Context context) {
        loaded = true; status = "已加载自部署连接";
        if (!healthScheduled) {
            healthScheduled = true;
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                Connection.prefs(context).edit().putInt("pendingStarts", 0).apply();
                log("alive-after-30s");
            }, 30000);
        }
    }
    private static void fail(XC_MethodHook.MethodHookParam p, Throwable error) {
        status = "连接补丁加载失败（" + error.getClass().getSimpleName() + "）";
        log(status);
        // A configured connection must never silently fall back to official routing.
        p.setThrowable(new IllegalStateException(status));
    }
    private static void log(String event) { XposedBridge.log(TAG + ": " + event); }
}
