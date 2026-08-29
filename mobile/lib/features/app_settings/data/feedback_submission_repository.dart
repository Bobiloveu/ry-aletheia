import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../domain/feedback_draft.dart';

/// Boundary reserved for a future, reviewed feedback backend.
///
/// A remote implementation must obtain explicit user consent and upload only
/// the [FeedbackDraft] fields selected on the form. It must never append robot
/// traffic, map/video evidence or diagnostics not visible to the operator.
abstract interface class FeedbackSubmissionRepository {
  Future<FeedbackSubmissionResult> submit({
    required FeedbackDraft draft,
    AppFeedbackDiagnostics? diagnostics,
  });
}

class FeedbackSubmissionResult {
  const FeedbackSubmissionResult.developmentOnly();

  /// This app build validates the draft but performs no I/O or persistence.
  bool get wasUploaded => false;
}

/// Development-only transport. It intentionally has no HTTP client and does
/// not retain the submitted text, contact details or attachment paths.
class DevelopmentFeedbackSubmissionRepository
    implements FeedbackSubmissionRepository {
  @override
  Future<FeedbackSubmissionResult> submit({
    required FeedbackDraft draft,
    AppFeedbackDiagnostics? diagnostics,
  }) async => const FeedbackSubmissionResult.developmentOnly();
}

final feedbackSubmissionRepositoryProvider =
    Provider<FeedbackSubmissionRepository>(
      (ref) => DevelopmentFeedbackSubmissionRepository(),
    );
