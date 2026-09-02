[CmdletBinding()]
param(
  [ValidateSet('backend', 'web', 'mobile', 'mobile-android', 'mobile-ios', 'all', 'full')]
  [string]$Profile = 'full'
)

$ErrorActionPreference = 'Stop'
$script:Failures = 0

function Write-Status([string]$Status, [string]$Message) {
  Write-Output "[$Status] $Message"
  if ($Status -eq 'MISSING') { $script:Failures = 1 }
}

function Find-Command([string]$Name) {
  return Get-Command $Name -ErrorAction SilentlyContinue
}

function Needs([string]$Domain) {
  return $Profile -eq 'full' -or $Profile -eq $Domain
}

function Check-Pixi {
  $pixi = Find-Command 'pixi'
  if ($pixi) { Write-Status 'OK' "Pixi $(& $pixi.Source --version)" }
  else { Write-Status 'MISSING' 'Pixi; install Pixi before Backend/Web work' }
}

function Check-MobileCommon {
  $fvm = Find-Command 'fvm'
  if ($fvm) { Write-Status 'OK' "FVM $(& $fvm.Source --version)" }
  else { Write-Status 'MISSING' 'FVM; install with: dart pub global activate fvm 4.3.0' }

  $dart = Find-Command 'dart'
  if ($dart) { Write-Status 'OK' "Dart $((& $dart.Source --version 2>&1) | Select-Object -First 1)" }
  else { Write-Status 'MISSING' 'Dart SDK; required to install and run FVM' }

  $root = Split-Path -Parent $PSScriptRoot
  if (Test-Path (Join-Path $root 'mobile/.fvm/flutter_sdk/bin/flutter')) {
    Write-Status 'OK' 'FVM-pinned Flutter SDK installed'
  } else {
    Write-Status 'OPTIONAL' 'FVM-pinned Flutter SDK not installed yet; run fvm install in mobile/'
  }
}

function Check-Android {
  $java = Find-Command 'java'
  if ($java) {
    $versionText = ((& $java.Source -version 2>&1) | Select-Object -First 1).ToString()
    $match = [regex]::Match($versionText, 'version "(\d+)')
    if ($match.Success -and [int]$match.Groups[1].Value -ge 17) {
      Write-Status 'OK' "JDK $($match.Groups[1].Value) (CI baseline and project JVM target: 17)"
    } else {
      Write-Status 'MISSING' 'JDK 17 or newer; required for Android builds'
    }
  } else {
    Write-Status 'MISSING' 'JDK 17 or newer; required for Android builds'
  }

  $sdk = $env:ANDROID_SDK_ROOT
  if (-not $sdk) { $sdk = $env:ANDROID_HOME }
  if (-not $sdk -and $env:LOCALAPPDATA) {
    $candidate = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
    if (Test-Path $candidate) { $sdk = $candidate }
  }
  if ($sdk) { Write-Status 'OK' "Android SDK $sdk" }
  else { Write-Status 'MISSING' 'Android SDK; set ANDROID_SDK_ROOT or install Android Studio' }

  if (Find-Command 'adb') { Write-Status 'OK' 'adb available' }
  else { Write-Status 'OPTIONAL' 'adb; required only for physical-device debugging' }
}

function Check-Ios {
  if (-not $IsMacOS) {
    Write-Status 'UNSUPPORTED' 'iOS toolchain; iOS builds require macOS with Xcode'
    return
  }
  if (Find-Command 'xcodebuild') { Write-Status 'OK' 'Xcode available' }
  else { Write-Status 'MISSING' 'Xcode; required for iOS Simulator/device builds' }
  if (Find-Command 'pod') { Write-Status 'OK' 'CocoaPods available' }
  else { Write-Status 'MISSING' 'CocoaPods; required by the current iOS plugin dependencies' }
}

if ($Profile -eq 'mobile') { $Profile = 'mobile-android' }
if ($Profile -eq 'all') { $Profile = 'full' }
Write-Output "RY Aletheia doctor: profile=$Profile os=$([System.Environment]::OSVersion.Platform)"

if (Needs 'backend') { Check-Pixi } else { Write-Status 'OPTIONAL' "Pixi (not required by profile $Profile)" }
if (Needs 'web') { Check-Pixi } else { Write-Status 'OPTIONAL' "Pixi/Node Web toolchain (not required by profile $Profile)" }
if ((Needs 'mobile-android') -or (Needs 'mobile-ios')) { Check-MobileCommon }
if (Needs 'mobile-android') { Check-Android } else { Write-Status 'OPTIONAL' "Android SDK, JDK, and adb (not required by profile $Profile)" }
if (Needs 'mobile-ios') { Check-Ios } elseif ($IsMacOS) { Write-Status 'OPTIONAL' "Xcode and CocoaPods (not required by profile $Profile)" } else { Write-Status 'UNSUPPORTED' 'iOS toolchain; not available on this OS' }
if ($script:Failures -ne 0) { exit 2 }
