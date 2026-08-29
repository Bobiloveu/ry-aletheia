class RuntimeSettings {
  const RuntimeSettings({
    required this.taskDirectory,
    required this.commandTimeoutSeconds,
    required this.elevatorWaitTimeoutSeconds,
    required this.taskExecutionTimeoutSeconds,
    required this.monitorNodes,
    required this.dependencyPlan,
    required this.liveObservation,
  });

  factory RuntimeSettings.fromJson(Map<String, dynamic> json) =>
      RuntimeSettings(
        taskDirectory: _text(json['task_directory']),
        commandTimeoutSeconds: _number(json['command_timeout_s'], fallback: 8),
        elevatorWaitTimeoutSeconds: _number(
          json['elevator_wait_timeout_s'],
          fallback: 180,
        ),
        taskExecutionTimeoutSeconds: _number(
          json['task_execution_timeout_s'],
          fallback: 900,
        ),
        monitorNodes: (json['monitor_nodes'] as List<Object?>? ?? const [])
            .whereType<String>()
            .toList(growable: false),
        dependencyPlan: DependencyPlan.fromJson(_map(json['dependency_plan'])),
        liveObservation: LiveObservationSettings.fromJson(
          _map(json['live_observation']),
        ),
      );

  final String taskDirectory;
  final int commandTimeoutSeconds;
  final int elevatorWaitTimeoutSeconds;
  final int taskExecutionTimeoutSeconds;
  final List<String> monitorNodes;
  final DependencyPlan dependencyPlan;
  final LiveObservationSettings liveObservation;

  Map<String, dynamic> toJson() => {
    'task_directory': taskDirectory,
    'command_timeout_s': commandTimeoutSeconds,
    'elevator_wait_timeout_s': elevatorWaitTimeoutSeconds,
    'task_execution_timeout_s': taskExecutionTimeoutSeconds,
    'monitor_nodes': monitorNodes,
    'dependency_plan': dependencyPlan.toJson(),
    'live_observation': liveObservation.toJson(),
  };
}

class DependencyPlan {
  const DependencyPlan({required this.enabled, required this.steps});

  factory DependencyPlan.fromJson(Map<String, dynamic> json) => DependencyPlan(
    enabled: json['enabled'] == true,
    steps: (json['steps'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map((item) => DependencyStep.fromJson(_map(item)))
        .toList(growable: false),
  );

  final bool enabled;
  final List<DependencyStep> steps;

  Map<String, dynamic> toJson() => {
    'enabled': enabled,
    'steps': steps.map((item) => item.toJson()).toList(growable: false),
  };
}

class DependencyStep {
  const DependencyStep({required this.nodes, required this.waitSeconds});

  factory DependencyStep.fromJson(Map<String, dynamic> json) => DependencyStep(
    nodes: (json['nodes'] as List<Object?>? ?? const [])
        .whereType<String>()
        .toList(growable: false),
    waitSeconds: _number(json['wait_seconds']),
  );

  final List<String> nodes;
  final int waitSeconds;

  Map<String, dynamic> toJson() => {
    'nodes': nodes,
    'wait_seconds': waitSeconds,
  };
}

class SupervisorProcess {
  const SupervisorProcess({required this.name, required this.status});

  factory SupervisorProcess.fromJson(Map<String, dynamic> json) =>
      SupervisorProcess(
        name: _text(json['name']),
        status: _text(json['status']),
      );

  final String name;
  final String status;
}

class LiveObservationSettings {
  const LiveObservationSettings({
    required this.enabled,
    required this.idleStopSeconds,
    required this.vehicleModels,
    required this.activeVehicleModel,
  });

  factory LiveObservationSettings.fromJson(Map<String, dynamic> json) =>
      LiveObservationSettings(
        enabled: json['enabled'] == true,
        idleStopSeconds: _number(json['idle_stop_seconds'], fallback: 45),
        vehicleModels: (json['vehicle_models'] as List<Object?>? ?? const [])
            .whereType<Map>()
            .map((item) => VehicleModel.fromJson(_map(item)))
            .toList(growable: false),
        activeVehicleModel: _text(json['active_vehicle_model']),
      );

  final bool enabled;
  final int idleStopSeconds;
  final List<VehicleModel> vehicleModels;
  final String activeVehicleModel;

  Map<String, dynamic> toJson() => {
    'enabled': enabled,
    'idle_stop_seconds': idleStopSeconds,
    'vehicle_models': vehicleModels
        .map((item) => item.toJson())
        .toList(growable: false),
    'active_vehicle_model': activeVehicleModel,
  };
}

class VehicleModel {
  const VehicleModel({
    required this.id,
    required this.name,
    required this.lengthMetres,
    required this.widthMetres,
  });

  factory VehicleModel.fromJson(Map<String, dynamic> json) => VehicleModel(
    id: _text(json['id']),
    name: _text(json['name']),
    lengthMetres: _decimal(json['length_m']),
    widthMetres: _decimal(json['width_m']),
  );

  final String id;
  final String name;
  final double lengthMetres;
  final double widthMetres;

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'length_m': lengthMetres,
    'width_m': widthMetres,
  };
}

String _text(Object? value) => value is String ? value : '';
int _number(Object? value, {int fallback = 0}) =>
    value is num ? value.toInt() : fallback;
double _decimal(Object? value) => value is num ? value.toDouble() : 0;
Map<String, dynamic> _map(Object? value) => value is Map
    ? value.map((key, item) => MapEntry(key.toString(), item))
    : const {};
