import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../domain/native_report_trajectory.dart';

/// A value transform for one frozen report map. All raster and vector layers
/// use this conversion so an archived route can never drift from its map.
class ReportTrajectoryViewport {
  const ReportTrajectoryViewport._({
    required this.map,
    required this.viewportSize,
    required this.pixelsPerMeter,
    required this.mapTopLeft,
    required this.fitPixelsPerMeter,
  });

  factory ReportTrajectoryViewport.fit({
    required NativeTrajectoryMap map,
    required Size viewportSize,
  }) {
    final worldWidth = map.widthCells * map.resolutionM;
    final worldHeight = map.heightCells * map.resolutionM;
    final fitPixelsPerMeter = math.min(
      viewportSize.width / worldWidth,
      viewportSize.height / worldHeight,
    );
    final mapSize = Size(
      worldWidth * fitPixelsPerMeter,
      worldHeight * fitPixelsPerMeter,
    );
    return ReportTrajectoryViewport._(
      map: map,
      viewportSize: viewportSize,
      pixelsPerMeter: fitPixelsPerMeter,
      mapTopLeft: Offset(
        (viewportSize.width - mapSize.width) / 2,
        (viewportSize.height - mapSize.height) / 2,
      ),
      fitPixelsPerMeter: fitPixelsPerMeter,
    );
  }

  final NativeTrajectoryMap map;
  final Size viewportSize;
  final double pixelsPerMeter;
  final Offset mapTopLeft;
  final double fitPixelsPerMeter;

  double get worldWidth => map.widthCells * map.resolutionM;
  double get worldHeight => map.heightCells * map.resolutionM;
  double get zoom => pixelsPerMeter / fitPixelsPerMeter;

  Rect get mapRect => Rect.fromLTWH(
    mapTopLeft.dx,
    mapTopLeft.dy,
    worldWidth * pixelsPerMeter,
    worldHeight * pixelsPerMeter,
  );

  Offset worldToScreen(NativeTrajectoryPoint point) => Offset(
    mapTopLeft.dx + (point.xM - map.originXM) * pixelsPerMeter,
    mapTopLeft.dy + (map.originYM + worldHeight - point.yM) * pixelsPerMeter,
  );

  NativeTrajectoryPoint screenToWorld(Offset point) => NativeTrajectoryPoint(
    xM: map.originXM + (point.dx - mapTopLeft.dx) / pixelsPerMeter,
    yM:
        map.originYM +
        worldHeight -
        (point.dy - mapTopLeft.dy) / pixelsPerMeter,
  );

  ReportTrajectoryViewport panBy(Offset delta) => ReportTrajectoryViewport._(
    map: map,
    viewportSize: viewportSize,
    pixelsPerMeter: pixelsPerMeter,
    mapTopLeft: mapTopLeft + delta,
    fitPixelsPerMeter: fitPixelsPerMeter,
  );

  ReportTrajectoryViewport zoomAround(Offset focalPoint, double multiplier) {
    final targetPixelsPerMeter = (pixelsPerMeter * multiplier).clamp(
      fitPixelsPerMeter,
      fitPixelsPerMeter * 6,
    );
    final focalWorld = screenToWorld(focalPoint);
    return ReportTrajectoryViewport._(
      map: map,
      viewportSize: viewportSize,
      pixelsPerMeter: targetPixelsPerMeter,
      mapTopLeft: Offset(
        focalPoint.dx - (focalWorld.xM - map.originXM) * targetPixelsPerMeter,
        focalPoint.dy -
            (map.originYM + worldHeight - focalWorld.yM) * targetPixelsPerMeter,
      ),
      fitPixelsPerMeter: fitPixelsPerMeter,
    );
  }

  NativeTrajectorySample? nearestSample(
    List<NativeTrajectorySample> samples,
    Offset tap, {
    required double maxScreenDistance,
  }) {
    NativeTrajectorySample? nearest;
    var nearestDistanceSquared = maxScreenDistance * maxScreenDistance;
    for (final sample in samples) {
      final distanceSquared = (worldToScreen(sample) - tap).distanceSquared;
      if (distanceSquared <= nearestDistanceSquared) {
        nearest = sample;
        nearestDistanceSquared = distanceSquared;
      }
    }
    return nearest;
  }

  @override
  bool operator ==(Object other) =>
      other is ReportTrajectoryViewport &&
      other.map == map &&
      other.viewportSize == viewportSize &&
      other.pixelsPerMeter == pixelsPerMeter &&
      other.mapTopLeft == mapTopLeft &&
      other.fitPixelsPerMeter == fitPixelsPerMeter;

  @override
  int get hashCode => Object.hash(
    map,
    viewportSize,
    pixelsPerMeter,
    mapTopLeft,
    fitPixelsPerMeter,
  );
}

