package app.prokbot.bridge;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class LauncherActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(24 * getResources().getDisplayMetrics().density); view.setPadding(padding, padding * 2, padding, padding);
        TextView title = new TextView(this); title.setText("ProkBot Bridge"); title.setTextSize(26); view.addView(title);
        TextView instructions = new TextView(this); instructions.setTextSize(16);
        instructions.setText("实验版 · 支持 Grok Bot 1.19.1 (3050)\n\n在 LSPosed 中启用本模块，作用域选择 Grok Bot。强制停止后重新打开 Grok Bot，点击右上角 ProkBot，输入 Host 地址和配对码。\n\nHost 需要包含 Android 配对支持。配对成功后关闭并重新打开 Grok Bot。\n\n若需要恢复原应用连接，在 ProkBot 设置中关闭连接，或在 LSPosed 中停用本模块，然后强制停止并重新打开 Grok Bot。");
        view.addView(instructions);
        Button open = new Button(this); open.setText("打开 Grok Bot"); view.addView(open);
        open.setOnClickListener(v -> {
            Intent intent = getPackageManager().getLaunchIntentForPackage("ai.x.grok.bot");
            if (intent != null) startActivity(intent);
            else instructions.setText("未找到 Grok Bot，请先从 Google Play 安装支持的版本。");
        });
        setContentView(view);
    }
}
