# Deployment and map configuration

**Status: Existing**
**Authoritative implementations:** autodrive_console/deployment.py, autodrive_console/mapping.py, web_console.py, and deployment Web UI
**Consumers:** robot_backend, web_console, mobile
**Compatibility:** Additive changes first; breaking changes require all consumers and this document to change together.

The existing deployment API begins at /api/deployments. Per-project routes cover map import/upload, map stages, transitions, routes, scene model, map instances, waypoints, component templates/components, virtual walls, and topology. Mapping sessions are controlled through /api/mapping and /api/mapping/sessions routes.

Backend validation is authoritative: clients display and submit user intent but do not write deployment files or robot configuration directly. Map image, metadata, virtual wall, and topology edits retain project/map ownership.

## Planned

New deployment data formats must be described in shared/schemas before they are cross-client inputs. Planned fields remain Planned until the backend exposes and validates them.
