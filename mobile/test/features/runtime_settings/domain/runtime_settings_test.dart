import 'package:aletheia_mobile/features/runtime_settings/domain/runtime_settings.dart';
import 'package:test/test.dart';

void main() {
  test(
    'replaces stale monitored dependencies with the enabled plan nodes on save',
    () {
      const settings = RuntimeSettings(
        taskDirectory: '/opt/ry/data/tasks',
        commandTimeoutSeconds: 8,
        elevatorWaitTimeoutSeconds: 180,
        taskExecutionTimeoutSeconds: 900,
        monitorNodes: [
          'MODULES:209-lightning',
          'MODULES:211-navigate_todoor_server',
          'Tasks:212-navigate_todoor_server',
        ],
        dependencyPlan: DependencyPlan(
          enabled: true,
          steps: [
            DependencyStep(
              nodes: [
                'Tasks:212-navigate_todoor_server',
                'Tasks:213-task_execute_server',
              ],
              waitSeconds: 0,
            ),
            DependencyStep(
              nodes: [
                'Navigation:211-fcrp_bringup',
                'Tasks:212-navigate_todoor_server',
              ],
              waitSeconds: 5,
            ),
          ],
        ),
        liveObservation: LiveObservationSettings(
          enabled: false,
          idleStopSeconds: 45,
          vehicleModels: [],
          activeVehicleModel: '',
        ),
      );

      expect(settings.toJson()['monitor_nodes'], [
        'Tasks:212-navigate_todoor_server',
        'Tasks:213-task_execute_server',
        'Navigation:211-fcrp_bringup',
      ]);
    },
  );

  test(
    'keeps manual monitoring when automatic dependency orchestration is off',
    () {
      const settings = RuntimeSettings(
        taskDirectory: '/opt/ry/data/tasks',
        commandTimeoutSeconds: 8,
        elevatorWaitTimeoutSeconds: 180,
        taskExecutionTimeoutSeconds: 900,
        monitorNodes: ['MODULES:209-lightning'],
        dependencyPlan: DependencyPlan(enabled: false, steps: []),
        liveObservation: LiveObservationSettings(
          enabled: false,
          idleStopSeconds: 45,
          vehicleModels: [],
          activeVehicleModel: '',
        ),
      );

      expect(settings.toJson()['monitor_nodes'], ['MODULES:209-lightning']);
    },
  );
}
