# 提示词目录说明

更新日期：2026-03-08

## 目录结构
- `registry.py`
  - 提示词注册中心
- `templates/report_qa_v1.txt`
  - 晨报问答模板
- `templates/report_qa_v2.txt`
  - 晨报问答模板，补充仓库上下文
- `templates/trending_detail_summary_v1.txt`
  - 页面1 热点详情摘要模板
- `templates/trending_detail_summary_v2.txt`
  - 页面1 热点详情摘要模板，两段式输出
- `templates/report_summary_v1.txt`
  - 晨报摘要模板
- `templates/report_summary_v2.txt`
  - 晨报摘要模板
- `templates/report_todo_v1.txt`
  - 待办生成模板
- `templates/report_todo_v2.txt`
  - 待办生成模板

## 规则
- 命名遵循 `场景_模块_版本`。
- 新模板必须可回滚，不直接覆盖已有模板文件。
- 晨报问答当前优先使用 `report_qa_v2`，同时参考晨报内容与仓库上下文。
- 页面1详情摘要当前优先使用 `trending_detail_summary_v2`，要求输出与列表摘要不同的两段式解读。
