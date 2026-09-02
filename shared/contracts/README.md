# Cross-client contracts

This directory is the documentation source of truth for interfaces shared by robot_backend, web_console, and mobile. It contains versioned facts and examples, not implementation code.

## Status labels

- **Status: Existing** — implemented and consumed today; preserve compatibility.
- **Status: Planned** — design intent only; do not implement or depend on it as available.

## Change rule

Make additive changes first. A breaking API, ROS Topic, WebSocket wire-format, or data-model change must update its contract, each consumer, and that consumer's focused verification in the same change.

## Contract catalog

- [Robot control](robot_control.md)
- [Realtime observation](realtime_observation.md)
- [Video](video.md)
- [Task execution](task_execution.md)
- [Deployment](deployment.md)

