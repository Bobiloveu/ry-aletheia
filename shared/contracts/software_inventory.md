# 车辆软件资产

**Status: Existing**

## 目的与边界

Desktop Web 通过本契约读取当前小车已安装的 ry-* Debian 软件包版本，并保存车辆档案和软件说明，供现场故障单进行版本比对。

- **执行方：** 机器人 Backend 的 SoftwareInventory。
- **Existing 消费者：** Desktop Web software-inventory.html。
- **非消费者：** Mobile；它不调用、缓存或展示本接口。
- Backend 固定调用本机 dpkg-query 读取包数据库；接口不会安装、卸载、升级软件包，不会操作 ROS、Supervisor、定位、导航、底盘或安全配置。
- 包名、版本、架构、安装状态均为只读事实。车辆资料、维护人和说明仅存于本机 config/console.json 的 software_inventory。

## GET /api/software-inventory

响应禁止缓存。成功读取包数据库时返回：

~~~json
{
  "inventory_status": "available",
  "message": "",
  "discovered_at": "2026-10-09T10:00:00+00:00",
  "vehicle": {
    "vehicle_number": "01号车",
    "vin": "RY-CHASSIS-001",
    "model": "RY 标准小车",
    "project": "园区配送",
    "location": "A 栋一层"
  },
  "packages": [
    {
      "package_name": "ry-runtime",
      "version": "1.2.3",
      "architecture": "amd64",
      "installed": true,
      "package_filename": "ry-runtime_1.2.3_amd64.deb",
      "maintainer": "甘怡训",
      "description": "ry 固件底层依赖"
    }
  ]
}
~~~

当包数据库暂不可读时，仍返回 HTTP 200 与 inventory_status: unavailable、已保存的 vehicle、空 packages 和用户安全的 message。响应不得包含命令行、绝对路径、stderr 或 dpkg 原文。

package_filename 是由 package_name、version 与 architecture 组成的标准化展示名；dpkg 不保存操作者下载时使用的原始文件名。

## POST /api/software-inventory

请求体：

~~~json
{
  "vehicle": {
    "vehicle_number": "01号车",
    "vin": "RY-CHASSIS-001",
    "model": "RY 标准小车",
    "project": "园区配送",
    "location": "A 栋一层"
  },
  "package_notes": {
    "ry-runtime": {
      "maintainer": "甘怡训",
      "description": "ry 固件底层依赖"
    }
  }
}
~~~

五个车辆字段均为必填字符串，拒绝控制字符；车架号只允许字母、数字、连字符和下划线。package_notes 的键只能是本次即时发现的已安装 ry-* 包。成功时返回更新后的 available 快照。

- 无效 JSON、缺失或无效车辆字段、未知包说明：HTTP 400，返回用户可操作的中文错误。
- 包数据库不可读取时禁止保存：HTTP 503，防止旧页面覆盖本地说明。
- Backend 使用 SettingsStore 的受控持久化路径保存；包事实本身不会写入配置。

## 兼容性与验证

这是新增 Desktop 专用接口，不改变现有接口。Backend 验证 tests/test_software_inventory.py 与 tests/test_software_inventory_http.py；Desktop 静态验证 frontend/test/legacy-app-module.test.mjs。Mobile 无需工具链验证。
