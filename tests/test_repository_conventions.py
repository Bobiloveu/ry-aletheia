import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_logical_modules_keep_real_source_locations() -> None:
    assert (ROOT / "web_console.py").is_file()
    assert (ROOT / "autodrive_console").is_dir()
    assert (ROOT / "frontend" / "package.json").is_file()
    assert (ROOT / "mobile" / "pubspec.yaml").is_file()
    assert (ROOT / "live_preprocessor" / "CMakeLists.txt").is_file()
    assert (ROOT / "apps" / "README.md").is_file()


def test_mobile_docs_use_fvm_and_keep_platform_locks() -> None:
    readme = (ROOT / "mobile" / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / "mobile" / "docs" / "DEVELOPMENT_WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    fvmrc = json.loads((ROOT / "mobile" / ".fvmrc").read_text(encoding="utf-8"))
    assert fvmrc["flutter"] == "3.47.1"
    assert "fvm flutter pub get" in readme
    assert "fvm flutter analyze" in workflow
    assert (ROOT / "mobile" / "pubspec.lock").is_file()
    assert (ROOT / "mobile" / "ios" / "Podfile.lock").is_file()
    assert (
        ROOT
        / "mobile"
        / "ios"
        / "Runner.xcworkspace"
        / "xcshareddata"
        / "swiftpm"
        / "Package.resolved"
    ).is_file()
    assert ".fvm/" in (ROOT / "mobile" / ".gitignore").read_text(encoding="utf-8")


def test_runtime_reports_ignore_rule_does_not_hide_mobile_reports_source() -> None:
    root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "\n/reports/\n" in root_ignore
    assert "\nreports/\n" not in root_ignore
    assert (
        ROOT
        / "mobile"
        / "lib"
        / "features"
        / "reports"
        / "application"
        / "reports_controller.dart"
    ).is_file()


def test_doctor_detects_dart_global_fvm_outside_interactive_shells() -> None:
    doctor = (ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")

    assert '"$HOME/.pub-cache/bin/fvm"' in doctor


def test_development_doctors_expose_supported_profiles() -> None:
    doctor = (ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")

    assert "mobile-android" in doctor
    assert "mobile-ios" in doctor
    assert "UNSUPPORTED" in doctor
    assert (ROOT / "scripts" / "doctor.ps1").is_file()


def test_web_doctor_treats_pixi_as_required_without_optional_duplicate() -> None:
    if shutil.which("bash") is None:
        pytest.skip("Bash Doctor runtime check is not available on this host")
    result = subprocess.run(
        ["bash", "scripts/doctor.sh", "--profile", "web"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] Pixi" in result.stdout
    assert "[OPTIONAL] Pixi (not required by profile web)" not in result.stdout


def test_mobile_scripts_detect_dart_global_fvm_outside_interactive_shells() -> None:
    for script_name in ("bootstrap.sh", "test-mobile.sh", "build-mobile.sh"):
        script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert '"$HOME/.pub-cache/bin/fvm"' in script
    for script_name in ("test-mobile.sh", "build-mobile.sh"):
        script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "127.0.0.1,localhost,::1" in script


def test_contracts_mark_existing_and_document_realtime_lanes() -> None:
    control = (ROOT / "shared" / "contracts" / "robot_control.md").read_text(
        encoding="utf-8"
    )
    observation = (ROOT / "shared" / "contracts" / "realtime_observation.md").read_text(
        encoding="utf-8"
    )
    assert "Status: Existing" in control
    assert "/control_source_cmd" in control
    assert "/control_source_state" in control
    assert "/cmd_vel_miniapp" in control
    assert "Status: Existing" in observation
    assert "ALTM v1" in observation
    assert all(port in observation for port in ("8768", "8769", "8770"))


def test_robot_control_contract_contains_runtime_safety_rules() -> None:
    control = (ROOT / "shared" / "contracts" / "robot_control.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "navigation",
        "miniapp",
        "forward",
        "1.00",
        "heartbeat",
        "/api/vehicle-control/enter",
    ):
        assert required in control


def test_scripts_delegate_to_existing_tools() -> None:
    backend = (ROOT / "scripts" / "test-backend.sh").read_text(encoding="utf-8")
    web = (ROOT / "scripts" / "test-web.sh").read_text(encoding="utf-8")
    mobile = (ROOT / "scripts" / "test-mobile.sh").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build-mobile.sh").read_text(encoding="utf-8")
    assert "pixi run test" in backend
    assert "pixi run frontend-check" in web
    assert "fvm flutter analyze" in mobile
    assert "fvm flutter test" in mobile
    assert "--engine flutter" in build
    assert "--engine unity" not in build
    package_script = (ROOT / "mobile" / "tool" / "build_mobile_packages.sh").read_text(
        encoding="utf-8"
    )
    assert "ALETHEIA_USE_FVM" in package_script


def test_docs_and_agent_rules_link_real_modules() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for path in ("autodrive_console/AGENTS.md", "frontend/AGENTS.md", "mobile/AGENTS.md"):
        assert (ROOT / path).is_file(), path
    for section in ("architecture", "backend", "web", "mobile", "protocols", "deployment"):
        assert (ROOT / "docs" / section / "README.md").is_file(), section
    assert "shared/contracts" in agents
    assert "scripts/doctor.sh" in readme


def test_development_profile_document_is_linked_from_root_readme() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (ROOT / "docs" / "development" / "PROFILES.md").is_file()
    assert "docs/development/PROFILES.md" in readme


def test_ci_is_split_by_module_and_platform_and_excludes_unity_builds() -> None:
    workflow = (ROOT / ".github" / "workflows" / "module-checks.yml").read_text(
        encoding="utf-8"
    )
    for job in ("backend:", "web:", "mobile-common:", "android:", "ios:", "contracts:"):
        assert job in workflow
    for path in ("autodrive_console/**", "frontend/**", "mobile/**", "shared/contracts/**"):
        assert path in workflow
    assert "flutter analyze" in workflow
    assert "flutter test" in workflow
    assert "flutter build apk --debug" in workflow
    assert "flutter build ios --simulator --debug --no-codesign" in workflow
    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "unity" not in workflow.lower()


def test_ci_and_local_mobile_tests_use_serial_runner_for_shared_rendering_resources() -> None:
    workflow = (ROOT / ".github" / "workflows" / "module-checks.yml").read_text(
        encoding="utf-8"
    )
    mobile_test_script = (ROOT / "scripts" / "test-mobile.sh").read_text(
        encoding="utf-8"
    )

    assert "fvm flutter test --exclude-tags golden --concurrency=1 -r compact" in workflow
    assert "fvm flutter test --concurrency=1 -r compact" in mobile_test_script


def test_legacy_foxglove_release_entrypoint_is_absent() -> None:
    legacy_entrypoint = ROOT / "build_offline_foxglove_bundle.sh"
    overview = (ROOT / "PROJECT_OVERVIEW.md").read_text(encoding="utf-8")

    assert not legacy_entrypoint.exists()
    assert legacy_entrypoint.name not in overview


def test_ci_runs_macos_gallery_goldens_separately_from_linux_mobile_tests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "module-checks.yml").read_text(
        encoding="utf-8"
    )
    golden_test = (ROOT / "mobile" / "test" / "debug_ui" / "gallery_golden_test.dart").read_text(
        encoding="utf-8"
    )

    assert "@Tags(['golden'])" in golden_test
    assert "fvm flutter test --exclude-tags golden --concurrency=1 -r compact" in workflow
    assert "mobile-golden:" in workflow
    assert "fvm flutter test test/debug_ui/gallery_golden_test.dart --concurrency=1 -r compact" in workflow


def test_mobile_declares_the_golden_test_tag() -> None:
    test_config = (ROOT / "mobile" / "dart_test.yaml").read_text(encoding="utf-8")

    assert "tags:\n  golden:" in test_config
