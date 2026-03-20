# android-app/app 模块说明

更新日期：2026-03-08

## 1. 模块定位
`android-app/app/` 是 NightShift Android 应用模块，负责四标签页原生容器、网络接线、本地会话与通知兜底。

## 2. 目录分工
- `src/main/java/com/example/myapplication3/auth/`
  - 登录态缓存与会话读写
- `src/main/java/com/example/myapplication3/database/`
  - 设备本地数据库与下载逻辑
- `src/main/java/com/example/myapplication3/network/`
  - Retrofit 接口、拦截器、请求/响应模型
- `src/main/java/com/example/myapplication3/notifications/`
  - 本地提醒调度、广播接收、防闪退保护
- `src/main/java/com/example/myapplication3/ui/home/`
  - 页面1 一周热点
- `src/main/java/com/example/myapplication3/ui/chat/`
  - 页面2 晨报交接
- `src/main/java/com/example/myapplication3/ui/dashboard/`
  - 页面3 WebView 工作区
- `src/main/java/com/example/myapplication3/ui/notifications/`
  - 页面4 登录、账号、订阅、运行时配置
- `src/main/res/`
  - 布局、导航、字符串、主题与图标资源

## 3. 契约约束
- 保留 `MainActivity + Fragment + Navigation`，不拆成新的启动壳。
- Tab3 只承载 `/showcase/atlas/`，不在 Android 端重写图谱逻辑。
- Tab4 承载登录、GitHub OAuth、订阅与运行时配置。
- Tab1 到 Tab3 不做登录拦截，匿名用户仍可通过仓库 URL 使用核心能力。
- 本地通知异常只能降级提示，不能中断订阅主流程。

## 4. 本地状态
- `SessionStore`
  - JWT 与最近一次账号快照
- `CurrentRepoStore`
  - 当前查看仓库
- `Hot_Git.db`、`Git_Self.db`
  - 设备本地数据

## 5. 验证命令
- `..\gradlew.bat :app:assembleDebug`
- `..\gradlew.bat :app:lintDebug`
- `..\gradlew.bat :app:testDebugUnitTest`
