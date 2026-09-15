# 部署建图定位清单与电梯物理楼层设计

**状态：** 已确认设计，尚未实施  
**范围：** PC 部署建图项目、实验部署包与现有室内电梯任务编译器；Mobile 不消费本功能。

## 目标

部署人员在项目地图中标注地图定位用途、初始化位和电梯按钮范围。控制台仅从项目快照生成受控部署包，自动产出：

- 机器人定位清单 `loc_yaml_path.json`；
- 每张已绑定地图的定位 YAML 与 2D 地图快照；
- 现有 `elevator_out_n_x.xml` 所需的 `origin_floor`；
- 带输入指纹、安装布局和文件校验的只读预览。

这不是浏览器编辑机器人文件的能力：页面不能输入、浏览、读取或写入机器人绝对路径，且不会调用 ROS、Supervisor、定位进程或任务下发。

## 业务事实

### 电梯物理楼层

电梯组件的 `min_button_floor` 与 `max_button_floor` 是电梯面板上的最低和最高按钮数字。按钮 `0` 永远不属于物理层序列。对任意电梯，后端构造：

```text
button_sequence = [min_button_floor .. max_button_floor]，去除 0
physical_floor(button) = button_sequence 的零基下标
```

例如 `min_button_floor=-2`、`max_button_floor=25` 时，序列为 `-2, -1, 1, 2, …, 25`，因此 `-2 → 0`、`-1 → 1`、`1 → 2`。起源地图上的电梯落点必须记录其面板按钮层 `button_floor`；编译器以该落点关联的物理电梯计算 `origin_floor`，并填入 `elevator_out_n_x.xml` 的 `SetBlackboard(output_key="origin_floor")`。

范围不连续、按钮层不在范围内、按钮层为 `0` 或起源图存在多个无法唯一确定的电梯落点，均必须阻断预览；不得回退到“地图楼层 + 1”。

### 定位清单

`loc_yaml_path.json` 的顶级 `community` 来自任务编译器已保存的小区名。每个 `{building, unit}` 形成一个 `loc_yaml` 条目；每个条目的 `yaml_index` 项只允许：

- `outdoor`：户外地图；
- `indoor`：室内大厅/电梯所在地图；
- `ferry`：可选摆渡层地图；
- `floor`：用户楼层地图，必须带 `floor` 布局模板编号。

`floor` 的 `floor` 字段是布局模板编号，不是电梯按钮楼层、项目楼层或任务目标层。同一布局模板可以服务多个实际用户楼层。每个条目都包含 `yaml`、`2D_yaml`、`init_go`、`init_return`；每个初始化位是 `{x, y, z, yaw}`。

同一楼栋单元最多一个 `outdoor`、`indoor`、`ferry`；`floor` 按布局模板编号唯一。多个楼栋单元可以安全引用同一项目地图资产，但导出时各自拥有独立的定位索引条目。

## 项目模型

保留现有 `map_instances` 的阶段/拓扑职责，不将定位语义塞入旧的 `role` 或三阶段模型。项目新增独立的 `localization_bindings`：

```json
{
  "id": "localization-…",
  "map_asset_id": "map-…",
  "building": "1",
  "unit": "1",
  "type": "floor",
  "floor_template": "2",
  "init_go": { "x": 0, "y": 0, "z": 0, "yaw": 0 },
  "init_return": { "x": 0, "y": 0, "z": 0, "yaw": 0 }
}
```

`floor_template` 只允许 `type="floor"`，其余类型必须为 `null`/缺省。`x/y` 受所属地图边界约束，`z/yaw` 必须为有限数。`init_return` 与 `init_go` 是两个显式字段：界面可提供“复制去程位置”的便利操作，但导出不隐式复制或猜测。

