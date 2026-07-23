# 接口层说明

更新日期：2026-03-05

## 职责
- 提供统一 HTTP 路由入口。
- 校验请求参数并返回契约化响应。
- 将服务层异常映射为统一错误结构：
  - `{"success": false, "error": {"code": "...", "message": "..."}}`
- 通过依赖注入统一管理服务实例。
- 通过请求日志中间件记录请求耗时。

## 文件
- `app_factory.py`：应用创建、路由挂载、`/showcase` 静态托管、启动时加载持久化运行时配置。
- `dependencies.py`：服务与仓储依赖注入。
- `error_handlers.py`：统一错误输出。
- `request_logging.py`：请求 ID、路径、状态码、耗时日志。
- `feature_flags.py`：页面3/4功能开关。
- `routes/`：业务路由。

## 路由分组
- `routes/general.py`：根接口、代理接口、临时写入 Token/LLM 配置。
- `routes/project.py`：页面2报告相关接口。
- `routes/trending.py`：页面1热点与分析。
- `routes/code_panorama.py`：页面3代码全景图、工作流仓库分析与外部 Agent 仓库上下文接口。
- `routes/subscriptions.py`：页面4订阅中心与持久化运行时配置。

## 并发控制映射
- 路由层捕获 `ConcurrencyLockTimeoutError` 并返回 `503`。
- 当前已使用的忙碌错误码：`REPORT_BUSY`、`SUBSCRIBE_BUSY`、`PANORAMA_BUSY`、`ANALYSIS_BUSY`、`REPO_CONTEXT_BUSY`。
