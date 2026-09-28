import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/features/reports/domain/native_report_trajectory.dart';
import 'package:aletheia_mobile/features/reports/presentation/report_trajectory_workspace.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'keeps map loading local and requests more samples only after a precision tap',
    (tester) async {
      var requestedMore = 0;
      await tester.pumpWidget(
        MaterialApp(
          theme: AletheiaTheme.light(),
          home: Scaffold(
            body: SizedBox(
              width: 320,
              height: 240,
              child: ReportTrajectoryWorkspace(
                trajectory: _trajectory,
                samples: const [],
                mapImage: null,
                hasMoreSamples: true,
                onRequestMoreSamples: () => requestedMore += 1,
              ),
            ),
          ),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      await tester.tapAt(const Offset(150, 120));

      expect(requestedMore, 1);
    },
  );

  testWidgets('selects a loaded sample without requesting another page', (
    tester,
  ) async {
    var requestedMore = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AletheiaTheme.light(),
        home: Scaffold(
          body: SizedBox(
            width: 320,
            height: 240,
            child: ReportTrajectoryWorkspace(
              trajectory: _trajectory,
              samples: const [_sample],
              mapImage: null,
              hasMoreSamples: true,
              onRequestMoreSamples: () => requestedMore += 1,
            ),
          ),
        ),
      ),
    );

    // 10×5 m map fits a 320×240 viewport at 32 px/m with 40 px top inset;
    // (2, 2) maps to (64, 136).
    await tester.tapAt(const Offset(64, 136));
    await tester.pump();

    expect(find.textContaining('采样点 18'), findsOneWidget);
    expect(requestedMore, 0);
  });
}

const _trajectory = NativeReportTrajectory(
  trajectoryId: 'traj_01J8',
  itemId: 'task_003',
  label: 'T-003 · 一层大厅',
  map: NativeTrajectoryMap(
    label: '一层大厅',
    resolutionM: 0.5,
    widthCells: 20,
    heightCells: 10,
    originXM: 0,
    originYM: 0,
  ),
  displayPaths: [
    NativeTrajectoryPath(
      routeName: '实际轨迹',
      kind: NativeTrajectoryPathKind.actual,
      points: [NativeTrajectoryPoint(xM: 2, yM: 2)],
    ),
  ],
  virtualWalls: [],
  sampleCount: 1,
  samplesNextCursor: 'cursor_01',
);

const _sample = NativeTrajectorySample(
  xM: 2,
  yM: 2,
  timestampNs: 1,
  routeName: '实际轨迹',
  sampleIndex: 17,
);
