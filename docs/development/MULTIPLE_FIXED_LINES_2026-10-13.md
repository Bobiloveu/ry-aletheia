# 多任务目标独立线路与完整导出

规则：多任务模式下，用户楼层每新增一个目标点，对应一条独立线路和一对 `floor` 去返任务；保留已有线路，不能把新目标追加为旧线路的一个停靠点。

## 最终行为

- 保存组件、门牌、地图属性或线路后保持当前编辑步骤；只有人员明确点击“结束修改并返回”才结束编辑。保存线路也不会自动进入导出。
- 画布、位置下拉框、流程卡片和预览显示真实门牌号；未填门牌的同名目标使用可读编号。自定义名称包含多个门牌时仍显示独立的真实门牌字段。
- 新楼层目标复制已有同图配送模板，只替换最终目标，保持原线路和活动选择。没有可用模板时先由人员配置首条，首次保存后补齐该图其他目标。门牌保存后更新自动名称，人员自定义名称不被覆盖。
- 旧 multi 项目一次性补齐已有门牌而缺少线路的目标，并记录内部迁移版本。后续读取、普通线路保存和目标属性编辑不恢复人员已明确删除的线路。
- single 仍导出选中线路；multi 汇总全部已保存线路，公共段语义一致才复用，各户 `floor/*[ _r ].json` 分别输出。所有 JSON 保持既有直接子任务格式；XML 引用和清单哈希同步一致。
- 最终实验预览默认显示全部线路，支持选择单条线路以及去/返程。节点、地图归属、动作均来自真实编译结果，独立线路之间不产生连接；配置画布可查看当前编辑线路的完整编译节点。
- 多户共享终末 floor 的定位 `init_return` 沿用既有多任务代表路线语义，取稳定最小线路 ID 的记录；每户独立返程完整保留。其他定位字段和公共前图的锚点仍严格一致。全部线路的模板哈希共同记录。

## 验证

- `env -u PYTHONPATH ./scripts/test-web.sh`：700 项测试通过，生产构建通过。
- 实现过程中完整 `scripts/test-backend.sh`：1327 项通过；后续边界修正及测试隔离完成后通过同脚本选取受影响模块：147 项通过、1185 项未选取。最终定向命令见下。
- 新 Backend 回归 10 项：多户真实文件结构、原项目不变、公共动作冲突、失效非活动线路、自动独立线路、门牌重命名、single 隔离、不同设施返程、三户代表记录全部排列、后续模板来源、Store 一次迁移/模式切换响应/删除保持/放置与保存不重复生成。
- Web 新回归 10 项：各步骤保存保留编辑、门牌/极端名称区分、空新草稿不丢失、逐线路归属与动作、实际子任务范围切片及不跨线路连接。
- 独立 Backend 与 Web 审查；最终结果见 `/tmp/ry-multiline-backend-review.md` 与 `/tmp/ry-multiple-lines-web-review.md`。
- 浏览器在 18933 独立端口使用项目副本：原有两户线路可切换，放置第三目标后即时增加第三线路，放置及属性保存留在 annotations，拖动与线路保存留在 localization。1508 单独改为下仓开仓；三线路预览共 33 个去程、21 个返程节点，单条为 11+7，全部能识别 1507/1508/1509。
- 最终源码生成 ZIP 验证：三条线路、六个 floor 文件、两个摆渡层公共文件、无伪造 indoor 目录；31 个产物哈希及全部 XML 引用有效，各户仓控独立。1600 与 1100 宽度预览无横向溢出。
- 设计检测工具因缺少可选解析器退化为正则检查；唯一提示为原有隐藏的动态 PCD 图片缺少初始 src，未将其视为本次新增缺陷。完成浏览器截图检查。

```bash
env -u PYTHONPATH PYTEST_ADDOPTS='-k "deployment_test_workspace or fixed_multiple_lines or fixed_task_compiler or fixed_compiler_consistency or fixed_multi_export or task_lines or task_preview_cache or deployment_project_settings"' ./scripts/test-backend.sh
```

证据在 `/tmp/ry-multiple-lines-qa/`：`browser-proof.json`、`zip-proof.json`、`three-lines-experimental.zip` 和两种宽度截图；检查日志为 `/tmp/ry-multiple-lines-final-web.log`、`/tmp/ry-multiple-lines-full-backend.log`、`/tmp/ry-multiple-lines-final-backend-script.log`。

本次涉及 Backend 与 PC Web，已同步 `shared/contracts/deployment.md`。Mobile 不是消费者；没有改变 ROS、任务下发、既有机器人文件读取格式或设备控制安全边界。没有重启现场服务、下发任务或重新构建安装包。

## 测试启动隔离纠正

核对发现，测试收集时导入 `web_console` 会构造默认 `MapProjectionJobs`，启动扫描默认部署目录，从而触发本次新增的旧项目补齐迁移。现场项目原有 1508 目标因此新增对应线路和 policy 版本；原线路及地图未改动，未回滚这条符合需求的线路。没有进程级审计，不能唯一归因到主任务或审查进程；不声称整个检查期间现场所有文件完全不变。

新增 pytest 启动隔离，仅将默认工作目录的 DeploymentStore 构造重定向私有临时目录，先于 HTTP 测试模块收集；显式临时 fixture Store 仍正常工作。独立服务导入验证确认默认 Store 与投影 Store 均采用私有根，现场 22 个源文件在隔离导入前后校验值完全一致。相关回归包含在最终 147 项检查内，证据为 `import-isolation-proof.json`。
