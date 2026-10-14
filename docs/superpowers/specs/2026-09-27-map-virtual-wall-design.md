# 地图虚拟墙编辑与导出设计

## 目标

在既有部署建图工作台中增加可视、可编辑的虚拟墙标记能力。实施人员在地图上用两个点定义一段不可穿越墙体；系统将其安全地保存为项目地图事实，并自动生成与地图 YAML 同目录、文件名固定为 `map_walls.yaml` 的运行时兼容文件。

本功能不改变部署向导、左侧导航、地图阶段或自动路线排序。虚拟墙是通行约束，不是任务执行节点，也不参与行为树节点排序。

## 现有文件兼容性

运行时文件固定名为 `map_walls.yaml`，根节点为 `virtual_walls`。生成文件采用如下稳定形状：

```yaml
virtual_walls:
  coordinate_mode: image_relative
  frame_id: map
  map_origin:
  - <map origin x>
  - <map origin y>
  - <map origin yaw>
  thickness: 0.1
  segments:
  - start:
    - <x - map origin x>
    - <y - map origin y>
    - 0.0
    end:
    - <x - map origin x>
    - <y - map origin y>
    - 0.0
    thickness: 0.1
```

项目内部始终以世界坐标保存端点；仅写 YAML 时转换为 `image_relative`。这与既有 PC、Mobile 和报告渲染器一致，避免地图原点为负数时坐标含义不一致。`map_origin` 来自对应 `map.yaml` 的 `origin`。

导入地图时，如果同目录已有可识别的 `map_walls.yaml`，后端把每个已有 `segments` 线段转换为项目拥有的两点墙段。旧项目残留的多点 `forbidden_zone` 兼容地转换为连续并闭合的线段，不丢弃已保存的边界。无法识别的外部墙文件不会被猜测或改写；用户可通过新的绘制工具重新标记。

## 数据与 API

每段墙是一条独立记录：

```json
{
  "id": "virtual-wall-…",
  "map_asset_id": "map-…",
  "start": {"x": 1.2, "y": 3.4},
  "end": {"x": 2.8, "y": 3.4}
}
```

端点必须是有限数值、在所关联地图边界内，且端点间距离大于零。创建、更新或删除后后端原子写入项目快照 `maps/<map-id>/map_walls.yaml`，更新资产文件元数据与哈希，并使实验任务预览失效。绝不改写 `/opt/ry/data/maps` 的外部原始地图，也不写入机器人运行目录。

受控 API 仅接受当前项目、当前地图的单段墙：

- `POST /api/deployments/{project_id}/virtual-walls` 创建 `{map_id, start, end}`；
- `POST /api/deployments/{project_id}/virtual-walls/{wall_id}` 替换该段端点；
- `DELETE /api/deployments/{project_id}/virtual-walls/{wall_id}` 删除该段。

所有响应返回权威项目快照。客户端不直接写 YAML。

## 画布交互与视觉

在现有地图工具栏增加“虚拟墙”按钮，保留原有布局与样式。选中后：

1. 第一次左键落下起点；移动鼠标显示临时红线。
2. 第二次左键落下终点，立即调用创建接口并保留工具，可连续绘制多段墙。
3. `Esc` 只取消尚未完成的临时线段；平移、缩放和原有组件编辑保持现状。

所有已保存墙显示为高对比红色实线，不带箭头或方向语义。命中一段墙时显示两个小型红色端点控制柄：拖动控制柄只移动对应端点；拖动线体平移整段墙。松开鼠标后提交一次更新。右键或键盘删除通过同一受控删除接口移除选中的墙段。删除不会删除地图或修改路线人工顺序；现有预览只会失效，下一次生成重新读取地图文件。

## 导出与运行边界

定位清单导出把每个地图快照的 `map_walls.yaml` 与 `map.yaml`、PGM、索引和受控 PCD 一并放入相同的运行时地图目录。实验预览与 ZIP 因此包含同路径墙文件，但仍不安装、不下发、不触碰 ROS 或机器人运行目录。

## 错误处理与验证

- 地图不存在、跨图墙段、越界端点、非有限坐标和零长度线段均由后端拒绝。
- 写入失败时保持旧的文件与项目快照；不得出现只更新 JSON 或只更新 YAML 的状态。
- 浏览器网络失败时回读权威项目快照，不保留伪造的本地墙段。
- Backend 测试覆盖：文件结构/坐标转换、导入迁移、CRUD、原子失败、导出 ZIP 同目录文件及非法输入。
- Web 测试覆盖：两次点击创建、临时红线、端点拖动、线体平移、删除、取消和既有组件交互不回归。
- 最终运行受影响的 Backend 与 Web 完整检查。
