# RY Aletheia Monorepo 整理设计

**Status:** Implemented, Phase 1  
**Scope:** Logical Monorepo boundaries only; no physical source migration.

## Decision

Robot backend remains at web_console.py plus autodrive_console/ and live_preprocessor/. Web source remains frontend/ and builds to autodrive_console/web-vue/. Flutter remains mobile/. Unity remains a paused renderer PoC.

## Implemented foundation

- shared/contracts/ is the cross-client interface source of truth; Existing and Planned are separate.
- Root Pixi remains the backend/Web toolchain; compatibility aliases preserve existing tasks.
- mobile/.fvmrc pins Flutter 3.47.1. Android and iOS platform versions remain unchanged.
- scripts/ provides bootstrap, doctor, backend/Web/Mobile test, and Flutter-only mobile build entrypoints.
- Root/module AGENTS and docs indexes define maintenance ownership.
- CI filters backend, Web, Mobile, and contract changes by path.

## Future physical migration

Only migrate into apps/ after backend workspace-root, Vite/static-resource, packaging/C++/test, and Flutter relative-path dependencies are decoupled and validated in a Linux ROS release environment.

