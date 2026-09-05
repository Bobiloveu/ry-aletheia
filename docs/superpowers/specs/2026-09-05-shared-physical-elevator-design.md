# Shared Physical Elevator Design

## Goal

Represent one physical elevator once within a deployment project while allowing
each served map to show its own elevator landing, centre coordinate and door
orientation.  The experimental indoor-elevator compiler must continue to
generate the current approved artifacts without writing to robot runtime
directories.

## Scope

This change applies only to deployment-project persistence, the PC deployment
editor, and the `indoor_elevator_v1` experimental compiler.  It does not change
ROS ownership, runtime task installation, protocol wire formats, localization
files, speed-mode definitions, or existing map assets.

## Model

The project document gains `physical_elevators`, a project-level list.  Each
entry has a generated immutable `id`, the user-confirmed unique `elevator_id`,
and the shared hardware facts:

- `elevator_protocol`
- `min_floor` and `max_floor`

An existing `kind: "elevator"` component becomes a map-local elevator landing.
It keeps its existing `map_asset_id`, `x`, `y`, `yaw`, `label`, dimensions and
`wait_distance_m`, and adds `physical_elevator_id`.  Its `yaw` remains the door
direction for that individual landing; it is intentionally not shared because
different floors may have different door-facing directions.

The map instance remains the authority for a landing's logical floor.  The
compiler calculates its robot physical floor from that value (`logical + 1`),
as it already does.  A landing therefore no longer stores editable `map_floor`
or `physical_floor` facts.  Legacy copies remain harmless during migration but
are ignored after the physical elevator relation is present.

## Editor workflow

When a user puts the first elevator on a project map, the editor creates a new
physical elevator and its first landing.  The editor asks for the unique
elevator number and shared hardware details as it does today.

When a user puts an elevator on another map, the editor defaults to **关联已有
电梯**.  It presents existing elevator numbers; choosing one creates only a
landing and shows the shared fields as read-only context.  The user enters or
adjusts only local geometry: size, wait distance, map position, and door
orientation.  A deliberate **新建物理电梯** choice is also available for sites
with more than one lift.

The map marker and its existing door-direction symbol are always rendered from
the local landing `yaw`, including on floors that reference the same physical
elevator.

## Compatibility and validation

`DeploymentStore.get()` normalizes old projects before use.  For each legacy
elevator component it creates or reuses one physical elevator keyed by its
nonempty `attributes.elevator_id`, copies protocol and service range into the
shared entity, and writes the local component relation.  If old copies for the
same elevator disagree on shared facts, loading remains non-destructive and
marks the compiler input invalid with a clear resolution error; it never picks
one silently.

Creation rejects a duplicate physical `elevator_id` in the same project.
Updating a shared physical entity is the only way to change its protocol or
service range.  Removing a protocol that a physical elevator uses is rejected.
Deleting a landing removes only that map marker; deleting a physical elevator is
rejected until all of its landings have been removed.

## Compiler behavior

`compile_indoor_elevator()` selects exactly one landing on each required map
stage and requires that both landings refer to the same `physical_elevator_id`.
It resolves protocol and service-range facts from the physical elevator, then
derives each floor from its map instance and each wait/centre pose from that
landing's local geometry and yaw.  Thus the generated caller origin-floor
parameters and all approved behavior-tree names remain unchanged, while the
two map markers cannot drift into independent descriptions of one lift.

For legacy fixture documents that have no `physical_elevators`, the pure
compiler retains its current `elevator_id` pair validation.  Store-managed
projects are migrated on read and use the new relation.

## APIs and user-visible errors

Existing component endpoints remain the editor's marker API.  Add project-owned
physical-elevator operations under the deployment HTTP boundary; browsers still
call only HTTP and never ROS.  Errors distinguish: duplicate elevator number,
unknown shared elevator, missing landing relation, two selected maps pointing
at different physical elevators, and conflicting legacy shared fields.

No cross-client contract changes are required: this is a deployment console
document and its HTTP API has no Mobile consumer.  The backend and its web
consumer will be changed together.

## Tests

Backend tests cover unique identifier enforcement, second-map association,
legacy migration, shared-field consistency, protocol removal protection, and
compiler rejection of a mismatched pair.  Compiler tests prove that separate
landing yaws produce independent waiting points while both floor-specific
behavior-tree parameters resolve from their map instances.  Web static tests
cover the association controls and local door-marker rendering.

The focused Pytest suites and the web build/check must pass before handoff.
