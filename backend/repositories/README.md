# 仓储层说明

更新日期：2026-03-05

## 职责
- SQLite 持久化：订阅、运行时配置、LLM 评估记录、并发任务锁。
- JSON 落盘：快照、分析、报告产物。
- 统一运行目录管理。

## 主要模块
- `paths.py`：运行目录与数据库路径。
- `json_repository.py`：JSON 原子写入与读取。
- `trending_repository.py`：热点数据持久化。
- `subscription_repository.py`：订阅与 `runtime_configs` 表。
- `llm_evaluation_repository.py`：LLM 调用评估记录。
- `job_lock_repository.py`：`job_locks` 表与锁获取/释放。

## 当前存储策略
- SQLite 连接统一启用 `WAL + busy_timeout`，降低并发写锁冲突概率。
- JSON 文件通过“临时文件 + 替换”方式写盘，避免半写入损坏。
- 运行时目录默认在仓库根目录，可由 `NIGHTSHIFT_RUNTIME_ROOT` 重定向。

## 数据表
- `subscriptions`
- `runtime_configs`
- `llm_evaluations`
- `job_locks`
