# 多端开发环境

本目录是开发角色、操作系统限制和统一命令的入口。它不替代各模块的源码说明：

- [开发 Profile 与命令矩阵](PROFILES.md)
- [根脚本说明](../../scripts/README.md)
- [Backend 文档](../backend/README.md)
- [Web 文档](../web/README.md)
- [Mobile 文档](../mobile/README.md)
- [共享契约](../../shared/contracts/README.md)

原则是“按职责安装”。缺少未选择模块的工具不应阻断当前工作；任何跨端接口改动则必须先更新共享契约，再验证受影响消费者。
