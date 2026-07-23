# NightShift 后端说明

更新日期：2026-03-08

## 1. 当前定位
`backend/` 是 NightShift 的后端主工程，目录分层固定为 `api -> services -> repositories -> clients -> models -> prompts`。Tab3 静态工作区并入 `backend/static/showcase/`，统一由后端托管。

## 2. 目录职责
- `api/`
  - HTTP 路由、依赖注入、错误映射与中间件
- `services/`
  - 页面1/2/3/4 业务编排
- `repositories/`
  - SQLite 与 JSON 持久化
- `clients/`
  - GitHub、LLM、邮件与 Trending 外部调用
- `models/`
  - Pydantic 契约模型
- `prompts/`
  - 提示词模板与注册
- `config/`
  - LLM 配置模板
- `static/showcase/`
  - Tab3 静态工作区

## 3. 当前接口
- `GET /`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/github/start`
- `GET /auth/github/poll/{poll_token}`
- `GET /auth/github/callback`
- `GET /me`
- `GET/POST/OPTIONS /api/proxy`
- `POST /api/config/token`
- `POST /api/config/llm`
- `GET /api/trending/weekly`
- `GET /api/trending/generate-analysis`
- `POST /api/trending/detail-summary`
- `POST /api/project/subscribe`
- `GET /api/project/daily-report`
- `POST /api/project/report-by-user`
- `POST /api/project/report-qa`
- `POST /api/repo/code-panorama`
- `POST /api/repo/workflow-analysis`
- `GET /api/subscriptions`
- `GET /api/subscriptions/runtime-config`
- `PUT /api/subscriptions/runtime-config`
- `DELETE /api/subscriptions/runtime-config`
- `POST /api/subscriptions`
- `PUT /api/subscriptions/{subscription_id}`
- `POST /api/subscriptions/{subscription_id}/send`
- `DELETE /api/subscriptions/{subscription_id}`

## 4. 当前行为
- 账号：
  - `POST /auth/register`、`POST /auth/login` 返回 Bearer Token。
  - `GET /me` 返回当前登录用户信息。
  - GitHub OAuth 走 `start -> callback -> poll` 闭环。
  - 同邮箱的密码账号和 GitHub OAuth 账号默认视为两个独立账户；只有已登录状态下的 connect 流程才绑定 GitHub。
  - GitHub OAuth 成功后自动导入公开仓库订阅；私有仓库不导入，只在消息里提示。
- 页面2：
  - 统一通过 `POST /api/project/report-by-user` 生成报告。
  - 追问通过 `POST /api/project/report-qa`。
  - 邮件发送优先复用“同用户 + 同仓库”的最近本地报告缓存。
  - 若用户已配置 GitHub token，发信时不会复用由空快照生成的旧缓存报告，而是重新抓取仓库后生成邮件。
  - BigModel 默认模型为 `glm-4-flash`，并对 `open.bigmodel.cn` 增加最小请求间隔与 429 冷却退避。
- 页面3：
  - 静态入口是 `/showcase/atlas/`。
  - GitHub clone 与资源代理通过 `/api/proxy`。
- 页面4：
  - 订阅、运行时配置和发送入口全部由后端承载。
  - 邮件发送走阿里云 Direct Mail RPC，不依赖 `alibabacloud-gateway-spi`。

## 5. 数据与隔离
- 运行时目录：`commit_data/`、`analysis_data/`、`reports/`、`sqlite_data/`
- 业务数据库：`sqlite_data/nightshift.db`
- `users`、`subscriptions`、`runtime_configs` 共用一份 SQLite，但按 `user_id` 作用域隔离。
- 页面2产物按 `commit_data/user_{id}/` 与 `reports/user_{id}/` 隔离落盘。

## 6. 安全边界
- 默认不信任请求参数、请求头、JWT、缓存命中、数据库历史字段和外部 API 返回值；读取后必须重新校验。
- GitHub OAuth 回调地址只从 `NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI` 或 `NIGHTSHIFT_PUBLIC_BASE_URL` 推导。
- `/api/proxy` 仅允许访问白名单 GitHub HTTPS 主机，不转发客户端自带的上游 `Authorization`。
- 运行时配置中的 `llm_base_url` 与 `email_endpoint` 会经过白名单和协议校验。
- 5xx 错误统一映射成受控消息，避免把内部异常直接暴露给客户端。

## 7. 常用命令
- `python -m compileall backend`
- `python -m backend.main`

## 8. 关键环境变量
- `NIGHTSHIFT_PUBLIC_BASE_URL`
- `NIGHTSHIFT_GITHUB_OAUTH_CLIENT_ID`
- `NIGHTSHIFT_GITHUB_OAUTH_CLIENT_SECRET`
- `NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI`
- `NIGHTSHIFT_JWT_SECRET`
- `NIGHTSHIFT_EMAIL_REPORT_CACHE_TTL_MINUTES`
- `NIGHTSHIFT_ALLOWED_LLM_HOSTS`
- `NIGHTSHIFT_ALLOWED_EMAIL_ENDPOINTS`
- `NIGHTSHIFT_PROXY_ALLOWED_HOSTS`

## 9. 当前风险
- 对外地址当前仍是 `http://8.163.4.22:8000/`，生产环境应切换为 HTTPS 域名。
- SQLite 仅提供应用层隔离，不是完整数据库权限模型。
- 页面2质量仍依赖 GitHub 上下文与运行时 LLM 配置完整度。
