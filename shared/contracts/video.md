# Video

**Status: Existing**
**Authoritative implementations:** autodrive_console/video.py, web_console.py, frontend/src/liveObservation.js, and mobile/lib/features/live_observation/
**Consumers:** robot_backend, web_console, mobile
**Compatibility:** Additive changes first; breaking changes require all consumers and this document to change together.

GET /api/video/status returns configured streams and runtime health. POST /api/video/control is the only client control entry for global or per-stream enabled state. Clients use returned configured stream names, not constructed camera endpoints.

Actual pixels travel through receive-only WHEP/WebRTC sessions from the media gateway to browser or Mobile. Python manages configuration, process lifecycle, and health only; it does not relay video frames. Leaving a video workspace, switching stream, app backgrounding, or disposing a view releases its session, peer connection, media stream, and renderer.

## Planned

Additional cameras or codecs require a configuration and lifecycle-compatible extension. No client may directly open ROS image topics.

