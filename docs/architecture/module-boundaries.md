# 模块边界

| 逻辑模块 | 实际位置 | 主要入口 |
| --- | --- | --- |
| robot_backend | `web_console.py`、`autodrive_console/`、`live_preprocessor/` | `web_console.py` |
| web_console | `frontend/` | `npm run dev`；Vite 输出由 Backend 提供 |
| mobile | `mobile/` | `lib/main.dart` |
| unity（暂停） | `unity/` 与 `mobile/packages/aletheia_visualization/` | 无默认入口 |

契约位于 [`shared/contracts/`](../../shared/contracts/)。当前是逻辑 Monorepo 边界，源码尚未迁移。
