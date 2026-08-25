import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "packaging" / "debian" / "ry-aletheia-status"


class StatusCommandTests(unittest.TestCase):
    def _command(self, directory: Path, name: str, body: str) -> None:
        target = directory / name
        target.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)

    def test_once_uses_the_actual_web_listener_not_the_onefile_bootstrap_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp)
            self._command(
                fake_bin,
                "ss",
                'printf \'LISTEN 0 128 0.0.0.0:8087 0.0.0.0:* users:(("ry-aletheia",pid=222,fd=9))\\n\'',
            )
            self._command(
                fake_bin,
                "ps",
                '''if [[ "$*" == *"-p 222 -o args="* ]]; then
  printf "/home/ry/ry_aletheia/dist/ry-aletheia\\n"
elif [[ "$*" == *"-p 222 -o rss="* ]]; then
  printf "20480 4 00:02:00 /home/ry/ry_aletheia/dist/ry-aletheia\\n"
elif [[ "$*" == *"-p 222 -o %cpu="* ]]; then
  printf "3.0\\n"
else
  exit 0
fi''',
            )
            self._command(fake_bin, "pgrep", "exit 1")
            self._command(
                fake_bin,
                "curl",
                "printf '%s' '{\"enabled\":true,\"streams\":[{\"name\":\"left_camera\",\"enabled\":true,\"status\":\"waiting\"}]}'",
            )
            environment = os.environ | {"PATH": f"{fake_bin}:{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", str(SCRIPT), "--once"],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("工具状态:     运行中（8087 已监听）", result.stdout)
        self.assertIn("工具总 CPU:   3.0%  （/proc 不可用，ps 平均值）", result.stdout)
        self.assertIn("服务 PID:     222", result.stdout)
        self.assertIn("内存占用:     20.0 MiB", result.stdout)
        self.assertIn("left_camera", result.stdout)
        self.assertIn("等待 ROS 图像", result.stdout)

    def test_help_and_shell_syntax_are_valid(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, check=True)
        result = subprocess.run(["bash", str(SCRIPT), "--help"], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout, "用法：ry-aletheia-status [--once]\n")
        self.assertIn("执行 ry-aletheia 启动控制台", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
