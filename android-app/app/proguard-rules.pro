# 在此添加项目专用的 ProGuard 规则。
# 可通过 build.gradle 中的 proguardFiles 配置项
# 控制生效的规则文件集合。
#
# 更多说明见：
# 文档地址：http://developer.android.com/guide/developing/tools/proguard.html

# 如果项目在 WebView 中启用了 JavaScript 交互，请取消下列注释，
# 并将类名替换为 JavaScript 接口的完整限定名：
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   例如：public *;
#}

# 如需保留行号信息以便调试堆栈，请取消注释：
#-keepattributes SourceFile,LineNumberTable

# 如果已保留行号信息，且希望隐藏原始源码文件名，请取消注释：
#-renamesourcefileattribute SourceFile
