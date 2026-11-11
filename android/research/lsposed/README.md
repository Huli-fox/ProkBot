# LSPosed 研究归档：当前不可用

这里保留早期实验源码和诊断探针，不作为 Android 安装入口。实际可用的 root + adb 工具见 [Android 安装说明](../../README.md)。

在 Android 11 / arm64、Grok Bot 1.19.1 (3050)、LSPosed 1.9.2 (7024) 的测试组合上，即使只加载模块、完全不注册 Hook，也会在 PairIP 内闪退。`build.py` 默认拒绝生成 APK；`--load-only-probe`、`--startup-probe`、`--experimental-lsposed` 仅用于研究。

Java `HermesPatch` 保留早期网关实验配方，未同步可用 Python 工具的 `gateway-send-v2` 发送修复。这里的界面、APK 和测试通过都不能作为可用客户端的证据。

研究构建需要 Android SDK platform 34 / build-tools 34.0.0、JDK 17，以及仅参与编译的 Xposed API 82。API JAR 来自 `https://api.xposed.info/de/robv/android/xposed/api/82/api-82.jar`，SHA-256 固定为 `f48c635f1c7469fdec0e00ad2ea0b7a6b2f5b55065784a35b7ca3a84615e8e25`。默认输出和开发签名保存在仓库忽略的 `output.noindex/android-lsposed`，不包含官方 APK 或 bundle。

本原型参考了 MBGA 的限定作用域、入口声明和配置分层方式，未复制其源码或引入其依赖。对照实验结果见 [Android 评估](../../../docs/ANDROID-ASSESSMENT.md#lsposed-对照实验)。
