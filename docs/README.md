# NightShift 文档入口

更新日期：2026-03-20

`docs/` 只保留当前有效的执行契约、交付说明和工作流，不记录历史方案、临时调试笔记或已废弃实现。

## 当前结构

```text
docs/
├── README.md
├── SELECTED.md
├── NightShift-current-portrait.md
├── assets/
├── documents/
└── workflow/
```

仓库根目录下按需生成但不入库的运行时目录：

- `analysis_data/`
- `commit_data/`
- `reports/`
- `sqlite_data/`

## 当前基线

- 后端主工程位于 `backend/`。
- Android 主工程位于 `android-app/`。
- Tab3 源码位于 `backend/showcase_tab3/vibecodeing/code/`。
- Tab3 发布目录位于 `backend/static/showcase/atlas/`，访问入口为 `/showcase/atlas/`。
- Tab3 默认 token 使用后端环境变量 `TAB3_DEFAULT_GITHUB_TOKEN`，仅作为 Tab3 本地空值时的兜底。

## 建议阅读顺序

1. `SELECTED.md`
2. `NightShift-current-portrait.md`
3. `documents/03-交付文档/NightShift-PRD-技术方案.md`
4. `documents/01-页面规格/四标签页视觉规格.md`
5. `documents/03-交付文档/前端接口与数据类型交付清单.md`
6. `workflow/auto-dev-loop/README.md`

## 维护约束

- 文档描述必须与当前代码一致。
- 目录、接口或运行方式发生变化时，同步更新对应 README。
- 上游项目的原始方法论文档、临时产物和第三方依赖缓存不再放入主仓库。
