import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../application/app_preferences_controller.dart';
import '../data/app_diagnostic_log.dart';
import '../data/feedback_submission_repository.dart';
import '../domain/app_preferences.dart';
import '../domain/feedback_draft.dart';

class AppFeedbackScreen extends ConsumerStatefulWidget {
  const AppFeedbackScreen({
    this.initialDraft,
    this.initialScrollOffset = 0,
    super.key,
  });

  static const routePath = '/settings/feedback';

  /// Used only by the Debug UI Gallery to inspect populated form states.
  final FeedbackDraft? initialDraft;
  final double initialScrollOffset;

  @override
  ConsumerState<AppFeedbackScreen> createState() => _AppFeedbackScreenState();
}

class _AppFeedbackScreenState extends ConsumerState<AppFeedbackScreen> {
  static const _maxAttachments = 3;
  static const _maxAttachmentSize = 8 * 1024 * 1024;
  static const _version = String.fromEnvironment(
    'FLUTTER_BUILD_NAME',
    defaultValue: '1.0.0',
  );
  static const _build = String.fromEnvironment(
    'FLUTTER_BUILD_NUMBER',
    defaultValue: '1',
  );

  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _summaryController;
  late final TextEditingController _detailsController;
  late final TextEditingController _contactController;
  late final ScrollController _scrollController;
  late FeedbackKind _kind;
  late bool _includeDiagnostics;
  late List<FeedbackAttachment> _attachments;
  var _submitting = false;

  @override
  void initState() {
    super.initState();
    final draft = widget.initialDraft;
    _summaryController = TextEditingController(text: draft?.summary ?? '');
    _detailsController = TextEditingController(text: draft?.details ?? '');
    _contactController = TextEditingController(text: draft?.contact ?? '');
    _kind = draft?.kind ?? FeedbackKind.issue;
    _includeDiagnostics = draft?.includeDiagnostics ?? true;
    _attachments = [...?draft?.attachments];
    _scrollController = ScrollController(
      initialScrollOffset: widget.initialScrollOffset,
    );
    ref.read(appDiagnosticLogProvider).record('feedback_opened');
  }

  @override
  void dispose() {
    _summaryController.dispose();
    _detailsController.dispose();
    _contactController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final preferences = ref.watch(appPreferencesControllerProvider);
    final copy = _FeedbackCopy(
      english: preferences.language == AppLanguage.english,
    );
    return SafeArea(
      top: false,
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          controller: _scrollController,
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 680),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    copy.title,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  SizedBox(height: 6),
                  Text(
                    copy.subtitle,
                    style: TextStyle(
                      color: AletheiaTheme.textSecondary,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 24),
                  _FeedbackSection(
                    label: copy.feedbackLabel,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(copy.kindLabel, style: _fieldLabelStyle),
                        const SizedBox(height: 8),
                        SegmentedButton<FeedbackKind>(
                          segments: [
                            ButtonSegment(
                              value: FeedbackKind.issue,
                              icon: const Icon(Icons.bug_report_outlined),
                              label: Text(copy.issue),
                            ),
                            ButtonSegment(
                              value: FeedbackKind.suggestion,
                              icon: const Icon(Icons.lightbulb_outline),
                              label: Text(copy.suggestion),
                            ),
                          ],
                          selected: {_kind},
                          onSelectionChanged: (selection) =>
                              setState(() => _kind = selection.single),
                        ),
                        const SizedBox(height: 18),
                        _FeedbackField(
                          controller: _summaryController,
                          label: copy.summaryLabel,
                          hint: copy.summaryHint,
                          validator: (value) =>
                              (value == null || value.trim().isEmpty)
                              ? copy.summaryRequired
                              : null,
                        ),
                        const SizedBox(height: 16),
                        _FeedbackField(
                          controller: _detailsController,
                          label: copy.detailsLabel,
                          hint: copy.detailsHint,
                          minLines: 5,
                          maxLines: 8,
                          validator: (value) =>
                              (value == null || value.trim().isEmpty)
                              ? copy.detailsRequired
                              : null,
                        ),
                        const SizedBox(height: 16),
                        _FeedbackField(
                          controller: _contactController,
                          label: copy.contactLabel,
                          hint: copy.contactHint,
                          keyboardType: TextInputType.emailAddress,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  _FeedbackSection(
                    label: copy.attachmentsLabel,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          copy.attachmentHint,
                          style: TextStyle(
                            color: AletheiaTheme.textSecondary,
                            height: 1.4,
                          ),
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          onPressed: _attachments.length >= _maxAttachments
                              ? null
                              : () => _pickScreenshots(copy),
                          icon: const Icon(Icons.add_photo_alternate_outlined),
                          label: Text(copy.selectScreenshots),
                        ),
                        if (_attachments.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          for (final attachment in _attachments)
                            _AttachmentRow(
                              attachment: attachment,
                              onRemove: () => setState(
                                () => _attachments.remove(attachment),
                              ),
                              removeLabel: copy.removeScreenshot,
                            ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: 18),
                  _FeedbackSection(
                    label: copy.diagnosticsLabel,
                    child: SwitchListTile.adaptive(
                      contentPadding: EdgeInsets.zero,
                      value: _includeDiagnostics,
                      activeTrackColor: AletheiaTheme.cyan,
                      title: Text(copy.includeDiagnostics),
                      subtitle: Text(copy.diagnosticsDetail),
                      onChanged: (value) =>
                          setState(() => _includeDiagnostics = value),
                    ),
                  ),
                  SizedBox(height: 18),
                  Text(
                    copy.privacyNote,
                    style: TextStyle(
                      color: AletheiaTheme.textTertiary,
                      fontSize: 12,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _submitting
                          ? null
                          : () => _submit(copy, preferences),
                      icon: _submitting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.send_outlined),
                      label: Text(_submitting ? copy.submitting : copy.submit),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _pickScreenshots(_FeedbackCopy copy) async {
    final selected = await FilePicker.platform.pickFiles(
      type: FileType.image,
      allowMultiple: true,
      withData: false,
    );
    if (!mounted || selected == null) return;
    final remaining = _maxAttachments - _attachments.length;
    final eligible = selected.files
        .where((file) => file.size > 0 && file.size <= _maxAttachmentSize)
        .take(remaining)
        .map(
          (file) => FeedbackAttachment(
            name: file.name,
            sizeBytes: file.size,
            sourcePath: file.path,
          ),
        )
        .toList(growable: false);
    if (eligible.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.invalidAttachment)));
      return;
    }
    setState(() => _attachments = [..._attachments, ...eligible]);
    if (eligible.length != selected.files.length) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(copy.attachmentLimit)));
    }
  }

