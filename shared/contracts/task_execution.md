# Task execution

**Status: Existing**
**Authoritative implementations:** web_console.py, autodrive_console/case_store.py, autodrive_console/run_manager.py, and Mobile feature repositories
**Consumers:** robot_backend, web_console, mobile
**Compatibility:** Additive changes first; breaking changes require all consumers and this document to change together.

The backend owns task files, validation, execution state, reports, cancellation, recovery, and supervisor coordination. Existing API families are /api/cases, /api/runs, /api/runs/latest, /api/reports, /api/scenario-setup, /api/supervisor/processes, and /api/tool-logs.

Mutating operations are controlled actions: client UI exposes target, confirmation, returned error, and current state. Mobile may consume these APIs but must not directly rewrite robot tasks, run arbitrary commands, or create an offline upgrade package.

## Planned

New task schema versions need a JSON schema in shared/schemas, backend validation, a consumer compatibility review, and migration guidance before use.

