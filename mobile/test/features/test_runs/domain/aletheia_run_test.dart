import 'package:aletheia_mobile/features/test_runs/domain/aletheia_run.dart';
import 'package:test/test.dart';

void main() {
  test('preserves the backend recovery state and progress semantics', () {
    final run = AletheiaRun.fromJson({
      'id': 'run123',
      'case': {'id': 'case.json', 'filename': 'case.json', 'name': '路线验证'},
      'requestedCount': 3,
      'intervalSeconds': 3,
      'status': 'awaiting_recovery',
      'error': 'T-001 执行失败，请恢复车辆。',
      'preflight': {
        'ros_service': {'message': '服务已就绪'},
        'node_states': [
          {
            'id': 'navigation',
            'label': '导航服务',
            'supervisor': 'robot-navigation',
            'required': true,
            'status': 'RUNNING',
          },
          {
            'id': 'recorder',
            'label': '轨迹记录',
            'supervisor': 'robot-recorder',
            'required': false,
            'status': 'BACKOFF',
          },
        ],
      },
      'liveProgress': null,
      'cancelRequested': false,
      'activeAttempt': null,
      'summary': {
        'completed': 1,
        'passed': 0,
        'failed': 1,
        'cancelled': 0,
        'passRate': 0,
      },
      'attempts': [
        {
          'index': 1,
          'status': 'failed',
          'message': '服务返回失败',
          'duration_s': 12.5,
          'started_at': '2026-08-26T10:00:00+08:00',
        },
      ],
      'interventions': [],
    });

    expect(run.status, AletheiaRunStatus.awaitingRecovery);
    expect(run.status.isActive, isTrue);
    expect(run.status.canCancel, isTrue);
    expect(run.preflightMessage, '服务已就绪');
    expect(run.supervisorNodes, hasLength(2));
    expect(run.supervisorNodes.first.isRunning, isTrue);
    expect(run.supervisorNodes.last.required, isFalse);
    expect(run.supervisorNodes.last.statusLabel, '正在重试');
    expect(run.supervisorStateSignature, contains('navigation:RUNNING:true'));
    expect(run.attempts.single.durationSeconds, 12.5);
  });

  test('serializes only the supported test-plan contract', () {
    const request = TestRunRequest(
      caseId: '社区_1_2_3_4.json',
      count: 2,
      intervalSeconds: 5,
    );

    expect(request.toJson(), {
      'caseId': '社区_1_2_3_4.json',
      'count': 2,
      'intervalSeconds': 5,
      'prepareTrajectoryMaps': true,
    });
  });
}
