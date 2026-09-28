import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/core/network/api_exception.dart';
import 'package:aletheia_mobile/features/reports/application/reports_controller.dart';
import 'package:aletheia_mobile/features/reports/data/reports_repository.dart';
import 'package:aletheia_mobile/features/reports/domain/native_report_trajectory.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  const key = NativeReportTrajectoryKey(
    reportId: 'rpt_01J8',
    trajectoryId: 'traj_01J8',
  );

  test(
    'loads exact samples only after the user asks for more detail',
    () async {
      final repository = _FakeTrajectoryReportsRepository()
        ..trajectory = _trajectory(nextCursor: 'cursor_01')
        ..pages.add(
          _samplePage(
            samples: [_sample(index: 1), _sample(index: 2)],
            nextCursor: null,
          ),
        );
      final container = _container(repository);
      addTearDown(container.dispose);

      final initial = await container.read(
        nativeReportTrajectoryProvider(key).future,
      );

      expect(initial.samples, isEmpty);
      expect(initial.nextCursor, 'cursor_01');
      expect(repository.cursors, isEmpty);

      await container
          .read(nativeReportTrajectoryProvider(key).notifier)
          .loadMoreSamples();

      final state = container.read(nativeReportTrajectoryProvider(key)).value!;
      expect(state.samples.map((sample) => sample.sampleIndex), [1, 2]);
      expect(state.nextCursor, isNull);
      expect(repository.cursors, ['cursor_01']);
    },
  );

  test(
    'keeps a visible sample path and retry cursor when sample paging fails',
    () async {
      final repository = _FakeTrajectoryReportsRepository()
        ..trajectory = _trajectory(nextCursor: 'cursor_01')
        ..pages.add(
          _samplePage(samples: [_sample(index: 1)], nextCursor: 'cursor_02'),
        )
        ..nextError = const ApiException('轨迹样本读取失败。');
      final container = _container(repository);
      addTearDown(container.dispose);

      await container.read(nativeReportTrajectoryProvider(key).future);
      final controller = container.read(
        nativeReportTrajectoryProvider(key).notifier,
      );
      await controller.loadMoreSamples();
      await controller.loadMoreSamples();

      final state = container.read(nativeReportTrajectoryProvider(key)).value!;
      expect(state.samples.map((sample) => sample.sampleIndex), [1]);
      expect(state.nextCursor, 'cursor_02');
      expect(state.loadMoreError, isA<ApiException>());
      expect(state.isLoadingMore, isFalse);
    },
  );

  test(
    'rejects a duplicate sample index without losing prior samples',
    () async {
      final repository = _FakeTrajectoryReportsRepository()
        ..trajectory = _trajectory(nextCursor: 'cursor_01')
        ..pages.addAll([
          _samplePage(samples: [_sample(index: 1)], nextCursor: 'cursor_02'),
          _samplePage(samples: [_sample(index: 1)], nextCursor: null),
        ]);
      final container = _container(repository);
      addTearDown(container.dispose);

      await container.read(nativeReportTrajectoryProvider(key).future);
      final controller = container.read(
        nativeReportTrajectoryProvider(key).notifier,
      );
      await controller.loadMoreSamples();
      await controller.loadMoreSamples();

      final state = container.read(nativeReportTrajectoryProvider(key)).value!;
      expect(state.samples.map((sample) => sample.sampleIndex), [1]);
      expect(state.nextCursor, 'cursor_02');
      expect(state.loadMoreError, isA<FormatException>());
    },
  );
}

ProviderContainer _container(_FakeTrajectoryReportsRepository repository) =>
    ProviderContainer(
      overrides: [
        robotConnectionControllerProvider.overrideWith(
          _ConnectedController.new,
        ),
        reportsRepositoryProvider.overrideWithValue(repository),
      ],
    );

class _ConnectedController extends RobotConnectionController {
  @override
  RobotConnectionState build() => RobotConnectionState(
    phase: ConnectionPhase.connected,
    endpoint: RobotEndpoint.parse('robot.local'),
  );
}

class _FakeTrajectoryReportsRepository extends ReportsRepository {
  _FakeTrajectoryReportsRepository()
    : super(
        AletheiaApiClient(
          MockClient((_) async => throw StateError('unexpected HTTP request')),
        ),
      );

  NativeReportTrajectory? trajectory;
  final pages = <NativeTrajectorySamplePage>[];
  final cursors = <String>[];
  ApiException? nextError;

  @override
  Future<NativeReportTrajectory> loadNativeTrajectory(
    RobotEndpoint endpoint,
    String reportId,
    String trajectoryId,
  ) async => trajectory!;

  @override
  Future<NativeTrajectorySamplePage> loadNativeTrajectorySamples(
    RobotEndpoint endpoint,
    String reportId,
    String trajectoryId, {
    required String cursor,
    int limit = 200,
  }) async {
    cursors.add(cursor);
    if (nextError != null && cursors.length > 1) throw nextError!;
    return pages.removeAt(0);
  }
}

NativeReportTrajectory _trajectory({String? nextCursor}) =>
    NativeReportTrajectory(
      trajectoryId: 'traj_01J8',
      itemId: 'task_003',
      label: 'T-003 · 一层大厅',
      map: const NativeTrajectoryMap(
        label: '一层大厅',
        resolutionM: 0.05,
        widthCells: 2048,
        heightCells: 1536,
        originXM: -25,
        originYM: -18,
      ),
      displayPaths: const [
        NativeTrajectoryPath(
          routeName: '实际轨迹',
          kind: NativeTrajectoryPathKind.actual,
          points: [NativeTrajectoryPoint(xM: 1, yM: 2)],
        ),
      ],
      virtualWalls: const [],
      sampleCount: 2,
      samplesNextCursor: nextCursor,
    );

NativeTrajectorySamplePage _samplePage({
  required List<NativeTrajectorySample> samples,
  required String? nextCursor,
}) => NativeTrajectorySamplePage(samples: samples, nextCursor: nextCursor);

NativeTrajectorySample _sample({required int index}) => NativeTrajectorySample(
  xM: index.toDouble(),
  yM: index.toDouble(),
  timestampNs: index,
  routeName: '实际轨迹',
  sampleIndex: index,
);
