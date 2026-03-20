# NightShift Tab3 文档

更新日期：2026-03-20

`backend/showcase_tab3/docs/` 现在只保留 NightShift 需要的最小说明，不再同步上游 `GitVisual` 的方法论文档、画布模板和提示词资料。

## 当前结构

```text
backend/showcase_tab3/
├── docs/
│   └── README.md
└── vibecodeing/
    └── code/
```

## 关键路径

- 源码目录：`backend/showcase_tab3/vibecodeing/code/`
- 静态发布目录：`backend/static/showcase/atlas/`
- 运行入口：`/showcase/atlas/`

## 当前约束

- Tab3 必须继续输出为可由后端直接托管的静态资源。
- Android 端继续通过 WebView 访问 `/showcase/atlas/`，不单独维护第二套实现。
- Tab3 默认 token 与全局 token 解耦，只在本地未保存 token 时使用后端注入值。
- 若需补充文档，只记录 NightShift 当前实现，不回流上游项目的通用资料。
