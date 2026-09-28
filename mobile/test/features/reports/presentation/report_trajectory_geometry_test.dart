import 'package:aletheia_mobile/features/reports/domain/native_report_trajectory.dart';
import 'package:aletheia_mobile/features/reports/presentation/report_trajectory_workspace.dart';
import 'package:flutter/widgets.dart';
import 'package:test/test.dart';

void main() {
  const map = NativeTrajectoryMap(
    label: '一层大厅',
    resolutionM: 0.5,
    widthCells: 20,
    heightCells: 10,
    originXM: -2,
    originYM: -1,
  );

  test(
    'world and screen coordinates round-trip through the frozen map fit',
    () {
      final viewport = ReportTrajectoryViewport.fit(
        map: map,
        viewportSize: const Size(320, 240),
      );
      const point = NativeTrajectoryPoint(xM: 3.5, yM: 1.25);

      final roundTrip = viewport.screenToWorld(viewport.worldToScreen(point));

      expect(roundTrip.xM, closeTo(point.xM, .0001));
      expect(roundTrip.yM, closeTo(point.yM, .0001));
    },
  );

  test('zoom retains the world point beneath its focal point', () {
    final viewport = ReportTrajectoryViewport.fit(
      map: map,
      viewportSize: const Size(320, 240),
    );
    const focalPoint = Offset(90, 110);
    final worldBefore = viewport.screenToWorld(focalPoint);

    final zoomed = viewport.zoomAround(focalPoint, 2);

    final worldAfter = zoomed.screenToWorld(focalPoint);
    expect(worldAfter.xM, closeTo(worldBefore.xM, .0001));
    expect(worldAfter.yM, closeTo(worldBefore.yM, .0001));
  });

  test('selects only a nearby exact sample in screen space', () {
    final viewport = ReportTrajectoryViewport.fit(
      map: map,
      viewportSize: const Size(320, 240),
    );
    final samples = [
      const NativeTrajectorySample(
        xM: 2,
        yM: 2,
        timestampNs: 1,
        routeName: '实际轨迹',
        sampleIndex: 17,
      ),
      const NativeTrajectorySample(
        xM: 9,
        yM: 3,
        timestampNs: 2,
        routeName: '实际轨迹',
        sampleIndex: 18,
      ),
    ];

    final near = viewport.worldToScreen(samples.first);
    expect(
      viewport.nearestSample(samples, near, maxScreenDistance: 28)?.sampleIndex,
      17,
    );
    expect(
      viewport.nearestSample(samples, const Offset(2, 2), maxScreenDistance: 6),
      isNull,
    );
  });
}
