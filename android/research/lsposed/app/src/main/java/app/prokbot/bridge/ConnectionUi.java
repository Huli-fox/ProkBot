package app.prokbot.bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class ConnectionUi {
    private static final String TAG = "prokbot-settings-entry";
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static boolean firstResume = true;
    private ConnectionUi() {}

    static void attach(Activity activity) {
        ViewGroup decor = (ViewGroup)activity.getWindow().getDecorView();
        if (decor.findViewWithTag(TAG) == null) {
            TextView entry = new TextView(activity);
            entry.setTag(TAG); entry.setText("ProkBot"); entry.setTextSize(12);
            entry.setTextColor(0xffe9edf2); entry.setBackgroundColor(0xe6333943);
            entry.setGravity(Gravity.CENTER); entry.setPadding(dp(activity, 10), dp(activity, 6), dp(activity, 10), dp(activity, 6));
            entry.setContentDescription("ProkBot 连接设置");
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.END);
            lp.topMargin = dp(activity, 50); lp.rightMargin = dp(activity, 8);
            decor.addView(entry, lp); entry.setOnClickListener(v -> show(activity));
        }
        if (firstResume) {
            firstResume = false;
            if (!Connection.prefs(activity).getBoolean("enabled", false)) new Handler(Looper.getMainLooper()).postDelayed(() -> {
                if (!activity.isFinishing() && !activity.isDestroyed()) show(activity);
            }, 600);
        }
    }

    static void show(Activity activity) {
        Connection current = Connection.read(activity);
        LinearLayout layout = new LinearLayout(activity); layout.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(activity, 20); layout.setPadding(padding, padding / 2, padding, 0);
        TextView status = new TextView(activity); status.setText(HookEntry.status()); layout.addView(status);
        EditText origin = field(activity, layout, "Host 地址（HTTPS）", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        origin.setText(current == null ? "" : current.origin);
        EditText code = field(activity, layout, "六位配对码", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        EditText name = field(activity, layout, "设备名称", InputType.TYPE_CLASS_TEXT);
        name.setText(Build.MODEL);
        if (current != null && !Connection.prefs(activity).getBoolean("enabled", false)) {
            Button resume = new Button(activity); resume.setText("重新启用已保存连接"); layout.addView(resume);
            resume.setOnClickListener(v -> {
                if (!HookEntry.supported()) return;
                Connection.prefs(activity).edit().putBoolean("enabled", true).putInt("pendingStarts", 0).commit();
                restartMessage(activity, "已重新启用。请关闭后重新打开 Grok Bot。");
            });
        }
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("连接自部署 Host").setView(layout)
            .setPositiveButton(current == null ? "配对" : "重新配对", null)
            .setNegativeButton(current == null ? "取消" : "关闭连接", null).setNeutralButton("收起", null).create();
        dialog.setOnShowListener(ignored -> {
            Button pair = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            pair.setEnabled(HookEntry.supported());
            pair.setOnClickListener(v -> {
                final String address = origin.getText().toString(), key = code.getText().toString(), device = name.getText().toString();
                pair.setEnabled(false); status.setText("正在配对…");
                WORKER.execute(() -> {
                    try {
                        // Validate the pinned bundle before consuming a one-time pairing code.
                        HookEntry.prepare(activity, new Connection(Origin.normalize(address), "PROKBOT_VALIDATION_ONLY_000000000000", ""));
                        Connection next = Connection.pair(address, key, device);
                        next.save(activity); // Persist first: a later preparation/registration error must not lose the issued token.
                        HookEntry.prepare(activity, next);
                        try { next.register(); } catch (Exception ignoredRegistration) { /* Pairing is still valid. */ }
                        activity.runOnUiThread(() -> {
                            if (activity.isDestroyed() || activity.isFinishing()) return;
                            dialog.dismiss(); restartMessage(activity, "配对成功。关闭后重新打开 Grok Bot，即可使用这台 Host。");
                        });
                    } catch (Exception error) {
                        String message = error instanceof IllegalArgumentException ? error.getMessage()
                            : "连接失败（" + error.getClass().getSimpleName() + "），请检查网络、证书和 Host 状态";
                        activity.runOnUiThread(() -> {
                            if (activity.isDestroyed()) return;
                            status.setText(message); pair.setEnabled(true);
                        });
                    }
                });
            });
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setOnClickListener(v -> {
                dialog.dismiss();
                if (current != null) {
                    HookEntry.forget(activity);
                    restartMessage(activity, "本机连接已清除。请在 Host 管理页撤销这台设备；关闭后重新打开将使用原应用连接。");
                }
            });
        });
        dialog.show();
    }

    private static EditText field(Activity activity, LinearLayout layout, String hint, int type) {
        EditText field = new EditText(activity); field.setHint(hint); field.setSingleLine(true); field.setInputType(type);
        layout.addView(field, new LinearLayout.LayoutParams(-1, -2)); return field;
    }
    private static void restartMessage(Activity activity, String text) {
        new AlertDialog.Builder(activity).setTitle("ProkBot").setMessage(text)
            .setPositiveButton("关闭应用", (d, w) -> {
                activity.finishAndRemoveTask();
                new Handler(Looper.getMainLooper()).postDelayed(() -> android.os.Process.killProcess(android.os.Process.myPid()), 300);
            }).setNegativeButton("稍后", null).show();
    }
    private static int dp(Activity a, int value) { return Math.round(value * a.getResources().getDisplayMetrics().density); }
}