  Future<void> _submit(_FeedbackCopy copy, AppPreferences preferences) async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _submitting = true);
    final diagnostics = _includeDiagnostics
        ? AppFeedbackDiagnostics(
            appVersion: 'Aletheia $_version ($_build)',
            platform: _platformLabel(),
            language: preferences.language.name,
            theme: preferences.theme.name,
            sessionEvents: ref.read(appDiagnosticLogProvider).snapshot(),
          )
        : null;
    try {
      await ref
          .read(feedbackSubmissionRepositoryProvider)
          .submit(
            draft: FeedbackDraft(
              kind: _kind,
              summary: _summaryController.text.trim(),
              details: _detailsController.text.trim(),
              contact: _contactController.text.trim(),
              attachments: _attachments,
              includeDiagnostics: _includeDiagnostics,
            ),
            diagnostics: diagnostics,
          );
      ref.read(appDiagnosticLogProvider).record('feedback_validated');
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(copy.developmentSubmitted)));
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  static String _platformLabel() {
    if (kIsWeb) return 'Web';
    return switch (Platform.operatingSystem) {
      'ios' => 'iOS',
      'android' => 'Android',
      final value => value,
    };
  }
}

final _fieldLabelStyle = TextStyle(
  color: AletheiaTheme.textSecondary,
  fontSize: 13,
  fontWeight: FontWeight.w600,
);

class _FeedbackSection extends StatelessWidget {
  const _FeedbackSection({required this.label, required this.child});
  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(
        padding: EdgeInsets.only(left: 4, bottom: 8),
        child: Text(
          label,
          style: TextStyle(
            color: AletheiaTheme.textTertiary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      Material(
        color: AletheiaTheme.surface,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: AletheiaTheme.border),
          borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
        ),
        clipBehavior: Clip.antiAlias,
        child: Padding(padding: const EdgeInsets.all(16), child: child),
      ),
    ],
  );
}

class _FeedbackField extends StatelessWidget {
  const _FeedbackField({
    required this.controller,
    required this.label,
    required this.hint,
    this.validator,
    this.minLines = 1,
    this.maxLines = 1,
    this.keyboardType,
  });