/// Direct-manipulation workspace for one immutable map segment in a report.
/// It intentionally owns no requests: its parent decides when map and sample
/// data may be read or retried.
class ReportTrajectoryWorkspace extends StatefulWidget {
  const ReportTrajectoryWorkspace({
    required this.trajectory,
    required this.samples,
    required this.mapImage,
    required this.hasMoreSamples,
    required this.onRequestMoreSamples,
    super.key,
  });

  final NativeReportTrajectory trajectory;
  final List<NativeTrajectorySample> samples;
  final ImageProvider? mapImage;
  final bool hasMoreSamples;
  final VoidCallback onRequestMoreSamples;

  @override
  State<ReportTrajectoryWorkspace> createState() =>
      _ReportTrajectoryWorkspaceState();
}

class _ReportTrajectoryWorkspaceState extends State<ReportTrajectoryWorkspace> {
  ReportTrajectoryViewport? _viewport;
  Size? _lastSize;
  NativeTrajectorySample? _selectedSample;
  double _scaleAtGestureStart = 1;

  @override
  void didUpdateWidget(covariant ReportTrajectoryWorkspace oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.trajectory.trajectoryId != widget.trajectory.trajectoryId) {
      _viewport = null;
      _lastSize = null;
      _selectedSample = null;
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final size = Size(constraints.maxWidth, constraints.maxHeight);
      if (size.isEmpty) return const SizedBox.expand();
      if (_viewport == null || _lastSize != size) {
        _lastSize = size;
        _viewport = ReportTrajectoryViewport.fit(
          map: widget.trajectory.map,
          viewportSize: size,
        );
      }
      final viewport = _viewport!;
      return Semantics(
        label: '${widget.trajectory.label} 地图运行轨迹',
        child: ClipRect(
          child: Stack(
            fit: StackFit.expand,
            children: [
              ColoredBox(color: AletheiaTheme.surfaceSunken),
              if (widget.mapImage != null)
                Positioned.fromRect(
                  rect: viewport.mapRect,
                  child: Image(
                    image: widget.mapImage!,
                    fit: BoxFit.fill,
                    filterQuality: FilterQuality.none,
                    // A report segment may never briefly show a different
                    // segment's frozen map while its replacement loads.
                    gaplessPlayback: false,
                    errorBuilder: (_, _, _) => _MapUnavailable(),
                    loadingBuilder: (context, child, progress) =>
                        progress == null ? child : const _MapLoading(),
                  ),
                )
              else
                const _MapLoading(),
              RepaintBoundary(
                child: CustomPaint(
                  painter: _ReportTrajectoryPainter(
                    trajectory: widget.trajectory,
                    viewport: viewport,
                    selectedSample: _selectedSample,
                    minorGrid: AletheiaTheme.mapGridMinor,
                    majorGrid: AletheiaTheme.mapGridMajor,
                    virtualWall: AletheiaTheme.mapVirtualWall,
                    actualRoute: AletheiaTheme.cyan,
                    idealRoute: AletheiaTheme.warning,
                  ),
                ),
              ),
              GestureDetector(
                key: const ValueKey('report-trajectory-gesture-surface'),
                behavior: HitTestBehavior.opaque,
                onScaleStart: (details) => _scaleAtGestureStart = viewport.zoom,
                onScaleUpdate: (details) {
                  final next = details.scale == 1
                      ? viewport.panBy(details.focalPointDelta)
                      : viewport.zoomAround(
                          details.localFocalPoint,
                          (details.scale * _scaleAtGestureStart) /
                              viewport.zoom,
                        );
                  setState(() => _viewport = next);
                },
                onTapUp: (details) =>
                    _selectSample(viewport, details.localPosition),
              ),
              Positioned(
                top: 8,
                right: 8,
                child: IconButton.filledTonal(
                  tooltip: '复位地图',
                  onPressed: () => setState(
                    () => _viewport = ReportTrajectoryViewport.fit(
                      map: widget.trajectory.map,
                      viewportSize: size,
                    ),
                  ),
                  icon: const Icon(Icons.center_focus_strong_rounded, size: 18),
                ),
              ),
              if (_selectedSample != null)
                Positioned(
                  left: 10,
                  bottom: 10,
                  child: _SampleReadout(sample: _selectedSample!),
                ),
            ],
          ),
        ),
      );
    },
  );

  void _selectSample(ReportTrajectoryViewport viewport, Offset position) {
    final sample = viewport.nearestSample(
      widget.samples,
      position,
      maxScreenDistance: 28,
    );
    if (sample != null) {
      setState(() => _selectedSample = sample);
    } else if (widget.hasMoreSamples) {
      widget.onRequestMoreSamples();
    }
  }
}

class _MapLoading extends StatelessWidget {
  const _MapLoading();

  @override
  Widget build(BuildContext context) => const Center(
    child: SizedBox(width: 24, height: 24, child: CircularProgressIndicator()),
  );
}

class _MapUnavailable extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Center(
    child: Icon(
      Icons.map_outlined,
      color: AletheiaTheme.textTertiary,
      size: 28,
    ),
  );
}

