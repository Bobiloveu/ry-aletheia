# Realtime observation

**Status: Existing**
**Authoritative implementations:** autodrive_console/telemetry.py, autodrive_console/observation.py, frontend/src/liveObservation.js, and mobile/lib/features/live_observation/
**Consumers:** robot_backend, web_console, mobile
**Compatibility:** Additive changes first; breaking changes require all consumers and this document to change together.

## Control-plane API

GET /api/observation, GET /api/observation/active-map, and GET /api/observation/maps/{id}/layers expose the active map, world metadata, virtual walls, and telemetry. The existing session lifecycle is POST /api/observation/start, /heartbeat, and /stop.

## Realtime transport

The robot-side preprocessor sends locally ingested UDP frames with RALT. The gateway exposes binary WebSocket lanes on port **8768**:

| Lane | Path | Ingress port | Record payload |
| --- | --- | --- | --- |
| cloud | /cloud | 8769 | XY float pairs, maximum 3000 points |
| pose | /pose | 8770 | one X/Y/yaw float record |

Browser and Mobile payloads begin with **ALTM v1**. Consumers validate magic, version, lane type, record count, declared payload length, and finite numeric values before rendering.

## Freshness and rendering

All stages are latest-wins: one pending frame per source, no retransmission, and stale frames are discarded rather than replayed. Map image, grid, virtual walls, cloud, pose, and vehicle indicator share one world-to-screen transform. The map stays north/original-map oriented; only the vehicle rotates.

## Planned

No generic telemetry bus is approved. New realtime data requires a separately versioned lane and explicit bounded-memory/freshness behavior.
