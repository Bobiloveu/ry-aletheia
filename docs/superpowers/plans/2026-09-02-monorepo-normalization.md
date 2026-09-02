# RY Aletheia Monorepo 整理实施记录

**Spec:** ../specs/2026-09-02-monorepo-normalization-design.md  
**Status:** Implemented in chore/monorepo-normalization.

1. Added a path/layout regression test without moving source directories.
2. Pinned Flutter 3.47.1 through mobile/.fvmrc and standardized FVM documentation.
3. Added Existing cross-client contracts and shared-directory admission rules.
4. Added scripts/ entrypoints, Pixi aliases, and FVM-aware Flutter packaging delegation.
5. Added root/backend/Web Agent rules and documentation indexes.
6. Added path-filtered GitHub Actions checks.
7. Verified Pixi backend/Web checks and recorded FVM/JDK environment limits.

The implementation intentionally does not migrate backend, Web, Mobile, ROS2/C++, or Unity source.

