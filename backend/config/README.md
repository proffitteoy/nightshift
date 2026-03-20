# 配置目录说明

更新日期：2026-03-08

## 文件
- `generator.json`：LLM 生成配置模板。
- `embedder.json`：向量模型配置模板。

## 默认模型配置
- `provider=glm`
- 默认 `base_url=https://open.bigmodel.cn/api/paas/v4/`
- 默认 `model=glm-4-flash`
- 兼容历史默认值 `glm-4.5-flash`，运行时会自动映射到 `glm-4-flash`

## 环境变量覆盖（推荐）
- `NIGHTSHIFT_GENERATOR_API_KEY`
- `NIGHTSHIFT_GENERATOR_BASE_URL`
- `NIGHTSHIFT_GENERATOR_MODEL`
- `NIGHTSHIFT_GENERATOR_TEMPERATURE`
- `NIGHTSHIFT_GENERATOR_TOP_P`
- `NIGHTSHIFT_GENERATOR_MAX_TOKENS`
- `NIGHTSHIFT_GENERATOR_TIMEOUT_SECONDS`
- `NIGHTSHIFT_GENERATOR_MAX_RETRIES`
- `NIGHTSHIFT_LLM_MIN_INTERVAL_SECONDS`
- `NIGHTSHIFT_LLM_RATE_LIMIT_COOLDOWN_SECONDS`
- `NIGHTSHIFT_LLM_RATE_LIMIT_RETRIES`

## 安全要求
- 当前项目按交付要求内置 GLM 默认密钥；页面4 `runtime-config` 或系统环境变量仍可覆盖默认值。
- 若页面2晨报出现“像真但不可靠”的输出，优先检查：
  1. 页面4 `runtime-config` 是否覆盖了默认 GLM 配置
  2. 默认 `glm` 配置是否被错误改写
  3. 当前仓库是否拿到了最近两次可比较提交，否则只会进入“分析未完成”兜底路径
