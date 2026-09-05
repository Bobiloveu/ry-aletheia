import 'dart:math' as math;

enum VehicleCommand {
  forward('forward'),
  backward('backward'),
  left('left'),
  right('right');

  const VehicleCommand(this.wireName);

  final String wireName;
}

/// A normalized mobile motion request.
///
/// Positive [linearRatio] moves the vehicle forward. Positive [angularRatio]
/// turns it left. The backend owns conversion to physical speed and all safety
/// gates; this type only describes the user's continuous joystick intent.
class VehicleControlVector {
  const VehicleControlVector(this.linearRatio, this.angularRatio)
    : assert(linearRatio >= -1 && linearRatio <= 1),
      assert(angularRatio >= -1 && angularRatio <= 1);

  static const stop = VehicleControlVector(0, 0);

  factory VehicleControlVector.fromJoystick({
    required double horizontal,
    required double vertical,
    double deadZone = .18,
  }) {
    if (!horizontal.isFinite || !vertical.isFinite || !deadZone.isFinite) {
      return stop;
    }
    final x = horizontal.clamp(-1.0, 1.0).toDouble();
    final y = vertical.clamp(-1.0, 1.0).toDouble();
    if (math.sqrt(x * x + y * y) < deadZone.clamp(0.0, 1.0)) return stop;

    // Screen Y increases downwards. Right is a clockwise (negative) turn.
    return VehicleControlVector(y == 0 ? 0 : -y, x == 0 ? 0 : -x);
  }

  final double linearRatio;
  final double angularRatio;

  bool get isStop => linearRatio == 0 && angularRatio == 0;

  Map<String, double> toJson() => {
    'linear_ratio': linearRatio,
    'angular_ratio': angularRatio,
  };

  @override
  bool operator ==(Object other) =>
      other is VehicleControlVector &&
      linearRatio == other.linearRatio &&
      angularRatio == other.angularRatio;

  @override
  int get hashCode => Object.hash(linearRatio, angularRatio);
}

enum EmergencyStopState {
  normal('normal'),
  triggered('triggered'),
  unknown('unknown');

  const EmergencyStopState(this.wireName);

  final String wireName;

  static EmergencyStopState fromWire(Object? value) =>
      EmergencyStopState.values
          .where((state) => state.wireName == value)
          .firstOrNull ??
      EmergencyStopState.unknown;
}

enum EmergencyReleaseState {
  idle('idle'),
  waitingConfirmation('waiting_confirmation'),
  confirmed('confirmed'),
  failed('failed'),
  unconfirmable('unconfirmable');

  const EmergencyReleaseState(this.wireName);

  final String wireName;

  static EmergencyReleaseState fromWire(Object? value) =>
      EmergencyReleaseState.values
          .where((state) => state.wireName == value)
          .firstOrNull ??
      EmergencyReleaseState.idle;
}

class VehicleControlState {
  const VehicleControlState({
    required this.runtime,
    required this.runtimeError,
    required this.actualSource,
    required this.transition,
    required this.transitionError,
    required this.manualReady,
    required this.canBeginManual,
    required this.session,
    required this.speed,
    required this.emergency,
    required this.chassisParameters,
  });

  factory VehicleControlState.fromJson(Map<String, dynamic> json) {
    return VehicleControlState(
      runtime: _string(json['runtime'], fallback: 'unknown'),
      runtimeError: _string(json['runtime_error']),
      actualSource: _string(json['actual_source'], fallback: 'unknown'),
      transition: _nullableString(json['transition']),
      transitionError: _string(json['transition_error']),
      manualReady: json['manual_ready'] == true,
      canBeginManual: json['can_begin_manual'] == true,
      session: VehicleControlSession.fromJson(json['session']),
      speed: VehicleSpeed.fromJson(json['speed']),
      emergency: EmergencyStop.fromJson(json['emergency_stop']),
      chassisParameters: ChassisParameters.fromJson(json['chassis_parameters']),
    );
  }

  final String runtime;
  final String runtimeError;
  final String actualSource;
  final String? transition;
  final String transitionError;
  final bool manualReady;
  final bool canBeginManual;
  final VehicleControlSession session;
  final VehicleSpeed speed;
  final EmergencyStop emergency;
  final ChassisParameters chassisParameters;

  /// This only reflects the backend's latest safety gate. The Controller must
  /// also prove that it still owns the opaque session ID returned by enter.
  bool get motionPermittedByBackend =>
      manualReady && emergency.state == EmergencyStopState.normal;
}

class VehicleControlSession {
  const VehicleControlSession({
    required this.present,
    required this.state,
    required this.id,
  });

  factory VehicleControlSession.fromJson(Object? value) {
    final json = _map(value);
    return VehicleControlSession(
      present: json['present'] == true,
      state: _string(json['state'], fallback: 'none'),
      id: _nullableString(json['id']),
    );
  }

  final bool present;
  final String state;
  final String? id;
}

class VehicleSpeed {
  const VehicleSpeed({
    required this.linearMps,
    required this.angularRadps,
    required this.minimum,
    required this.maximum,
  });

  factory VehicleSpeed.fromJson(Object? value) {
    final json = _map(value);
    return VehicleSpeed(
      linearMps: _finiteDouble(json['linear_mps']),
      angularRadps: _finiteDouble(json['angular_radps']),
      minimum: _finiteDouble(json['min']),
      maximum: _finiteDouble(json['max']),
    );
  }

  final double linearMps;
  final double angularRadps;
  final double minimum;
  final double maximum;
}

class EmergencyStop {
  const EmergencyStop({required this.state, required this.release});

  factory EmergencyStop.fromJson(Object? value) {
    final json = _map(value);
    return EmergencyStop(
      state: EmergencyStopState.fromWire(json['state']),
      release: EmergencyReleaseState.fromWire(json['release']),
    );
  }

  final EmergencyStopState state;
  final EmergencyReleaseState release;
}

class ChassisParameters {
  const ChassisParameters({
    required this.press,
    required this.movementAcceleration,
    required this.stopAcceleration,
  });

  factory ChassisParameters.fromJson(Object? value) {
    final json = _map(value);
    return ChassisParameters(
      press: _finiteInteger(json['press']),
      movementAcceleration: _finiteInteger(json['movement_acc']),
      stopAcceleration: _finiteInteger(json['stop_acc']),
    );
  }

  final int press;
  final int movementAcceleration;
  final int stopAcceleration;

  Map<String, int> toJson() => {
    'press': press,
    'movement_acc': movementAcceleration,
    'stop_acc': stopAcceleration,
  };
}

Map<String, dynamic> _map(Object? value) {
  if (value is! Map) return const {};
  return value.map((key, item) => MapEntry(key.toString(), item));
}

String _string(Object? value, {String fallback = ''}) =>
    value is String ? value : fallback;

String? _nullableString(Object? value) =>
    value is String && value.isNotEmpty ? value : null;

double _finiteDouble(Object? value) =>
    value is num && value.isFinite ? value.toDouble() : 0;

int _finiteInteger(Object? value) =>
    value is num && value.isFinite ? value.toInt() : 0;
