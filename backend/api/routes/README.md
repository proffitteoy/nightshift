# 路由模块说明

更新日期：2026-03-07

## general
- `GET /`：健康检查。
- `GET/POST/OPTIONS /api/proxy`：GitHub 代理，供 Atlas 工作区克隆仓库时复用；若客户端未显式传认证头，代理会自动注入页面4已保存的 `GITHUB_TOKEN`，用于私有仓库访问。
- `GET /favicon.ico`：页面3运行时图标兜底。
- `POST /api/config/token`：写入进程级 `GITHUB_TOKEN`（不持久化）。
- `POST /api/config/llm`：写入进程级 LLM 运行参数（不持久化）。

## trending
- `GET /api/trending/weekly`：读取周热点数据。
- `GET /api/trending/generate-analysis`：拉取并生成热点分析列表。
- `POST /api/trending/detail-summary`：为页面1详情页按项目生成两段式 LLM 详情解读；未配置模型时回退到规则摘要。

## project
- `POST /api/project/subscribe`：按仓库抓取最近活动并落盘快照。
- `GET /api/project/daily-report`：基于最近快照生成晨报；必要时会从订阅仓库引导一次生成。
- `POST /api/project/report-by-user`：按指定仓库即时生成晨报。
- `POST /api/project/report-qa`：基于当前晨报回答追问；请求体可额外携带 `repo_url`，用于补充 README、目录结构、变更文件、PR、Commit 上下文；未配置 LLM 时走规则回退。

## code_panorama
- `POST /api/repo/code-panorama`：生成函数节点与调用边（MVP 图谱）。

## subscriptions
- `GET /api/subscriptions`：查询订阅列表。
- `POST /api/subscriptions`：创建订阅。
- `PUT /api/subscriptions/{subscription_id}`：更新订阅。
- `DELETE /api/subscriptions/{subscription_id}`：删除订阅。
- `GET /api/subscriptions/runtime-config`：读取持久化运行时配置状态。
- `PUT /api/subscriptions/runtime-config`：保存 GitHub Token 与 LLM 配置（持久化）。

## 忙碌错误码（503）
- `SUBSCRIBE_BUSY` / `REPORT_BUSY`：页面2并发重计算锁等待超时。
- `PANORAMA_BUSY`：页面3全景图生成锁等待超时。
- `ANALYSIS_BUSY`：页面1热点分析生成锁等待超时。

## 前端联调提示
- 页面1列表继续调用 `GET /api/trending/generate-analysis`；进入详情后再调用 `POST /api/trending/detail-summary`，详情文案应与列表摘要区分。
- 页面2“按当前仓库生成”和“按 URL 生成”都应调用 `POST /api/project/report-by-user`，仅 `repo_url` 来源不同。
- 页面2晨报追问建议附带 `repo_url`，这样后端才能读取目标仓库的 README、PR、Commit 与变更上下文。
- 页面4订阅 UI 可以隐藏 `frequency/update_strategy`，但创建和更新请求仍要继续传固定默认值，避免破坏后端模型校验。
- 页面3由 Android WebView 直接加载 `/showcase/atlas/`，路由层仅提供代理、图标和数据能力。
