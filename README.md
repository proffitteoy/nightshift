# NightShift

更新日期：2026-03-20

NightShift 由后端服务、Android 客户端和一套嵌入式 Tab3 前端组成。Tab3 继续通过 WebView 加载 `/showcase/atlas/`，源码已经并入主仓库，不再依赖根目录外部项目。

## 目录

```text
NightShift/
├── backend/                        # 后端服务与 Tab3 静态发布目录
│   ├── showcase_tab3/vibecodeing/code/
│   └── static/showcase/atlas/
├── android-app/                    # Android 客户端
├── docs/                           # 当前有效的项目文档
├── .gitignore
└── README.md
```

## 当前基线

- 后端保持 `api -> services -> repositories -> clients -> models -> prompts` 分层。
- Android 保持 `MainActivity + Fragment + Navigation` 架构。
- Tab1 到 Tab3 允许匿名使用，Tab4 承担登录、账号、订阅和运行时配置。
- Tab3 运行入口固定为 `/showcase/atlas/`，对应静态文件目录为 `backend/static/showcase/atlas/`。
- Tab3 默认 GitHub token 由后端环境变量 `TAB3_DEFAULT_GITHUB_TOKEN` 注入，只在 Tab3 本地未写入 token 时生效，且与全局 token 分离。

## Tab3 开发

源码目录：`backend/showcase_tab3/vibecodeing/code/`

常用命令：

- `npm install`
- `npm run lint`
- `npm run build:tab3`

`npm run build:tab3` 会把产物写入 `backend/static/showcase/atlas/`，供后端和 Android WebView 直接加载。

## 常用校验

- 后端语法检查：`python -m compileall backend`
- Android Debug 构建：`cd android-app && .\gradlew.bat :app:assembleDebug`
- Android lint：`cd android-app && .\gradlew.bat :app:lintDebug`
- Tab3 类型检查：`cd backend/showcase_tab3/vibecodeing/code && npm run lint`

## 文档入口

- `docs/README.md`：项目文档索引
- `backend/static/showcase/README.md`：Tab3 静态发布目录说明
- `backend/showcase_tab3/docs/README.md`：Tab3 集成说明
- `backend/showcase_tab3/vibecodeing/code/README.md`：Tab3 源码开发说明
