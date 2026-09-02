import 'observation_status.dart';
import 'robot_endpoint.dart';

enum ConnectionPhase { restoring, idle, checking, connected, failure }

class RobotConnectionState {
  const RobotConnectionState({
    this.phase = ConnectionPhase.restoring,
    this.endpoint,
    this.observation,
    this.message = '',
    this.lastChecked,
    this.isStartingObservation = false,
    this.addressDraft = '',
  });

  final ConnectionPhase phase;
  final RobotEndpoint? endpoint;
  final ObservationStatus? observation;
  final String message;
  final DateTime? lastChecked;
  final bool isStartingObservation;

  /// Local input state survives a root-tab change. It never changes robot
  /// configuration; it only avoids discarding an operator's address draft.
  final String addressDraft;

  bool get isBusy =>
      phase == ConnectionPhase.restoring ||
      phase == ConnectionPhase.checking ||
      isStartingObservation;

  bool get isConnected => phase == ConnectionPhase.connected;

  RobotConnectionState copyWith({
    ConnectionPhase? phase,
    RobotEndpoint? endpoint,
    ObservationStatus? observation,
    String? message,
    DateTime? lastChecked,
    bool? isStartingObservation,
    String? addressDraft,
  }) {
    return RobotConnectionState(
      phase: phase ?? this.phase,
      endpoint: endpoint ?? this.endpoint,
      observation: observation ?? this.observation,
      message: message ?? this.message,
      lastChecked: lastChecked ?? this.lastChecked,
      isStartingObservation:
          isStartingObservation ?? this.isStartingObservation,
      addressDraft: addressDraft ?? this.addressDraft,
    );
  }
}
