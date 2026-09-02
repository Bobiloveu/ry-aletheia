# Phase 2 physical migration prerequisites

Do not move source into apps/ until all conditions hold:

1. Backend supports explicit package/workspace roots instead of implicit repository-parent paths.
2. Vite output and backend static lookup support a configured migration-compatible location.
3. PyInstaller, DEB, upgrade, C++ build scripts, and path-sensitive tests use module-root resolution.
4. Flutter UI documentation, Golden tests, and paused Unity contract tests do not depend on fixed parent paths.
5. Linux ROS release validation passes before and after the migration.

Until then, apps/ is documentation only.

