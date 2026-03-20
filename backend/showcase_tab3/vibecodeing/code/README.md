# NightShift Tab3 Source

更新日期：2026-03-20

这里是 NightShift Tab3 的可维护源码。它由集成后的 `GitVisual` 前端裁剪而来，专门服务于 `/showcase/atlas/` 这条运行链路。

## 运行前提

- Node.js 20+
- npm

## 目录职责

- `src/`
  - Tab3 前端源码
- `.env.example`
  - 通用环境变量示例
- `.env.tab3`
  - NightShift Tab3 构建模式默认值
- `vite.config.ts`
  - 构建入口和输出目录配置

## 常用命令

- `npm install`
- `npm run dev`
- `npm run lint`
- `npm run build`
- `npm run build:tab3`

其中：

- `npm run dev` 用于本地独立调试
- `npm run build` 默认输出到当前目录下 `dist/`
- `npm run build:tab3` 输出到 `backend/static/showcase/atlas/`

## 环境变量

本地独立开发时可自行创建 `.env.local`，常用变量见 `.env.example`。

Tab3 嵌入模式默认使用 `.env.tab3`：

- `SHOWCASE_PUBLIC_BASE="/showcase/atlas/"`
- `SHOWCASE_OUT_DIR="../../../static/showcase/atlas"`
- `TAB3_EMBEDDED="true"`
- `TAB3_DISABLE_LOCAL_PROJECT="true"`

默认 GitHub token 不再写死在前端构建文件中。NightShift 后端会在 `/showcase/atlas/` 响应里注入 `TAB3_DEFAULT_GITHUB_TOKEN`，并且只有在 Tab3 本地没有保存 `githubToken` 时才会作为兜底值使用。

## 维护约束

- 不提交 `node_modules/`、`dist/`、`coverage/` 等产物。
- 不再保留上游项目的独立文档、测试缓存或本地环境文件副本。
- 嵌入式 Tab3 默认禁用本地目录分析入口，修改时要确认不影响 Android WebView 场景。
