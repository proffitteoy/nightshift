# NightShift PRD 与技术方案

更新日期：2026-03-08

## 一、文档目的
统一 NightShift 当前阶段的需求范围、架构基线、接口契约与验证口径，保证实现、联调与文档一致。

## 二、系统摘要
- 后端主工程位于 `backend/`，固定分层为 `api -> services -> repositories -> clients -> models -> prompts`。
- Android 客户端位于 `android-app/`，固定骨架为 `MainActivity + Fragment + Navigation`。
- Tab3 静态工作区位于 `backend/static/showcase/`，对外入口固定为 `/showcase/atlas/`。
- 账号体系支持邮箱密码、GitHub OAuth、JWT 鉴权和 `GET /me`。
- Tab1 到 Tab3 保持匿名可用；Tab4 承载登录态与用户隔离能力。

## 三、范围
### 3.1 范围内
- 本地账号注册、登录、`GET /me`
- GitHub OAuth 登录与 connect
- `subscriptions.user_id` 与 `runtime_configs.user_id` 用户隔离
- 页面1 热点列表与项目详情摘要
- 页面2 晨报生成、结构化摘要与追问
- 页面3 Atlas 工作区
- 页面4 登录、账号信息、订阅 CRUD、运行时配置、邮件发送、当前仓库选择

### 3.2 范围外
- 重写 Android 导航体系
- 完整多租户数据库权限系统
- 将 Tab3 改造成 Android 原生图谱实现

## 四、关键规则
1. Tab1 到 Tab3 不做登录拦截，匿名用户仍可通过输入仓库 URL 使用核心能力。
2. Tab4 内嵌登录入口，不新增独立登录页或深链 Activity。
3. 密码账号与 GitHub OAuth 账号以 `auth_source` 区分；同邮箱默认不自动合并。
4. 只有在已登录状态下触发 GitHub connect，才会把 GitHub 账号绑定到当前账户。
5. GitHub OAuth 成功后自动导入公开仓库订阅；私有仓库不导入，只提示数量。
6. 邮件发送优先复用“同用户 + 同仓库”的本地报告缓存；若用户已配置 GitHub token 且缓存对应空快照，则跳过缓存并实时重抓仓库。
7. Android 本地通知、OAuth 浏览器跳转和异步 UI 更新必须 fail-closed，不得因权限或机型异常导致闪退。
8. 服务端默认不信任请求参数、Header、JWT 载荷、数据库历史字段、缓存命中和外部 API 返回值，必须显式校验后再使用。

## 五、接口基线
### 通用
- `GET /`
- `GET /me`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/github/start`
- `GET /auth/github/poll/{poll_token}`
- `GET /auth/github/callback`
- `POST /api/config/token`
- `POST /api/config/llm`

### 页面1
- `GET /api/trending/weekly`
- `GET /api/trending/generate-analysis`
- `POST /api/trending/detail-summary`

### 页面2
- `POST /api/project/subscribe`
- `POST /api/project/report-by-user`
- `GET /api/project/daily-report`
- `POST /api/project/report-qa`

### 页面3
- `GET /api/subscriptions`
- `GET/POST/OPTIONS /api/proxy`
- `/showcase/atlas/`

### 页面4
- `GET /api/subscriptions`
- `POST /api/subscriptions`
- `PUT /api/subscriptions/{subscription_id}`
- `POST /api/subscriptions/{subscription_id}/send`
- `DELETE /api/subscriptions/{subscription_id}`
- `GET /api/subscriptions/runtime-config`
- `PUT /api/subscriptions/runtime-config`
- `DELETE /api/subscriptions/runtime-config`

## 六、页面契约
### 页面1
- 热点列表入口使用 `GET /api/trending/generate-analysis`。
- 项目详情入口使用 `POST /api/trending/detail-summary`。
- 详情内容必须与列表摘要区分为两段式输出。

### 页面2
- “按当前仓库生成”和“按 URL 生成”统一调用 `POST /api/project/report-by-user`。
- 标准快照入口保留 `GET /api/project/daily-report`。
- 追问入口使用 `POST /api/project/report-qa`，可附带 `repo_url`。
- 已登录用户的报告缓存与产物按 `user_id + 日期 + 仓库` 隔离。

### 页面3
- 页面3继续承载现有 Atlas 工作区，不切换为原生替代方案。
- Android 与浏览器访问同一套静态资源。
- `/api/proxy` 只允许访问白名单 GitHub HTTPS 主机。

### 页面4
- 页面4承载登录、GitHub OAuth、账号信息、订阅 CRUD、运行时配置和邮件发送。
- 未登录时只显示账号入口与说明；受保护区块默认隐藏。
- 订阅写操作与运行时配置操作必须携带 Bearer Token，并按 `user_id` 隔离。
- 订阅模型包含 `recipient_email`、`delivery_mode`、`delivery_time`；UI 默认仍透传 `frequency=daily` 与 `update_strategy=incremental`。

## 七、非功能要求
- GitHub、LLM、邮件的外部调用必须可超时、可失败、可回退。
- 重计算接口允许返回 `503` 忙碌错误：`REPORT_BUSY`、`SUBSCRIBE_BUSY`、`PANORAMA_BUSY`、`ANALYSIS_BUSY`。
- GitHub OAuth 回调地址只能来自 `NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI` 或 `NIGHTSHIFT_PUBLIC_BASE_URL`。
- Android 仅对白名单 API 主机开放 cleartext 流量；生产环境应切换到 HTTPS。
- JWT secret 必须可配置；未配置时只允许使用进程内临时 secret 作为开发兜底。

## 八、验证基线
1. `POST /auth/register`、`POST /auth/login` 与 `GET /me` 可闭环验证。
2. 同邮箱的密码账号与 GitHub OAuth 账号可以并存且互不覆盖。
3. 页面3可访问 `/showcase/atlas/`。
4. 页面2在有仓库上下文时可生成晨报并继续追问。
5. 页面2在上下文不足时仍返回结构化降级结果。
6. 页面4运行时配置可保存、读取与清空。
7. Android 可通过 `assembleDebug`、`lintDebug`、`testDebugUnitTest`。
8. 后端可通过 `python -m compileall backend` 与关键链路 smoke。