现有 `physical_elevators` 保留作为共享电梯事实，并继续使用兼容字段 `min_floor`、`max_floor` 表示面板按钮范围；不改名、不破坏现有项目或 API。每个地图电梯组件新增 `attributes.button_floor`，表示该电梯落点对应的面板按钮层。它必须位于关联物理电梯的非零按钮序列内。

## 导出布局与路径

部署包拥有唯一、受控的逻辑安装布局；浏览器不选择路径：

```text
runtime/
  loc_yaml_path.json
  localization/<community>/<building>_<unit>/<type-or-template>.yaml
  maps/<community>/<building>_<unit>/<type-or-template>/map.yaml
  maps/<community>/<building>_<unit>/<type-or-template>/…地图同目录快照文件
manifest.json
```

导出的 `yaml` 和 `2D_yaml` 使用安装器定义的固定白名单根目录加上述相对路径。编译器从包的运行时布局函数一次性生成两种最终路径，不能沿用上传临时目录、项目工作区绝对路径或浏览器输入。`manifest.json` 必须列出每个文件相对路径、SHA-256、输入指纹、目标安装根和 `robot_runtime_changed: false`。

定位 YAML 使用现有受控 `localization_base.yaml` 模板，仅替换模板中唯一批准的 `system.map_path`。地图资产从项目快照复制进入包；缺少 `map.yaml`、关联 PGM 或解析后的地图元数据时阻断导出。

## 编译与兼容

现有 `indoor_elevator_v1` 继续只生成其已批准的室内两图任务，绝不凭空生成户外、摆渡或多模板楼层路线。该 profile 改为从 `localization_bindings` 获取大厅和目标布局所需的定位输出，使用起源大厅电梯落点的 `button_floor` 渲染 `origin_floor`；目标层相关的电梯门命令也使用同一按钮序列换算，不能继续使用“目标地图楼层 + 1”。

`outdoor`、`ferry` 和额外 `floor` 模板会进入定位部署包与清单；它们的导航/行为树任务必须等待相应业务模板和任务协议明确后才新增。这样不会把“能导出定位清单”误报为“已支持跨所有地图自动执行”。

旧项目没有 `localization_bindings` 时保持可读且保留旧实验预览；请求新定位部署预览时明确提示补充绑定，不以旧地图阶段或地图名称猜测类型。所有新 API 均由 Backend 验证，Web 只提交受限结构；Mobile 不变。

## 界面

在既有部署地图详情中增加“定位绑定”编辑区，而不是新建第二套地图工作台。部署人员选择当前项目地图后：

1. 选择绑定类型与楼栋/单元；选择 `floor` 时才显示布局模板编号；
2. 在地图画布上分别设置去程、返程初始化位，界面展示坐标并允许复制；
3. 标记电梯时编辑其共享按钮范围及该落点的 `button_floor`，实时展示推导出的物理层号；
4. 在任务编译预览区域展示清单条目、自动路径和阻断原因，下载仍是实验部署包。

不展示或接受机器人绝对路径，不新增 ROS 控制按钮，不改变已有地图导入、建图、组件、Transition、路线或虚拟墙功能。

## 验证

1. 纯函数测试：按钮序列、跳过 `0`、负层/正层换算、边界与非法范围。
2. Store/API 测试：定位绑定唯一性、初始化位地图边界、物理电梯迁移、落点按钮层校验、未知字段拒绝。
3. 编译器测试：多栋单元清单聚合、`floor` 模板不被误作目标楼层、受控输出路径、地图资产复制、`origin_floor` XML 渲染，以及缺失/歧义事实的阻断。
4. Web 单元与页面结构测试：类型切换、仅 `floor` 显示模板字段、初始化位编辑和错误文案；现有部署画布/组件路由不回归。
5. 更新 `shared/contracts/deployment.md` 的消费者、数据格式与实验导出边界；运行 `scripts/test-backend.sh`、`scripts/test-web.sh`、`git diff --check`。环境变更再运行 `scripts/doctor.sh --profile backend` 与 `--profile web`。
