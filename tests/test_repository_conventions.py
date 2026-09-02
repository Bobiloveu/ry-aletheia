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
