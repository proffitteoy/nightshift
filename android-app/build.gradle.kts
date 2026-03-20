// 顶层构建文件，可在此添加所有子模块通用的配置项。
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
}
