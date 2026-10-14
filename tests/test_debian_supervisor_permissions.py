"""Exercise postinst's rule generator without installing or contacting Supervisor."""

import json
import os
import subprocess
from pathlib import Path

import pytest


POSTINST = Path(__file__).resolve().parents[1] / "packaging/debian/postinst"


def generate_rules(tmp_path, *, config=None, status="", status_exit=0):
    # Extract only the generator: no account discovery, visudo, system writes,
    # package installation, service management or real Supervisor invocation.
    source = POSTINST.read_text(encoding="utf-8")
    fragment = source.split("  SUPERVISOR_NODES=(", 1)[1].split(
        '  visudo -cf "$TEMP_SUDOERS"', 1
    )[0]
    fragment = "  SUPERVISOR_NODES=(" + fragment
    (tmp_path / "config").mkdir()
    if config is not None:
        (tmp_path / "config/console.json").write_text(json.dumps(config), encoding="utf-8")
    status_path = tmp_path / "status.txt"
    status_path.write_text(status, encoding="utf-8")
    supervisorctl = tmp_path / "fake-supervisorctl"
    supervisorctl.write_text(
        '#!/usr/bin/env bash\nset -eu\n'
        '[[ "$#" -eq 1 && "$1" == status ]] || exit 99\n'
        'cat "$FAKE_SUPERVISOR_STATUS"\nexit "$FAKE_SUPERVISOR_EXIT"\n',
        encoding="utf-8",
    )
    supervisorctl.chmod(0o755)
    output = tmp_path / "sudoers.txt"
    env = {
        "PATH": os.environ["PATH"],
        "ROOT": str(tmp_path),
        "RUN_USER": "test_operator",
        "SUPERVISORCTL": str(supervisorctl),
        "TEMP_SUDOERS": str(output),
        "FAKE_SUPERVISOR_STATUS": str(status_path),
        "FAKE_SUPERVISOR_EXIT": str(status_exit),
    }
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", fragment],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    rule = output.read_text(encoding="utf-8").strip()
    prefix = "test_operator ALL=(root) NOPASSWD: "
    assert rule.startswith(prefix)
    commands = rule[len(prefix):].split(", ")
    assert all(command.startswith(f"{supervisorctl} ") for command in commands)
    return [command[len(str(supervisorctl)) + 1:] for command in commands]


def test_status_discovery_grants_stdout_tail_without_start_or_restart(tmp_path):
    commands = generate_rules(
        tmp_path, config={}, status="DRIVERS:104-livox_lidar RUNNING pid 123, uptime 0:00:01\n"
    )

    assert r"tail -f DRIVERS\:104-livox_lidar stdout" in commands
    assert r"start DRIVERS\:104-livox_lidar" not in commands
    assert r"restart DRIVERS\:104-livox_lidar" not in commands


def test_existing_approved_nodes_keep_control_and_stdout_tail_without_status(tmp_path):
    commands = generate_rules(tmp_path, status_exit=4)

    assert "status" in commands
    for node in (
        r"DRIVERS\:102-chassis_node",
        r"DRIVERS\:111-elevator_server",
        r"MODULES\:209-lightning",
        r"MODULES\:211-navigate_todoor_server",
        r"MODULES\:212-task_execute_server",
        r"MODULES\:214-fcrp_bringup",
    ):
        assert f"start {node}" in commands
        assert f"restart {node}" in commands
        assert f"tail -f {node} stdout" in commands


def test_declared_configuration_sources_keep_exact_control_and_tail_rules(tmp_path):
    commands = generate_rules(
        tmp_path,
        config={
            "nodes": [{"supervisor": "ROBOT_B:localizer.v2"}],
            "monitor_nodes": ["monitor-node_1"],
            "dependency_plan": {"steps": [{"nodes": ["ROBOT_B:navigate_2"]}]},
        },
        status="ROBOT_B:localizer.v2 RUNNING pid 456, uptime 0:00:02\n" * 2,
    )

    for node in (r"ROBOT_B\:localizer.v2", "monitor-node_1", r"ROBOT_B\:navigate_2"):
        assert f"start {node}" in commands
        assert f"restart {node}" in commands
        assert f"tail -f {node} stdout" in commands
    assert len(commands) == len(set(commands))
    assert r"tail -f ROBOT_B:localizer.v2 stdout" not in commands


def test_invalid_names_cannot_enter_control_or_tail_rules(tmp_path):
    invalid = [
        "DRIVERS:*", "DRIVERS:bad,node", "DRIVERS:bad!node", "DRIVERS:bad=node",
        r"DRIVERS:bad\node", "DRIVERS:/bad", "DRIVERS:bad;node", "DRIVERS:bad#node",
        "DRIVERS:bad:node", "-option", ".hidden", "x" * 129, "G:" + "x" * 129,
    ]
    commands = generate_rules(
        tmp_path,
        config={
            "nodes": [{"supervisor": node} for node in invalid + ["bad node"]],
            "monitor_nodes": invalid,
            "dependency_plan": {"steps": [{"nodes": invalid}]},
        },
        status="".join(f"{node} RUNNING pid 123, uptime 0:00:01\n" for node in invalid),
    )

    # Exactly the six existing control nodes and their tails plus status.
    assert len(commands) == 19
    assert len(commands) == len(set(commands))


@pytest.mark.parametrize("source", ["nodes", "monitor_nodes", "dependency_plan"])
def test_config_values_are_validated_before_any_line_splitting(tmp_path, source):
    values = [
        "VALID:before_1",
        "unapproved_a\nunapproved_b",
        "unapproved_c\r\nunapproved_d",
        "unapproved_e\rnode",
        "unapproved_f\n",
        "\nunapproved_g",
        "unapproved_h\r",
        "unapproved_i\u2028node",
        "", None, 42, False, {}, [],
        "VALID:after-2.v3",
    ]
    if source == "nodes":
        config = {source: [{"supervisor": value} for value in values]}
    elif source == "monitor_nodes":
        config = {source: values}
    else:
        config = {source: {"steps": [{"nodes": values}]}}

    commands = generate_rules(tmp_path, config=config)

    # Only the six defaults and the two complete valid values are approved.
    assert len(commands) == 25
    for node in (r"VALID\:before_1", r"VALID\:after-2.v3"):
        assert f"start {node}" in commands
        assert f"restart {node}" in commands
        assert f"tail -f {node} stdout" in commands
    assert all("unapproved" not in command for command in commands)


def test_empty_config_arrays_keep_only_existing_approved_nodes(tmp_path):
    commands = generate_rules(
        tmp_path,
        config={"nodes": [], "monitor_nodes": [], "dependency_plan": {"steps": []}},
    )

    assert len(commands) == 19
    assert len(commands) == len(set(commands))


def test_config_accepts_full_length_valid_program_and_group_names(tmp_path):
    program = "P" * 128
    group = "G" * 128
    commands = generate_rules(
        tmp_path,
        config={"monitor_nodes": [program, f"{group}:{program}"]},
    )

    for node in (program, group + r"\:" + program):
        assert f"start {node}" in commands
        assert f"restart {node}" in commands
        assert f"tail -f {node} stdout" in commands
    assert len(commands) == 25
