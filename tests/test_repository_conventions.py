from pathlib import Path


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
    assert (ROOT / "mobile" / ".fvmrc").read_text(encoding="utf-8").strip() == "3.47.1"
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
