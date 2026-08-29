class ScenarioSetupStatus {
  const ScenarioSetupStatus({
    required this.document,
    required this.inspection,
    required this.activeBackup,
  });

  factory ScenarioSetupStatus.fromJson(Map<String, dynamic> json) =>
      ScenarioSetupStatus(
        document: ScenarioDocument.fromJson(_map(json['document'])),
        inspection: ScenarioInspection.fromJson(_map(json['inspection'])),
        activeBackup: json['active_backup'] is Map
            ? ScenarioBackup.fromJson(_map(json['active_backup']))
            : null,
      );

  final ScenarioDocument document;
  final ScenarioInspection inspection;
  final ScenarioBackup? activeBackup;
}

class ScenarioDocument {
  const ScenarioDocument({
    required this.startupScript,
    required this.searchDirectories,
    required this.bindings,
    required this.profiles,
    required this.caseBindings,
  });

  factory ScenarioDocument.fromJson(Map<String, dynamic> json) =>
      ScenarioDocument(
        startupScript: _text(json['startup_script']),
        searchDirectories:
            (json['search_directories'] as List<Object?>? ?? const [])
                .whereType<String>()
                .toList(growable: false),
        bindings: _map(json['bindings']),
        profiles: (json['profiles'] as List<Object?>? ?? const [])
            .whereType<Map>()
            .map((item) => ScenarioProfile.fromJson(_map(item)))
            .toList(growable: false),
        caseBindings: _map(json['case_bindings']),
      );

  final String startupScript;
  final List<String> searchDirectories;
  final Map<String, dynamic> bindings;
  final List<ScenarioProfile> profiles;
  final Map<String, dynamic> caseBindings;

  Map<String, dynamic> toJson() => {
    'startup_script': startupScript,
    'search_directories': searchDirectories,
    'bindings': bindings,
    'profiles': profiles.map((item) => item.toJson()).toList(growable: false),
    'case_bindings': caseBindings,
  };
}

class ScenarioProfile {
  const ScenarioProfile({
    required this.id,
    required this.name,
    required this.fcrpLaunch,
    required this.lightningConfig,
  });

  factory ScenarioProfile.fromJson(Map<String, dynamic> json) =>
      ScenarioProfile(
        id: _text(json['id']),
        name: _text(json['name']),
        fcrpLaunch: _text(json['fcrp_launch']),
        lightningConfig: _text(json['lightning_config']),
      );

  final String id;
  final String name;
  final String fcrpLaunch;
  final String lightningConfig;

  ScenarioProfile copyWith({
    String? id,
    String? name,
    String? fcrpLaunch,
    String? lightningConfig,
  }) => ScenarioProfile(
    id: id ?? this.id,
    name: name ?? this.name,
    fcrpLaunch: fcrpLaunch ?? this.fcrpLaunch,
    lightningConfig: lightningConfig ?? this.lightningConfig,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'fcrp_launch': fcrpLaunch,
    'lightning_config': lightningConfig,
  };
}

class ScenarioInspection {
  const ScenarioInspection({
    required this.path,
    required this.exists,
    required this.writable,
  });
  factory ScenarioInspection.fromJson(Map<String, dynamic> json) =>
      ScenarioInspection(
        path: _text(json['path']),
        exists: json['exists'] == true,
        writable: json['writable'] == true,
      );
  final String path;
  final bool exists;
  final bool writable;
}

class ScenarioBackup {
  const ScenarioBackup({required this.profileName, required this.createdAt});
  factory ScenarioBackup.fromJson(Map<String, dynamic> json) => ScenarioBackup(
    profileName: _text(json['profile_name']),
    createdAt: _text(json['created_at']),
  );
  final String profileName;
  final String createdAt;
}

class ScenarioFileBrowser {
  const ScenarioFileBrowser({
    required this.path,
    required this.parent,
    required this.directories,
    required this.files,
  });
  factory ScenarioFileBrowser.fromJson(
    Map<String, dynamic> json,
  ) => ScenarioFileBrowser(
    path: _text(json['path']),
    parent: json['parent'] is String ? json['parent'] as String : null,
    directories: (json['directories'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map((item) => ScenarioFileEntry.fromJson(_map(item), directory: true))
        .toList(growable: false),
    files: (json['files'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map((item) => ScenarioFileEntry.fromJson(_map(item), directory: false))
        .toList(growable: false),
  );
  final String path;
  final String? parent;
  final List<ScenarioFileEntry> directories;
  final List<ScenarioFileEntry> files;
}

class ScenarioFileEntry {
  const ScenarioFileEntry({
    required this.name,
    required this.path,
    required this.isDirectory,
    this.size,
  });
  factory ScenarioFileEntry.fromJson(
    Map<String, dynamic> json, {
    required bool directory,
  }) => ScenarioFileEntry(
    name: _text(json['name']),
    path: _text(json['path']),
    isDirectory: directory,
    size: json['size'] is num ? (json['size'] as num).toInt() : null,
  );
  final String name;
  final String path;
  final bool isDirectory;
  final int? size;
}

/// A server-validated text file from the scenario setup's constrained root.
/// This is intentionally preview-only: selecting it still requires the
/// operator to save and explicitly apply a guarded scenario profile.
class ScenarioFilePreview {
  const ScenarioFilePreview({
    required this.path,
    required this.content,
    required this.size,
    required this.sha256,
  });

  factory ScenarioFilePreview.fromJson(Map<String, dynamic> json) =>
      ScenarioFilePreview(
        path: _text(json['path']),
        content: _text(json['content']),
        size: json['size'] is num ? (json['size'] as num).toInt() : 0,
        sha256: _text(json['sha256']),
      );

  final String path;
  final String content;
  final int size;
  final String sha256;
}

class ScenarioPreview {
  const ScenarioPreview({
    required this.path,
    required this.content,
    required this.changed,
    required this.profileName,
  });
  factory ScenarioPreview.fromJson(Map<String, dynamic> json) =>
      ScenarioPreview(
        path: _text(json['path']),
        content: _text(json['content']),
        changed: json['changed'] == true,
        profileName: _text(json['profile_name']),
      );
  final String path;
  final String content;
  final bool changed;
  final String profileName;
}

String _text(Object? value) => value is String ? value : '';
Map<String, dynamic> _map(Object? value) => value is Map
    ? value.map((key, item) => MapEntry(key.toString(), item))
    : const {};
