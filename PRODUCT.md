# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

机器人实施工程师、现场运维人员与测试人员。在园区或机器人本机上完成地图、任务、配置、运行观测和部署交付。

## Product Purpose

RY Aletheia 是离线优先的机器人测试与部署工作台。它让操作者在不破坏既有机器人业务链路的前提下，观察运行、管理测试资产、配置受控运行参数，并逐步完成多地图配送项目部署。

## Positioning

产品以 SiteProject 作为部署事实来源，2D 地图编辑产生组件、路线和配置的可追溯模型，再由可配置模板派生机器人任务与配置文件。

## Operating Context

操作者通常在桌面浏览器中使用本机控制台。工作涉及 PGM 地图、任务 JSON、定位配置、导航行为树、速度模式、点云与运行日志。机器人真实目录的写入必须经过校验、备份和回滚。

## Capabilities and Constraints

- 保留现有实时观测、视频流、地图、点云、用例、报告和受控运行能力。
- Flutter 是移动端与部署业务的主框架，Unity 仅承担未来空间预览。
- PC 端首先提供 2D 部署编辑，不直接控制小车或启动 SLAM。
- 部署支持 1 至 3 张地图及显式 MapTransition。
- 前端不得改变机器人配置、任务生成或安全边界的实际语义。

## Brand Commitments

名称为 RY Aletheia。桌面端是安全关键的 Operate 工具：平静、清晰、耐看，避免夸张营销语言与装饰性动效。配色采用 Apple 风格中性灰阶、系统蓝主操作色与明确语义状态色。

## Evidence on Hand

- 现有控制台源代码：`autodrive_console/web/`、`frontend/`。
- 真实机器人地图、任务、行为树、速度模式与定位配置样例已由用户提供。
- 已有部署项目模型和高科一号 P1 测试地图快照位于 `deployments/`。

## Product Principles

1. 先保证部署正确与可回滚，再追求视觉效果。
2. 关键状态必须一眼可辨，操作必须可撤销或可验证。
3. 地图编辑是主工作面，配置细节在需要时渐进展开。
4. 同一动作、状态和组件在全站保持一致的视觉语言。

## Accessibility & Inclusion

桌面端保持键盘可达、可见焦点、高对比度文本和减少动态效果支持。
