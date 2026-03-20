# android-app（Android 客户端）说明

更新日期：2026-03-08

## 1. 模块定位
`android-app/` 是 NightShift 的 Android 客户端根目录。实现必须服从 `docs/` 契约，优先阅读：
1. `../docs/SELECTED.md`
2. `../docs/NightShift-current-portrait.md`
3. `../docs/documents/03-交付文档/NightShift-PRD-技术方案.md`
4. `../docs/documents/00-基础指南/代码组织.md`
5. `../docs/documents/00-基础指南/强前置条件约束.md`

## 2. 当前约束
- 保留 `MainActivity + Fragment + Navigation` 骨架。
- 页面1、页面2、页面4 保持原生 Android 页面。
- 页面3继续通过 WebView 加载 `/showcase/atlas/`。
- Tab1 到 Tab3 不做登录拦截，匿名用户仍可通过仓库 URL 使用核心功能。
- Tab4 承载登录、账号信息、GitHub OAuth、订阅、运行时配置和邮件发送入口。
- 接口契约变化必须同步更新本 README、`app/README.md` 与 `../docs/`。

## 3. 页面映射
- 页面1 一周热点：`app/src/main/java/com/example/myapplication3/ui/home/`
- 页面2 晨报交接：`app/src/main/java/com/example/myapplication3/ui/chat/`
- 页面3 代码全景图：`app/src/main/java/com/example/myapplication3/ui/dashboard/`
- 页面4 订阅中心：`app/src/main/java/com/example/myapplication3/ui/notifications/`

## 4. 当前行为基线
- 账号：
  - 已接入 `POST /auth/register`、`POST /auth/login`、`GET /me`
  - 已接入本地 token 存储、请求拦截器、启动鉴权与退出登录
  - GitHub OAuth 使用浏览器授权 + 后端 callback + poll 闭环
  - 同邮箱的密码账号与 GitHub OAuth 账号视为两个独立 NightShift 账户
- 页面1：
  - 使用 `GET /api/trending/generate-analysis`
  - 详情使用 `POST /api/trending/detail-summary`
- 页面2：
  - 统一使用 `POST /api/project/report-by-user`
  - 标准快照读取 `GET /api/project/daily-report`
  - 追问使用 `POST /api/project/report-qa`
- 页面3：
  - WebView 指向 `/showcase/atlas/`
  - 不在客户端重写 Atlas 图谱逻辑
- 页面4：
  - 登录入口内嵌在 Tab4
  - 承载账号信息、订阅 CRUD、运行时配置与 GitHub OAuth
  - “发送邮件”在即时模式下只触发一次，不允许 `instant + manual` 双发

## 5. 当前安全与防闪退基线
- `SessionStore` 优先使用加密 SharedPreferences；不可用时才降级为普通 SharedPreferences。
- OAuth 浏览器跳转只允许 `https://github.com/login/oauth/authorize`。
- 通知广播接收器显式 `android:exported="false"`，仅接受应用内固定 action。
- 通知调度、通知展示、广播回调、异步 Retrofit 回调中的 UI 更新全部做异常兜底和视图存在性检查。
- 应用关闭系统数据备份，避免会话信息进入备份链路。
- 只对白名单 API 主机开放 cleartext 流量。
- release 默认关闭 HTTP 日志。

## 6. 本地数据边界
- `SessionStore`
  - JWT 与最近一次账号快照
- `CurrentRepoStore`
  - 当前查看仓库
- `Hot_Git.db`、`Git_Self.db`
  - 设备本地数据库

## 7. 构建环境
- JDK：21
- Gradle Wrapper：8.7
- Android SDK：
  - `platform-tools`
  - `platforms;android-34`
  - `build-tools;34.0.0`

## 8. 常用命令
1. `.\gradlew.bat :app:assembleDebug`
2. `.\gradlew.bat :app:lintDebug`
3. `.\gradlew.bat :app:testDebugUnitTest`

## 9. 常见定位点
- 页面3空白时，优先检查 `ApiClient.BASE_URL` 与 `/showcase/atlas/`。
- 页面2追问质量偏弱时，优先检查 Tab4 运行时配置中的 GitHub Token 和 LLM 配置。
- Tab4 异常时，优先检查登录态、GitHub OAuth 配置和通知权限兜底逻辑。
