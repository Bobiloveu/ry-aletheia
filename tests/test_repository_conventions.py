from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_logical_modules_keep_real_source_locations() -> None:
    assert (ROOT / "web_console.py").is_file()
    assert (ROOT / "autodrive_console").is_dir()
    assert (ROOT / "frontend" / "package.json").is_file()
    assert (ROOT / "mobile" / "pubspec.yaml").is_file()
    assert (ROOT / "live_preprocessor" / "CMakeLists.txt").is_file()
    assert (ROOT / "apps" / "README.md").is_file()
