# auto-dev-loop 执行说明

更新日期：2026-03-05

## 五步闭环
1. `step1_需求输入.jsonl`：锁定范围、验收、约束。
2. `step2_执行计划.jsonl`：拆分任务并冻结契约。
3. `step3_实施变更.jsonl`：实施代码与文档改动。
4. `step4_验证发布.jsonl`：功能、契约、视觉三重验证。
5. `step5_总控与循环.jsonl`：归档结论并输入下一轮。

## 项目附加约束
- 不推翻 Android 导航骨架。
- 页面3/4改动必须回归页面1/2。
- 接口变化必须同步更新：
  - `android-app/README.md`
  - `backend/static/showcase/README.md`
  - `docs/NightShift-current-portrait.md`
- 涉及 LLM 的改动必须记录提示词版本与参数。
