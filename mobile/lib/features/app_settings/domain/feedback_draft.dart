/// The category selected by the operator before a feedback draft is handed to
/// the future submission transport.
enum FeedbackKind { issue, suggestion }

/// Metadata for a user-selected screenshot.
///
/// The local development transport intentionally never reads [sourcePath] or
/// sends it anywhere. It remains part of the future transport contract so a
/// reviewed upload implementation can attach exactly what the operator chose.
class FeedbackAttachment {
  const FeedbackAttachment({
    required this.name,
    required this.sizeBytes,
    this.sourcePath,
  });

  final String name;
  final int sizeBytes;
  final String? sourcePath;
}

/// Safe, app-local context that may accompany a feedback submission.
///
/// This deliberately excludes robot address, map/video data, ROS state,
/// vehicle logs and any data received from the robot.
class AppFeedbackDiagnostics {
  const AppFeedbackDiagnostics({
    required this.appVersion,
    required this.platform,
    required this.language,
    required this.theme,
    required this.sessionEvents,
  });

  final String appVersion;
  final String platform;
  final String language;
  final String theme;
  final List<String> sessionEvents;
}

/// A user-controlled feedback payload. It has no HTTP or persistence logic.
class FeedbackDraft {
  const FeedbackDraft({
    required this.kind,
    required this.summary,
    required this.details,
    required this.contact,
    required this.attachments,
    required this.includeDiagnostics,
  });

  final FeedbackKind kind;
  final String summary;
  final String details;
  final String contact;
  final List<FeedbackAttachment> attachments;
  final bool includeDiagnostics;

  /// Deterministic content for the Debug UI Gallery. It is never used by a
  /// production route and contains no robot data.
  static const gallery = FeedbackDraft(
    kind: FeedbackKind.issue,
    summary: '横屏地图显示需要调整',
    details: '切换横屏后，地图控制区覆盖了部分画面。',
    contact: 'operator@example.com',
    attachments: [
      FeedbackAttachment(name: 'map-landscape.png', sizeBytes: 482 * 1024),
    ],
    includeDiagnostics: true,
  );
}
