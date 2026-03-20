# Tab3 静态发布目录

更新日期：2026-03-20

`backend/static/showcase/` 只承载 NightShift Tab3 的静态发布资源。

## 路由入口

- `/showcase/`
  - 轻量跳转入口，访问后跳转到 `/showcase/atlas/`
- `/showcase/atlas/`
  - Tab3 实际运行入口

## 目录说明

- `index.html`
  - `/showcase/` 跳转页
- `atlas/index.html`
  - Tab3 入口页
- `atlas/assets/*`
  - Vite 构建产物

## 源码位置

Tab3 源码位于 `backend/showcase_tab3/vibecodeing/code/`。

常用构建命令：

1. `cd backend/showcase_tab3/vibecodeing/code`
2. `npm install`
3. `npm run lint`
4. `npm run build:tab3`

`npm run build:tab3` 会直接覆盖 `backend/static/showcase/atlas/` 下的发布文件。

## 维护约束

- 不手改 `atlas/assets/*` 构建产物。
- 需要调整 Tab3 页面时，修改源码后重新执行 `npm run build:tab3`。
- Tab3 运行时默认 token 由后端在返回 `/showcase/atlas/` 时注入，不在本目录保存敏感配置。
