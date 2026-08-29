/// Shared breakpoint rules for the landscape-first operator workflow.
///
/// The values are based on the usable content width after system chrome, not
/// device categories, so they work for phones, tablets and desktop windows.
bool usesNavigationRail({
  required double availableWidth,
  required bool isLandscape,
}) => availableWidth >= 840 || (isLandscape && availableWidth >= 600);

bool usesTwoColumnWorkspace({
  required double availableWidth,
  required bool isLandscape,
}) => availableWidth >= 840 || (isLandscape && availableWidth >= 700);

bool isCompactLandscape({
  required double viewportHeight,
  required bool isLandscape,
}) => isLandscape && viewportHeight < 600;

/// Reserve only the compact workspace chrome and let map/video use the rest
/// of the available HMI viewport. The caller supplies the body height after
/// app and system bars, so this stays stable across phones, tablets and split
/// view instead of assuming a device class.
double observationWorkspaceHeight({
  required double viewportHeight,
  required bool isLandscape,
}) {
  // In short landscape the workspace switcher is integrated into the map or
  // camera controls. Map status now sits as a compact in-canvas overlay, so
  // it no longer consumes a permanent row beneath the primary work area.
  final reservedHeight = isLandscape ? 12.0 : 206.0;
  final minimumHeight = isLandscape ? 220.0 : 380.0;
  final maximumHeight = isLandscape ? 520.0 : 640.0;
  return (viewportHeight - reservedHeight)
      .clamp(minimumHeight, maximumHeight)
      .toDouble();
}
