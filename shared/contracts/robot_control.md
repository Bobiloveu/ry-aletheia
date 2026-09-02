# Robot control

**Status: Existing**
**Authoritative implementations:** autodrive_console/vehicle_control.py and web_console.py
**Consumers:** robot_backend, web_console, mobile
**Compatibility:** Additive changes first; breaking changes require all consumers and this document to change together.

## ROS ownership

| Topic | Direction | Meaning |
| --- | --- | --- |
| /control_source_cmd | Aletheia → robot | Requests a permitted control-source transition. |
| /control_source_state | robot → Aletheia | Actual source state; clients must not infer it from a button press. |
| /cmd_vel_miniapp | Aletheia → robot | Velocity command only while the controlled session is valid. |

Only the robot backend publishes or subscribes to these topics. Web and Mobile use the controlled HTTP lifecycle; they never speak ROS directly.

## HTTP lifecycle

Existing endpoints are GET /api/vehicle-control plus POST /api/vehicle-control/enter, /heartbeat, /command, /speed, /stop, and /exit. Enter grants the time-bounded controlled session; heartbeat retains it; stop is explicit and must be sent before exit. A run in progress or another control owner is a conflict, not an invitation for a client-side retry loop.

## Planned

No new direct mobile operation protocol is approved. Future command UI needs a separate contract, permission model, audit trail, and explicit confirmation flow.
