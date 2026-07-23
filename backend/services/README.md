# 服务层说明

更新日期：2026-03-05

## 服务清单
- `TrendingService`：页面1热点抓取与分析文件落盘。
- `ProjectService`：页面2仓库活动抓取、晨报生成、仓库上下文缓存、问答编排与兜底输出。
- `CodePanoramaService`：页面3全景图节点/边生成（MVP）。
- `SubscriptionService`：页面4订阅 CRUD 与运行时配置持久化。
- `ConcurrencyGuard`：跨进程任务锁封装（加锁、轮询等待、超时抛错）。

## 当前关键策略
- GitHub 匿名限流时，`ProjectService` 回退到空快照，保证页面2仍可渲染。
- 仓库上下文抓取结果落盘到 `runtime/analysis_data/repo_context/`；每次请求按上下文预算动态生成 `analysis_prompt_context`，供外部 Agent 平台复用。
- `daily-report` 支持从订阅仓库自动引导，降低 `repository=unknown` 概率。
- LLM 客户端先走模型，失败时回退规则生成，并记录评估日志。
- 重计算入口统一通过 `ConcurrencyGuard` 控制并发，超时抛出 `ConcurrencyLockTimeoutError`，由路由层映射为 `503`。

## 约束
- 服务层不依赖 FastAPI 对象。
- 服务层输出在返回前必须满足 `backend/models/schemas.py` 契约。
