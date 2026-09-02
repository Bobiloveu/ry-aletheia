# Robot backend rules

The backend boundary includes web_console.py, autodrive_console/, live_preprocessor/, config/, tasks/, packaging/, and root release scripts.

- Preserve controlled ROS2 ownership. Browser and Mobile call HTTP APIs; they never access ROS topics directly.
- Preserve workspace/runtime data ownership and offline upgrade/DEB compatibility.
- Do not move the package or change ROOT/WORKSPACE assumptions without a separately approved Phase 2 migration.
- Update shared/contracts before changing an externally consumed API, telemetry wire format, video behavior, or control topic.
- Validate with Pixi: pixi run test for backend changes and pixi run test-offline for offline/runtime behavior.

