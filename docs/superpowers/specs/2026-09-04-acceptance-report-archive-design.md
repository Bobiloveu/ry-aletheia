# Deployment Acceptance Report Archive Design

## Purpose

Make deployment acceptance a first-class, offline-readable report in the existing Report Center. It must help an implementation engineer understand the result and evidence without making optional runtime preparation look mandatory.

## Scope and boundaries

- Desktop Web only for the acceptance and Report Center interface changes.
- `reports/` remains the single archive. `AcceptanceOrchestrator` and `RunManager` remain the only owners of task execution, ROS, scenario application, Supervisor orchestration and recovery.
- Mobile keeps its current UI. Its existing report-list consumer only receives backward-compatible additional fields.
- The normal acceptance path stays default: no scenario and no Supervisor orchestration unless selected explicitly.

## Report archive

`GET /api/reports` will enumerate both existing test report HTML files and validated `acceptance_<plan-id>_<timestamp>.html` reports. It preserves `filename`, `size`, `modified_at` and `csv_filename`, and adds `report_type` (`test` or `acceptance`) plus a human title.

Existing preview, HTML download, CSV download and delete endpoints serve both types. An acceptance report writes a validated sidecar manifest with only its report-owned trajectory directories. Deletion removes its HTML, CSV, manifest and only those strictly validated directories. Legacy acceptance reports without a manifest still delete HTML and CSV safely.

## Acceptance HTML evidence

The acceptance writer creates self-contained, printable HTML using the existing test-report evidence vocabulary: conclusion badge, pass rate, scope, completed task count, elapsed time, creation/start/finish times, actual physical-building/floor/door coverage, frozen runtime-preparation summary, and a per-task table with status, start, finish, duration and feedback.

Verified SVG maps are inlined for each task, including actual trajectory, ideal route and virtual walls if captured. Missing trajectory is called out as incomplete evidence. Random seed is never displayed. All task text is escaped and all SVG paths are revalidated; the downloaded HTML does not depend on `reports/` assets.

## Optional runtime preparation

The page will call this “可选运行准备”. Its closed/default state says “不使用额外运行准备，按常规验收流程执行”. Saved scene and saved Supervisor plan controls are progressively disclosed only when needed.

Plans persist a validated runtime status separate from the frozen option snapshot: `state`, `message`, `updated_at`. The existing sequence callback updates it through pending, applying scenario, settling, restarting dependencies, ready, restoring normal script, restored, cancelled and blocked. Browser users can observe but never alter this state or node commands.

## Draft recovery and compatibility

Before a plan is created, the desktop browser stores scope, community, building-unit, mode, sample size, saved profile ID and dependency checkbox under a versioned localStorage key. It restores after navigation or refresh, revalidates current options, and clears after a successful plan creation. It never writes robot configuration.

Existing test reports and schema-1/2 acceptance plans remain readable. Malformed filenames, manifests and paths are rejected; deletion never follows arbitrary directories. No selected optional condition retains the exact existing execution behavior.

## Verification

Automated checks cover report classification, safe cleanup, legacy compatibility, self-contained trajectories and times, progress persistence, and desktop draft behavior. Backend suite, web build, whitespace check, design detector and a desktop browser pass verify the result.
