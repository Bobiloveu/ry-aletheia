const TYPE_BY_INSTANCE_ROLE = Object.freeze({
  outdoor: "outdoor",
  ferry: "ferry",
  lobby: "indoor",
  typical_floor: "floor",
  floor_override: "floor",
});

/**
 * Return the localization facts already fixed by a deployment map instance.
 * A null result retains legacy/manual binding support for projects without a
 * deployment topology.
 */
export function bindingOwnedByTopology(instance) {
  const type = TYPE_BY_INSTANCE_ROLE[instance?.role];
  if (!type) return null;
  if (type === "ferry") return { type, building: "", unit: "" };
  const building = String(instance?.building || "").trim();
  const unit = String(instance?.unit || "").trim();
  return building && unit ? { type, building, unit } : null;
}