class _SampleReadout extends StatelessWidget {
  const _SampleReadout({required this.sample});
  final NativeTrajectorySample sample;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: AletheiaTheme.surface.withValues(alpha: .94),
      borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      border: Border.all(color: AletheiaTheme.border),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      child: Text(
        '采样点 ${sample.sampleIndex + 1} · ${sample.routeName}',
        style: Theme.of(context).textTheme.labelMedium,
      ),
    ),
  );
}

class _ReportTrajectoryPainter extends CustomPainter {
  const _ReportTrajectoryPainter({
    required this.trajectory,
    required this.viewport,
    required this.selectedSample,
    required this.minorGrid,
    required this.majorGrid,
    required this.virtualWall,
    required this.actualRoute,
    required this.idealRoute,
  });

  final NativeReportTrajectory trajectory;
  final ReportTrajectoryViewport viewport;
  final NativeTrajectorySample? selectedSample;
  final Color minorGrid;
  final Color majorGrid;
  final Color virtualWall;
  final Color actualRoute;
  final Color idealRoute;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.clipRect(viewport.mapRect);
    _drawGrid(canvas);
    _drawWalls(canvas);
    for (final path in trajectory.displayPaths) {
      _drawPath(
        canvas,
        path.points,
        path.kind == NativeTrajectoryPathKind.actual ? actualRoute : idealRoute,
        path.kind == NativeTrajectoryPathKind.actual ? 2.5 : 1.8,
      );
    }
    final sample = selectedSample;
    if (sample != null) {
      final center = viewport.worldToScreen(sample);
      canvas.drawCircle(center, 8, Paint()..color = AletheiaTheme.surface);
      canvas.drawCircle(center, 5, Paint()..color = actualRoute);
    }
    canvas.restore();
    canvas.drawRect(
      viewport.mapRect,
      Paint()
        ..color = AletheiaTheme.border.withValues(alpha: .8)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );
  }

  void _drawGrid(Canvas canvas) {
    final minorMeters = _gridMetersFor(viewport.pixelsPerMeter);
    _drawGridLines(canvas, minorMeters, minorGrid, .7);
    _drawGridLines(canvas, minorMeters * 5, majorGrid, 1);
  }

  void _drawGridLines(
    Canvas canvas,
    double meters,
    Color color,
    double strokeWidth,
  ) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth;
    final maxX = trajectory.map.originXM + viewport.worldWidth;
    final maxY = trajectory.map.originYM + viewport.worldHeight;
    for (
      var x = (trajectory.map.originXM / meters).ceilToDouble() * meters;
      x <= maxX + .000001;
      x += meters
    ) {
      final top = viewport.worldToScreen(
        NativeTrajectoryPoint(xM: x, yM: maxY),
      );
      final bottom = viewport.worldToScreen(
        NativeTrajectoryPoint(xM: x, yM: trajectory.map.originYM),
      );
      canvas.drawLine(top, bottom, paint);
    }
    for (
      var y = (trajectory.map.originYM / meters).ceilToDouble() * meters;
      y <= maxY + .000001;
      y += meters
    ) {
      final left = viewport.worldToScreen(
        NativeTrajectoryPoint(xM: trajectory.map.originXM, yM: y),
      );
      final right = viewport.worldToScreen(
        NativeTrajectoryPoint(xM: maxX, yM: y),
      );
      canvas.drawLine(left, right, paint);
    }
  }

  void _drawWalls(Canvas canvas) {
    for (final wall in trajectory.virtualWalls) {
      _drawPath(canvas, wall, virtualWall, 2);
    }
  }

  void _drawPath(
    Canvas canvas,
    List<NativeTrajectoryPoint> points,
    Color color,
    double strokeWidth,
  ) {
    if (points.isEmpty) return;
    final path = Path()
      ..moveTo(
        viewport.worldToScreen(points.first).dx,
        viewport.worldToScreen(points.first).dy,
      );
    for (final point in points.skip(1)) {
      final screen = viewport.worldToScreen(point);
      path.lineTo(screen.dx, screen.dy);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..strokeWidth = strokeWidth,
    );
  }

  @override
  bool shouldRepaint(covariant _ReportTrajectoryPainter oldDelegate) =>
      oldDelegate.trajectory != trajectory ||
      oldDelegate.viewport != viewport ||
      oldDelegate.selectedSample != selectedSample ||
      oldDelegate.minorGrid != minorGrid ||
      oldDelegate.majorGrid != majorGrid ||
      oldDelegate.virtualWall != virtualWall ||
      oldDelegate.actualRoute != actualRoute ||
      oldDelegate.idealRoute != idealRoute;
}

double _gridMetersFor(double pixelsPerMeter) {
  for (final meters in const [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]) {
    if (pixelsPerMeter * meters >= 26) return meters;
  }
  return 20;
}
