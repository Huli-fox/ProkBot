package app.prokbot.bridge;

import android.app.Application;
import android.content.Context;
import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

/** Local diagnostic only. Isolate one known startup program, leaving app/activity VM bodies intact. */
public final class StartupEntry implements IXposedHookLoadPackage {
    @Override public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lp) throws Throwable {
        if (!"ai.x.grok.bot".equals(lp.packageName) || !"ai.x.grok.bot".equals(lp.processName)) return;
        XposedBridge.log("ProkBotBridge: startup-probe-loaded");
        XposedHelpers.findAndHookMethod(System.class, "loadLibrary", String.class, new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if ("pairipcore".equals(p.args[0])) XposedBridge.log("ProkBotBridge: pairip-load-before");
            }
            @Override protected void afterHookedMethod(MethodHookParam p) {
                if ("pairipcore".equals(p.args[0])) XposedBridge.log("ProkBotBridge: pairip-load-after");
            }
        });
        Class<?> runner = XposedHelpers.findClass("com.pairip.VMRunner", lp.classLoader);
        XposedHelpers.findAndHookMethod(runner, "invoke", String.class, Object[].class, new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                if ("AGgbQ1WXTJRXPSkB".equals(p.args[0])) {
                    XposedBridge.log("ProkBotBridge: startup-probe-isolated-vm-startup");
                    p.setResult(null);
                } else XposedBridge.log("ProkBotBridge: startup-probe-other-vm-enter");
            }
            @Override protected void afterHookedMethod(MethodHookParam p) {
                XposedBridge.log("ProkBotBridge: startup-probe-vm-return");
            }
        });
        XposedBridge.log("ProkBotBridge: startup-probe-vm-hook-registered");
        Class<?> startup = XposedHelpers.findClass("com.pairip.StartupLauncher", lp.classLoader);
        XposedBridge.log("ProkBotBridge: startup-probe-class-resolved");
        XposedHelpers.findAndHookMethod(startup, "launch", new XC_MethodHook() {
            @Override protected void beforeHookedMethod(MethodHookParam p) {
                XposedBridge.log("ProkBotBridge: startup-probe-isolated-launch");
                p.setResult(null);
            }
        });
        XposedBridge.log("ProkBotBridge: startup-probe-hook-registered");
        XposedHelpers.findAndHookMethod(Application.class, "attach", Context.class, new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam p) {
                XposedBridge.log("ProkBotBridge: startup-probe-application-attached");
            }
        });
    }
}
