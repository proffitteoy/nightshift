# NightShift 当前画像

更新时间：2026-03-08

## 一、总体状态
- 后端主工程目录是 `backend/`，分层结构固定为 `api -> services -> repositories -> clients -> models -> prompts`。
- Android 主工程目录是 `android-app/`，四标签页骨架固定为 `MainActivity + Fragment + Navigation`。
- Tab3 静态工作区目录是 `backend/static/showcase/`，Android 通过 WebView 加载 `/showcase/atlas/`。
- 账号体系已提供 `users`、JWT 鉴权、`POST /auth/register`、`POST /auth/login`、`GET /me` 和 GitHub OAuth。
- 密码登录与 GitHub OAuth 使用相同邮箱时，视为两个不同的 NightShift 账户；只有在已登录状态下触发 GitHub connect 才会绑定到当前账户。
- GitHub OAuth 成功后会自动导入当前 GitHub 账号下的公开仓库订阅；私有仓库不会导入，只返回提示信息。

## 二、功能矩阵
| 页面 | 当前能力 | 当前承载 | 当前入口 |
|---|---|---|---|
| 页面1 一周热点 | 热点列表、趋势、项目详情两段式摘要 | Android 原生页面 + 后端接口 | `GET /api/trending/generate-analysis`、`POST /api/trending/detail-summary` |
| 页面2 晨报交接 | 仓库报告、摘要卡、追问问答 | Android 原生页面 + 后端接口 | `POST /api/project/report-by-user`、`GET /api/project/daily-report`、`POST /api/project/report-qa` |
| 页面3 代码全景图 | Atlas 工作区、图谱浏览、节点与代码联动 | `backend/static/showcase/` + Android WebView | `/showcase/atlas/` |
| 页面4 订阅中心 | 登录、注册、GitHub OAuth、账号信息、订阅 CRUD、运行时配置、发送入口 | Android 原生页面 + 后端接口 | `POST /auth/register`、`POST /auth/login`、`POST /auth/github/start`、`GET /auth/github/poll/{poll_token}`、`GET /me`、`GET/POST/PUT/DELETE /api/subscriptions`、`GET/PUT/DELETE /api/subscriptions/runtime-config` |

## 三、当前契约
1. Tab1 到 Tab3 不做登录拦截，匿名用户仍可通过输入 GitHub 仓库 URL 使用核心能力。
2. Tab4 承载账号体系、订阅、运行时配置和邮件发送，不新增独立登录 Activity。
3. 已登录用户的页面2快照与日报产物按 `user_id + 日期 + 仓库` 隔离存储。
4. `subscriptions` 与 `runtime_configs` 以 `user_id` 隔离；写操作必须携带 Bearer Token。
5. 页面2统一使用 `POST /api/project/report-by-user` 生成报告；追问使用 `POST /api/project/report-qa`。
6. 页面3继续承载现有 Atlas 工作区，不改成 Android 原生替代方案。
7. GitHub OAuth 使用“后端 start + 浏览器授权 + callback + poll”闭环，不新增 Android 深链登录页面。
8. 邮件发送优先复用“同用户 + 同仓库”的最近本地报告；若用户已配置 GitHub token 且旧缓存对应空快照，则跳过缓存并重新抓取 GitHub。
9. 默认不信任客户端输入、请求头、数据库现存字段、缓存命中和外部 API 返回；服务端必须重新校验后再使用。
10. `/api/proxy` 只允许访问白名单 GitHub HTTPS 主机，不转发客户端自带的上游 `Authorization`。

## 四、数据边界
- 后端运行目录是 `commit_data/`、`analysis_data/`、`reports/`、`sqlite_data/`。
- 业务数据库是 `sqlite_data/nightshift.db`。
- `users`、`subscriptions`、`runtime_configs` 共享同一份 SQLite 文件，但按 `user_id` 作用域隔离。
- 已登录用户的页面2产物写入 `commit_data/user_{id}/` 与 `reports/user_{id}/`。
- Android 本地保存 `SessionStore`、`CurrentRepoStore`、`Hot_Git.db`、`Git_Self.db`；其中 `SessionStore` 优先使用加密 SharedPreferences。

## 五、当前安全与防闪退基线
- GitHub OAuth 回调地址只从 `NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI` 或 `NIGHTSHIFT_PUBLIC_BASE_URL` 解析，不信任请求里的 Host/Header。
- Android 打开 OAuth 浏览器前会校验 `https://github.com/login/oauth/authorize`，非预期 URL 直接拒绝。
- Android 通知广播接收器 `android:exported="false"`，仅响应应用内固定 action。
- Android 本地通知调度、展示和广播回调全部做异常兜底，权限异常或厂商实现异常只降级提示，不中断主流程。
- Android 只对白名单 API 主机开放 cleartext 流量，release 默认关闭网络日志。
- Android 关闭应用数据备份，避免会话数据进入系统备份链路。

## 六、当前验证口径
- backend：`python -m compileall backend`
- backend：关键链路 smoke，包括账号隔离、OAuth 回调地址、报告缓存复用与鉴权校验
- Android：`assembleDebug`、`lintDebug`、`testDebugUnitTest`

## 七、当前风险
1. Android `BASE_URL` 当前仍是明文 HTTP 地址 `http://8.163.4.22:8000/`，生产环境应替换为 HTTPS 域名。
2. GitHub OAuth 依赖后端公网可回调地址与环境变量配置；未配置时 Tab4 只能继续使用邮箱密码登录。
3. 页面2问答质量仍依赖运行时 LLM 配置与 GitHub 上下文抓取完整度。
4. 后端 SQLite 仍不是完整多租户权限系统，只实现了应用层隔离和校验。
