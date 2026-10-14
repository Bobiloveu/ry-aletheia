"""Exercise release entry selection without running a build or writing a release."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def release_fixture(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    for name in ("make_upgrade.sh", "build_binary.sh"):
        shutil.copy2(ROOT / name, root / name)
    helper = ROOT / "scripts/build-environment.sh"
    if helper.exists():
        (root / "scripts").mkdir()
        shutil.copy2(helper, root / "scripts/build-environment.sh")
    (root / "install").mkdir()
    (root / "install/setup.bash").write_text("")
    (root / "frontend/node_modules").mkdir(parents=True)
    (root / "config").mkdir()
    for profile in ("ros", "shm"):
        (root / f"config/video.{profile}.json").write_text("{}")
    (root / ".pixi/envs/default/bin").mkdir(parents=True)
    python = root / ".pixi/envs/default/bin/python3"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pixi = fake_bin / "pixi"
    pixi.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        "with open(os.environ['BUILD_ENTRY_CAPTURE'],'w') as f:\n"
        " json.dump({'args':sys.argv[1:],'cwd':os.getcwd()},f)\n"
    )
    pixi.chmod(0o755)
    # The unactivated system interpreter lacks the new reader dependencies.
    missing_python = fake_bin / "python3"
    missing_python.write_text("#!/bin/sh\nexit 31\n")
    missing_python.chmod(0o755)
    capture = tmp_path / "entry.json"
    env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin", "BUILD_ENTRY_CAPTURE": str(capture)}
    env.pop("PIXI_PROJECT_ROOT", None)
    return root, capture, env


@pytest.mark.parametrize("script,args", [
    ("make_upgrade.sh", ["2.7.6", "--shm", "--deb"]),
    ("build_binary.sh", []),
])
def test_release_entries_activate_existing_locked_environment_without_installing(tmp_path, script, args):
    root, capture, env = release_fixture(tmp_path)
    result = subprocess.run(["bash", str(root / script), *args], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    call = json.loads(capture.read_text())
    assert call["cwd"] == str(root)
    assert call["args"] == ["run", "--frozen", "--no-install", "--manifest-path", str(root / "pixi.toml"), "bash", str(root / script), *args]
    assert not (root / "releases").exists()
    assert not (root / "build").exists()


def test_already_activated_project_does_not_reexec_or_hide_missing_dependencies(tmp_path):
    root, capture, env = release_fixture(tmp_path)
    env["PIXI_PROJECT_ROOT"] = str(root)
    result = subprocess.run(["bash", str(root / "build_binary.sh")], cwd=root, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "PCD" in result.stderr
    assert not capture.exists()


@pytest.mark.parametrize("script", ["make_upgrade.sh", "build_binary.sh"])
def test_symlink_entry_uses_physical_project_root(tmp_path, script):
    root, capture, env = release_fixture(tmp_path)
    alias = tmp_path / "project alias"
    alias.symlink_to(root, target_is_directory=True)
    args = ["2.7.6", "--shm"] if script == "make_upgrade.sh" else []
    result = subprocess.run(["bash", str(alias / script), *args], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    call = json.loads(capture.read_text())
    assert call["args"] == ["run", "--frozen", "--no-install", "--manifest-path", str(root / "pixi.toml"), "bash", str(root / script), *args]


def test_symlink_entry_in_activated_project_does_not_reexec(tmp_path):
    root, capture, env = release_fixture(tmp_path)
    alias = tmp_path / "project alias"
    alias.symlink_to(root, target_is_directory=True)
    env["PIXI_PROJECT_ROOT"] = str(root)
    result = subprocess.run(["bash", str(alias / "build_binary.sh")], cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "PCD" in result.stderr
    assert not capture.exists()


def assert_binary_build_embeds_selected_video_profile_at_canonical_file_and_cleans_stage(
    tmp_path, profile, packager_exit,
):
    """Catches --add-data treating a desired filename as its target directory."""
    root, _, env = release_fixture(tmp_path)
    selected = root / f'config/video.{profile}.json'
    selected_bytes = ('{"profile":"'+profile+'","preserve":"exact bytes"}\n').encode()
    selected.write_bytes(selected_bytes)
    fake_bin = tmp_path / 'bin'
    capture = tmp_path / 'pyinstaller-call.json'
    fake_python = fake_bin / 'python3'
    fake_python.write_text(
        f'#!{sys.executable}\n'
        'import json,os,pathlib,sys\n'
        'if sys.argv[1:3] == ["-m","PyInstaller"]:\n'
        ' args=sys.argv[3:]; entries=[]\n'
        ' for i,arg in enumerate(args):\n'
        '  if arg != "--add-data": continue\n'
        '  source,destination=args[i+1].rsplit(":",1)\n'
        '  path=pathlib.Path(source)\n'
        '  if not path.is_file() or not destination.startswith("config"): continue\n'
        '  entries.append({"source":str(path),"destination":destination,\n'
        '   "packaged_path":str(pathlib.PurePosixPath(destination)/path.name),\n'
        '   "bytes":path.read_bytes().hex()})\n'
        ' workpath=args[args.index("--workpath")+1]\n'
        ' pathlib.Path(os.environ["BUILD_ARCHIVE_CAPTURE"]).write_text(json.dumps({\n'
        '  "entries":entries,"workpath":workpath,"workpath_exists":pathlib.Path(workpath).is_dir()}))\n'
        ' sys.exit(int(os.environ["BUILD_PACKAGER_EXIT"]))\n'
    )
    fake_python.chmod(0o755)
    for name in ('node', 'npm', 'cmake'):
        command = fake_bin / name
        command.write_text('#!/bin/sh\nexit 0\n')
        command.chmod(0o755)
    native = root / 'build/live_preprocessor'
    native.mkdir(parents=True)
    for name in ('aletheia_live_cloud', 'aletheia_video_ingest'):
        executable = native / name
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
    libraries = root / 'install/lib'
    libraries.mkdir()
    for name in ('tf2_msgs', 'nav2_msgs', 'sensor_msgs'):
        (libraries / f'lib{name}__rosidl_typesupport_c.so').write_bytes(b'fixture')
    runtime = root / 'private runtime'
    runtime.mkdir()
    (runtime / 'ry-aletheia-runtime.json').write_text('{}')
    env.update(PIXI_PROJECT_ROOT=str(root), RY_ALETHEIA_VIDEO_CONFIG=str(selected),
               ROVER_QA_ROS_SETUP=str(root / 'install/setup.bash'),
               RY_ALETHEIA_VIDEO_RUNTIME=str(runtime), BUILD_ARCHIVE_CAPTURE=str(capture),
               BUILD_PACKAGER_EXIT=str(packager_exit))
    result = subprocess.run(['bash', str(root / 'build_binary.sh')], cwd=root,
                            env=env, text=True, capture_output=True)
    assert result.returncode == packager_exit, result.stderr
    call = json.loads(capture.read_text())
    assert len(call['entries']) == 1
    entry = call['entries'][0]
    assert entry['packaged_path'] == 'config/video.json'
    assert entry['bytes'] == selected_bytes.hex()
    assert selected.read_bytes() == selected_bytes
    assert Path(entry['source']).name == 'video.json'
    assert not Path(entry['source']).parent.exists()
    assert call['workpath_exists'] and not Path(call['workpath']).exists()


@pytest.mark.parametrize('profile', ['ros', 'shm'])
@pytest.mark.parametrize('packager_exit', [0, 7])
def test_binary_build_embeds_selected_video_profile_at_canonical_file_and_cleans_stage(
    tmp_path, profile, packager_exit,
):
    assert_binary_build_embeds_selected_video_profile_at_canonical_file_and_cleans_stage(
        tmp_path, profile, packager_exit,
    )