  final TextEditingController controller;
  final String label;
  final String hint;
  final String? Function(String?)? validator;
  final int minLines;
  final int maxLines;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: _fieldLabelStyle),
      const SizedBox(height: 7),
      TextFormField(
        controller: controller,
        validator: validator,
        minLines: minLines,
        maxLines: maxLines,
        keyboardType: keyboardType,
        textInputAction: maxLines > 1
            ? TextInputAction.newline
            : TextInputAction.next,
        decoration: InputDecoration(hintText: hint),
      ),
    ],
  );
}

class _AttachmentRow extends StatelessWidget {
  const _AttachmentRow({
    required this.attachment,
    required this.onRemove,
    required this.removeLabel,
  });

  final FeedbackAttachment attachment;
  final VoidCallback onRemove;
  final String removeLabel;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.only(bottom: 8),
    child: DecoratedBox(
      decoration: BoxDecoration(
        color: AletheiaTheme.surfaceRaised,
        borderRadius: BorderRadius.circular(AletheiaTheme.controlRadius),
      ),
      child: Padding(
        padding: EdgeInsets.only(left: 12, right: 4, top: 6, bottom: 6),
        child: Row(
          children: [
            Icon(Icons.image_outlined, color: AletheiaTheme.cyan, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                '${attachment.name}  ${_formatSize(attachment.sizeBytes)}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(
              tooltip: removeLabel,
              onPressed: onRemove,
              icon: const Icon(Icons.close_rounded),
            ),
          ],
        ),
      ),
    ),
  );

  static String _formatSize(int bytes) {
    if (bytes < 1024 * 1024) return '${(bytes / 1024).round()} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}

class _FeedbackCopy {
  const _FeedbackCopy({required this.english});
  final bool english;

  String get title => english ? 'Feedback' : '问题与建议';
  String get subtitle => english
      ? 'Tell us what happened or what would help. This development build does not upload submissions.'
      : '请描述遇到的问题或改进建议。当前开发版本不会上传提交内容。';
  String get feedbackLabel => english ? 'Feedback' : '反馈内容';
  String get kindLabel => english ? 'Type' : '反馈类型';
  String get issue => english ? 'Problem' : '问题';
  String get suggestion => english ? 'Suggestion' : '建议';
  String get summaryLabel => english ? 'Summary' : '简要说明';
  String get summaryHint => english
      ? 'For example, map controls overlap in landscape.'
      : '例如：横屏时地图控制区重叠。';
  String get summaryRequired => english ? 'Enter a short summary.' : '请填写简要说明。';
  String get detailsLabel => english ? 'Details' : '详细描述';
  String get detailsHint => english
      ? 'What happened, what did you expect, and how can we reproduce it?'
      : '发生了什么、预期是什么，以及如何复现？';
  String get detailsRequired => english ? 'Enter details.' : '请填写详细描述。';
  String get contactLabel => english ? 'Contact (optional)' : '联系方式（选填）';
  String get contactHint => english
      ? 'Email, phone number, or another contact method'
      : '邮箱、电话或其他可联系的方式';
  String get attachmentsLabel => english ? 'Screenshots' : '截图';
  String get attachmentHint => english
      ? 'Optional. Select up to 3 screenshots, each no larger than 8 MB.'
      : '可选。最多选择 3 张截图，单张不超过 8 MB。';
  String get selectScreenshots => english ? 'Choose screenshots' : '选择截图';
  String get removeScreenshot => english ? 'Remove screenshot' : '移除截图';
  String get invalidAttachment =>
      english ? 'Choose an image no larger than 8 MB.' : '请选择不超过 8 MB 的图片。';
  String get attachmentLimit => english
      ? 'Only the first available screenshots were added.'
      : '仅添加了数量和大小范围内的截图。';
  String get diagnosticsLabel => english ? 'App diagnostics' : 'App 诊断摘要';
  String get includeDiagnostics =>
      english ? 'Attach app diagnostics and session log' : '附加 App 诊断摘要与会话日志';
  String get diagnosticsDetail => english
      ? 'Current app session events, version, platform, language, and theme.'
      : '包含当前 App 会话事件、版本、平台、语言和主题。';
  String get privacyNote => english
      ? 'Robot address, map, video, and robot logs are never added to this form. Submission is local validation only during development.'
      : '不会附加机器人地址、地图、视频或车端日志。开发阶段仅进行本地校验，不上传也不保存内容。';
  String get submit => english ? 'Submit feedback' : '提交反馈';
  String get submitting => english ? 'Preparing feedback' : '正在准备反馈';
  String get developmentSubmitted => english
      ? 'Feedback was validated. This development build did not upload or save any content.'
      : '反馈已完成本地校验。当前开发版本未上传或保存任何内容。';
}
