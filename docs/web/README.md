# Web Console 文档

Vue/Vite 源码位于 [frontend](../../frontend/)。其生产输出有意由 `autodrive_console/web-vue` 提供。阅读 [Web 规则](../../frontend/AGENTS.md)、[共享契约](../../shared/contracts/README.md)，并运行 `scripts/test-web.sh`。

Desktop 侧栏由 `autodrive_console/web/app_shell.js` 统一生成，图标几何仅维护在其中的
`NAVIGATION_ICONS`，避免各页面混用字符和图标字体。11 枚原创 SVG 使用 24×24 网格、
1.7 线宽及圆角端点，通过 `app_shell.css` 以 20px 显示并继承深浅主题及选中颜色。
图标随现有网页资源离线交付，无额外请求；名称、分组和原生链接导航保持现有规则。
此项只影响 Web 展示，不改变 Backend API、ROS、Mobile 或共享契约。
