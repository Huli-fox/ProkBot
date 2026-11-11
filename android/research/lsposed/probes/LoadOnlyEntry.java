package app.prokbot.bridge;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

/** Isolation probe: does not access host classes, install hooks, or change app state. */
public final class LoadOnlyEntry implements IXposedHookLoadPackage {
    @Override public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lp) {
        if ("ai.x.grok.bot".equals(lp.packageName) && "ai.x.grok.bot".equals(lp.processName)) {
            XposedBridge.log("ProkBotBridge: load-only-probe; no hooks registered");
        }
    }
}
