import 'package:aletheia_mobile/features/reports/domain/native_report_trajectory.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final validMap = {
    'label': '一层大厅',
    'resolution_m': 0.05,
    'width_cells': 2048,
    'height_cells': 1536,
    'origin_x_m': -25.0,
    'origin_y_m': -18.0,
  };

  final validTrajectory = {
    'schema_version': 1,
    'trajectory_id': 'traj_01J8A',
    'item_id': 'task_003',
    'label': 'T-003 · 一层大厅',
    'map': validMap,
    'display_paths': [
      {
        'route_name': '实际轨迹',
        'kind': 'actual',
        'points': [
          {'x_m': 1.2, 'y_m': 3.4},
          {'x_m': 1.6, 'y_m': 3.8},
        ],
      },
      {
        'route_name': '理想路线',
        'kind': 'ideal',
        'points': [
          {'x_m': 1.0, 'y_m': 3.0},
          {'x_m': 2.0, 'y_m': 4.0},
        ],
      },
    ],
    'virtual_walls': [
      [
        {'x_m': 0.0, 'y_m': 0.0},
        {'x_m': 4.0, 'y_m': 0.0},
      ],
    ],
    'sample_count': 624,
    'integrity_warning': null,
    'samples_next_cursor': 'cursor_01',
  };

  test('accepts a safe native trajectory reference', () {
    final reference = NativeReportTrajectoryRef.tryFromJson({
      'trajectory_id': 'traj_01J8A',
      'label': 'T-003 · 一层大厅',
      'status': 'available',
      'sample_count': 624,
      'integrity_warning': null,
    });

    expect(reference, isNotNull);
    expect(reference!.trajectoryId, 'traj_01J8A');
    expect(reference.availability, NativeTrajectoryAvailability.available);
    expect(reference.sampleCount, 624);
  });

  test('rejects a path-bearing native trajectory reference', () {
    expect(
      NativeReportTrajectoryRef.tryFromJson({
        'trajectory_id': '../map',
        'label': 'T-003 · 一层大厅',
        'status': 'available',
        'sample_count': 624,
        'integrity_warning': null,
      }),
      isNull,
    );
  });

  test('accepts a finite frozen map trajectory', () {
    final trajectory = NativeReportTrajectory.tryFromJson(validTrajectory);

    expect(trajectory, isNotNull);
    expect(trajectory!.map.resolutionM, 0.05);
    expect(trajectory.displayPaths, hasLength(2));
    expect(trajectory.displayPaths.first.kind, NativeTrajectoryPathKind.actual);
    expect(trajectory.virtualWalls.single, hasLength(2));
    expect(trajectory.samplesNextCursor, 'cursor_01');
  });

  test('rejects unsafe trajectory geometry', () {
    expect(
      NativeReportTrajectory.tryFromJson({
        ...validTrajectory,
        'map': {...validMap, 'resolution_m': 0},
      }),
      isNull,
    );
    expect(
      NativeReportTrajectory.tryFromJson({
        ...validTrajectory,
        'display_paths': [
          {
            'route_name': '实际轨迹',
            'kind': 'actual',
            'points': [
              {'x_m': double.nan, 'y_m': 3.4},
            ],
          },
        ],
      }),
      isNull,
    );
  });

  test('rejects unordered raw samples', () {
    expect(
      () => NativeTrajectorySamplePage.fromJson({
        'samples': [
          {
            'x_m': 1.2,
            'y_m': 3.4,
            'timestamp_ns': 10,
            'route_name': '实际轨迹',
            'sample_index': 2,
          },
          {
            'x_m': 1.6,
            'y_m': 3.8,
            'timestamp_ns': 11,
            'route_name': '实际轨迹',
            'sample_index': 1,
          },
        ],
        'next_cursor': null,
      }),
      throwsFormatException,
    );
  });
}
