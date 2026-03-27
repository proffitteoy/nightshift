# 数据库 ER 图说明

本文档以文字形式描述项目中数据库实体（表）及其关系，便于生成 ER 图或作为架构说明使用。

## 实体清单与字段（简要）

- `users`
  - id (PK)
  - email
  - password_hash
  - display_name
  - auth_source
  - github_id
  - github_login
  - avatar_url
  - is_active
  - created_at, updated_at

- `subscriptions`
  - id (PK)
  - user_id (FK -> users.id, nullable)
  - repo_url
  - morning_report_enabled
  - code_panorama_enabled
  - recipient_email
  - delivery_mode, frequency, delivery_time, update_strategy
  - last_delivery_at, last_delivery_attempt_at, last_delivery_error
  - created_at, updated_at

- `runtime_configs`
  - id (PK)
  - user_id (FK -> users.id, nullable)
  - key
  - value
  - updated_at

- `oauth_sessions`（表名：`oauth_sessions`）
  - id (PK)
  - state_token (unique)
  - poll_token (unique)
  - requested_by_user_id (FK -> users.id, nullable)
  - flow_type, redirect_uri, authorization_url
  - status, result_* 字段（access token、user json 等）
  - expires_at, completed_at, created_at, updated_at

- `job_locks`（或 `job_locks`）
  - lock_key (PK)
  - owner_id
  - expires_at
  - updated_at

- `llm_evaluations`
  - id (PK)
  - created_at
  - provider, model, prompt_name, prompt_version
  - temperature, top_p, max_tokens
  - success (bool), fallback_used (bool)
  - latency_ms, output_preview, error_message

- `commit_snapshots`（文件/对象存储索引）
  - id (PK)
  - repository (text)
  - file_path (text) 或 object_storage_key
  - fetch_time
  - metadata (json)

- `reports`
  - id (PK)
  - repository
  - report_file_path 或 object_storage_key
  - generated_at
  - generated_by_user_id (FK -> users.id, nullable)
  - report_summary (json)

- `weekly_data`（独立 trending DB）
  - id (PK)
  - name, author, language, stars_total, forks_total, issues_total, date

- `project_data`（独立 trending DB）
  - id (PK)
  - name (unique), author, link, creation_date


## 实体关系说明（文字 ER）

1. `users` 1 - N `subscriptions`
   - 说明：一个用户可以创建多个订阅；`subscriptions.user_id` 可为空表示全局/匿名订阅（代码中采用 `IFNULL(user_id, 0)` 唯一索引策略）。

2. `users` 1 - N `runtime_configs`
   - 说明：用户可有多条运行时配置（key/value），用于覆盖 LLM、邮件等运行时参数；也支持 user_id 为 NULL 的全局默认配置。

3. `users` 1 - N `oauth_sessions`
   - 说明：OAuth 登录/回调流程创建 session 记录，`requested_by_user_id` 用于关联发起该流的用户（可为 NULL）。

4. `subscriptions` -> `reports`（逻辑关联，非直接 FK）
   - 说明：订阅触发报告生成或引用已产生的 `reports` 文件；实现上 `subscriptions` 不直接 FK 指向 `reports`，而是通过 `repository / repo_url` 与 `reports.repository` 的语义关联检索历史报告。

5. `reports` -> `commit_snapshots`（一对多/多对一，语义关联）
   - 说明：每次生成报告通常基于一个快照（snapshot）；快照以文件形式存储，`reports` 包含 `data_file` 路径来引用快照。实现上快照存为文件/对象存储并由 `JsonRepository` 管理，数据库可只保存索引路径。

6. `llm_evaluations`（独立审计表）
   - 说明：记录 LLM 调用的元数据、耗时与结果预览；可选上链到 `reports` 或 `users`（当前实现未强制 FK），但语义上可关联 `generated_by_user_id` 或 `report_id`，便于追溯。

7. `job_locks`（独立表）
   - 说明：用于进程间/线程间的抢占与超时锁定，保证对同一 `lock_key` 的串行化处理（例如仓库级别的并发生成、订阅投递）。

8. `weekly_data` / `project_data`（trending DB）
   - 说明：热点数据被写入独立的 `TRENDING_DB`，与主 DB 分离。`project_data.name` 为唯一键，`weekly_data` 保存每日快照供前端展示与统计分析。


## 数据流（生成交接包/报告时的关系流程）

1. 用户或匿名请求 `report-by-user`（可能携带 `token`）：API 层校验并读取 `runtime_configs`（若 user_id 提供）。
2. 服务层尝试从 `reports` 目录/索引中读取可用缓存（按 `repository` 和 `generated_at` TTL）。
3. 若未命中缓存，服务调用 GitHub 客户端获取数据并将快照存为 `commit_snapshots`（或对象存储），同时可在数据库或索引表中记录快照路径。
4. 调用 LLM 生成报告，服务可创建 `llm_evaluations` 记录（审计/监控），并将最终报告保存为 `reports`（文件并在 DB 中记录索引与元数据）。
5. 若请求来自订阅投递，`SubscriptionDeliveryService` 根据 `subscriptions` 配置选择 `reports` 并执行邮件投递；投递结果通过 `record_delivery_attempt` 更新 `subscriptions.last_delivery_*` 字段。
6. 整个过程中，`ConcurrencyGuard`/`job_locks` 保证对同一仓库的并发操作被串行化，防止重复生成或竞态写入。


## 关系摘要（便于绘图）

- `users` 1--* `subscriptions`
- `users` 1--* `runtime_configs`
- `users` 1--* `oauth_sessions`
- `subscriptions` *--0..1 `reports`（通过 repository 字段语义关联）
- `reports` 1--* `commit_snapshots`（语义上：report 基于 snapshot）
- `llm_evaluations` 独立，可 0..1 -> `reports`（若实现强关联）
- `job_locks` 独立，用于锁定 `lock_key`
- `weekly_data` / `project_data` 位于独立 DB（TRENDING_DB）


## 绘图建议

- 主图（主 DB）：放置 `users`, `subscriptions`, `runtime_configs`, `oauth_sessions`, `reports`, `commit_snapshots`, `llm_evaluations`, `job_locks`，用 FK 箭头标注 `user_id`, `generated_by_user_id`, `requested_by_user_id`。
- 辅助图（trending）：单独绘制 `weekly_data` 与 `project_data`，并用虚线表示与 `reports.repository` 或 `subscriptions.repo_url` 的语义关联。 
- 在图上标注唯一约束（例如 `project_data.name` unique、`oauth_sessions.state_token` unique、`runtime_configs` 的 `(IFNULL(user_id,0), key)` unique）。

---

> 文件位置：`docs/ER.md`（已生成）

如需，我可以基于以上文字直接生成 PlantUML 源文件或 PNG/SVG ER 图并放入 `docs/` 目录。 
