#
# Aletheia visualization plugin — iOS.
#
# The embedded Unity runtime (`UnityFramework.framework` + `Data`) is a
# generated artefact from "Build → iOS" in `unity/aletheia_viz` (see
# unity/README.md). It is not committed.
#
# Until it is built and dropped into `ios/UnityLibrary/`, leave
# ALETHEIA_UNITY_ENABLED unset: the plugin compiles a stub surface and the app
# uses the Flutter renderer. The flag is deliberately a CocoaPods environment
# setting, rather than a Dart define, because Unity only supplies an iPhoneOS
# framework and normal simulator builds must remain available.
#
Pod::Spec.new do |s|
  unity_enabled = ENV['ALETHEIA_UNITY_ENABLED'] == '1'
  pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'GCC_C_LANGUAGE_STANDARD' => 'c11',
  }
  s.name             = 'aletheia_visualization'
  s.version          = '0.1.0'
  s.summary          = 'Embedded Unity renderer transport for the Aletheia HMI.'
  s.description      = <<-DESC
Renderer-only bridge: forwards map, camera, pose and a native point-cloud
buffer to an embedded Unity instance. Never touches ROS2, backend, tasks or
video.
                       DESC
  s.homepage         = 'https://ryaletheia.local'
  s.license          = { :type => 'Proprietary' }
  s.author           = { 'Aletheia' => 'dev@ryaletheia.local' }
  s.source           = { :path => '.' }

  # The plugin framework is embedded once by CocoaPods and is loaded before
  # the Unity surface is created. Compile the bridge here so Swift, Dart FFI
  # and Unity resolve one process-wide staging buffer from the same image.
  # An iOS app executable does not publish a stable dynamic export table for a
  # sibling framework, which made the former Runner-hosted bridge jump to a
  # null lazy binding in release IPAs.
  s.source_files = 'Classes/**/*'
  # CocoaPods only adds headers under the pod source root to the generated
  # umbrella header. The forwarding header makes the shared C bridge visible
  # to the plugin's Swift sources.
  s.public_header_files = 'Classes/AletheiaVisualizationBridge.h'
  s.preserve_paths = '../shared/**/*'
  s.dependency 'Flutter'
  s.platform = :ios, '13.0'
  s.swift_version = '5.0'

  # The Unity framework resolves the loaded plugin framework by its @rpath
  # install name. It is an opt-in, device-only integration: omitting the
  # environment variable means no iPhoneOS framework is linked, so the iOS
  # simulator remains on the permanent Flutter renderer path.
  if unity_enabled
    s.vendored_frameworks = 'UnityLibrary/UnityFramework.framework'
    s.resources = 'UnityLibrary/Data'
    pod_target_xcconfig['GCC_PREPROCESSOR_DEFINITIONS'] =
      '$(inherited) ALETHEIA_UNITY_ENABLED=1'
    # `#if ALETHEIA_UNITY_ENABLED` in the Swift platform-view adapter is a
    # Swift compilation condition, not a C preprocessor macro.  Without this
    # setting CocoaPods built only the adapter's stub branch even though the
    # Unity framework was embedded in Runner.
    pod_target_xcconfig['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] =
      '$(inherited) ALETHEIA_UNITY_ENABLED'
  end

  s.pod_target_xcconfig = pod_target_xcconfig
end
