# 手动控制与定位恢复修复顺序

依据：2026-10-16 的十项审查，用户已要求按顺序修复。保持当前脏工作树，不打包/部署/提交；不得改变350ms看门狗、1.2秒心跳或急停许可。Backend/Web共享行为先记录契约影响，Mobile旧请求兼容，不引入无关平台工具链。每项先见失败用例，再实现与定向回归；完成后再检查跨模块与只读独立评审。

- [x] 1. STOP发布顺序：实际publish出口在同一锁域复查非零目标/许可，废弃已过时tick；用暂停线程观察STOP后的真实publisher输出。
- [x] 2. 旧状态响应：Web统一响应代际管理，旧GET/heartbeat不能清除新输入；模拟响应乱序。
- [x] 3. 请求积压：latest-wins受限在途、有限请求期限；新STOP立即优先，旧运动不重放；悬置HTTP验证请求上限与停止。
- [x] 4. 退休future：身份和generation匹配才消费，超时仅计一次；保留真正的失败锁定。
- [x] 5. 失效会话：有本会话失效证据才释放本地ID，聚合GET缺少ID不算失效；验证重入。
- [x] 6. 离页释放：使用既有release，保持显式exit全局语义，离页幂等；双会话验证。
- [x] 7. 位姿进程恢复：启用、有活跃观测及心跳时缺失lane有界退避恢复；正常lane不重启，stop/禁用不复活。
- [x] 8. TF候选恢复：区分低频地图边与停止的车体边，选新鲜备用frame；不无限重打旧TF新戳，也不因合成stamp低频切断有效流。
- [x] 9. 地图内容身份：有界栅格摘要纳入去重签名；同元数据不同栅格必须更新，相同内容不重写。
- [x] 10. 地图线程生命周期：停止超时保留旧worker引用/停止令牌，不能清stop启动重叠worker；旧回调禁止写入新状态。

相关验证入口：scripts/test-backend.sh（按受影响测试筛选）、scripts/test-web.sh、C++/ROS独立编译与定向CTest、doctor backend/web、git diff --check。全部本地假发布器/合成TF/HTTP，不发送真实小车控制。

十项均完成失败复现、修复和定向回归。独立复核补齐了当前运动错误不能被展示代际吞掉、明确失效会话处理、未知急停下有序停止、旧零向量不能覆盖新运动，以及安全锁定/心跳失败后的在途运动停止屏障。连续未知状态或 STOP 失败不会无限重发。

TF 补充回归覆盖未来 100ms 容差、明显未来数据拒绝、过期间接链让位新鲜直接链、静态车体边不刷新旧动态地图，以及全静态链兼容。急停查询同时覆盖退休回调、查询期间到达新 Topic、旧查询到期前已有新 Topic 三种时序；旧请求不得计错到新代。

本地验证记录：

- `scripts/test-backend.sh` 按上述受影响表达式筛选：267 passed，1463 deselected；3 条既有 TestCase 收集警告。
- 最后补充急停时序后，`tests/test_vehicle_control.py`、`tests/test_map_marker_navigation.py`、`tests/test_manual_relocalization.py`：163 passed。
- `scripts/test-web.sh`：885 passed，parity 与 Vite 构建通过；已有主题脚本/大 chunk 构建提示保留。
- `pixi run test-offline`：109 passed；1 条既有 TestCase 收集警告。
- 原生位姿节点与测试编译通过；CTest：3/3 passed，包含真实内存 BufferCore 的位姿选择回归。
- Backend/Web doctor 和 `git diff --check` 通过。两个只读独立复核均未发现剩余阻塞问题。

仅验证本地源码与合成故障；未连接实车、未发送真实运动，未打包、部署、提交或推送。实车表现仍需后续按现场版本验证。
