/**
 * Keep the operator's current map framing through a discontinuous pose change.
 * A completed relocalization may move the vehicle many metres at once; treating
 * that as ordinary driving would snap the camera away from the map being read.
 */
export function freezeMapViewportForRelocalization(mapView, layout) {
  const center = mapView.center || layout?.center;
  if (center)
    mapView.center = { x: Number(center.x), y: Number(center.y) };
  mapView.followVehicle = false;
  mapView.followOffset = { x: 0, y: 0 };
}
