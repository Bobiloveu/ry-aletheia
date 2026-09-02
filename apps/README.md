# Apps 物理迁移状态

本仓库第一阶段采用逻辑 Monorepo：这里不复制、链接或承载业务源码。

当前模块的实际位置如下：

- `robot_backend`：根 `web_console.py`、`autodrive_console/`、`live_preprocessor/`，以及相关的 `config/`、`tasks/`、`packaging/` 和根发布脚本；
- `web_console`：`frontend/`，构建产物仍由后端从 `autodrive_console/web-vue/` 提供；
- `mobile`：`mobile/`；
- `unity`（暂停 PoC）：`unity/` 与 `mobile/packages/aletheia_visualization/`。

只有满足 [`docs/architecture/monorepo-migration.md`](../docs/architecture/monorepo-migration.md)
规定的路径解耦和回归验证条件后，才可以将源码迁至 `apps/robot_backend`、
`apps/web_console` 和 `apps/mobile`。在此之前，请从仓库根 README 进入实际模块。
