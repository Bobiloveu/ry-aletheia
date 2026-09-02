# Web console rules

The Web source is frontend/. Its production output intentionally remains autodrive_console/web-vue/ until Phase 2 migration.

- Keep Vite output compatible with the backend static-resource lookup.
- Browser code consumes controlled HTTP, WebSocket, and WHEP/WebRTC interfaces only; never directly controls ROS or robot files.
- Preserve latest-wins realtime behavior and per-stream video lifecycle.
- Update shared/contracts before changing a Web-consumed cross-client interface.
- Validate with pixi run frontend-check. Do not commit frontend/node_modules or built web-vue output.

