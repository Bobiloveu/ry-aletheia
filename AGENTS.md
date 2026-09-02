# RY Aletheia collaboration rules

## Start here

1. Read README.md, the relevant module README, and any Existing contract in shared/contracts/.
2. Read PROJECT_OVERVIEW.md for robot/runtime facts and inspect git status before editing.
3. Read the module AGENTS.md before changing backend, Web, or Mobile.

## Boundaries

- Do not perform a large physical directory migration, rewrite business logic, delete data, or change robot safety boundaries without explicit approval.
- Current real modules remain: robot backend at web_console.py plus autodrive_console/; Web source at frontend/; Flutter at mobile/; Unity at unity/ and is paused.
- A cross-client API, ROS Topic, WebSocket wire format, or shared data-model change must update shared/contracts/ and verify each consumer.
- When asked to change only one module, change only that module and required contract/script documentation. State any cross-domain impact.
- Do not duplicate existing capabilities or bypass backend-controlled ROS, video, task, or deployment boundaries.
- Do not commit build output, caches, logs, signing material, maps, field data, or another developer's Golden failure images.

## Verification

Run the smallest relevant check before completion: scripts/test-backend.sh, scripts/test-web.sh, or scripts/test-mobile.sh. Run scripts/doctor.sh when environment behavior is relevant. Flutter CustomPaint is the released mobile renderer; do not restore Unity by default.
