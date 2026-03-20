# 模型契约层说明

更新日期：2026-03-05

## 作用
- 定义 API 入参与出参契约。
- 在服务层输出返回前做二次结构校验。

## 当前模型覆盖
- 基础配置请求：`GitHubTokenRequest`、`LLMRuntimeConfigRequest`
- 页面2请求：`RepoSubscriptionRequest`、`RepoReportRequest`
- 页面3请求：`CodePanoramaRequest`
- 页面4请求：
  - `SubscriptionCreateRequest`
  - `SubscriptionUpdateRequest`
  - `RuntimeConfigUpdateRequest`
- 页面1/2/3/4响应模型与统一错误模型。

## 约束
- 新增接口必须先补充模型定义，再写路由逻辑。
