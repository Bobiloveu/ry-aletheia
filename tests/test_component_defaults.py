from __future__ import annotations

import json

import autodrive_console.component_defaults as defaults_module
from autodrive_console.component_defaults import component_speed_defaults, component_speed_profile


def test_access_component_speed_defaults_are_loaded_from_the_task_template_json():
    """Installers change one task-template JSON, never duplicated UI/backend constants."""
    defaults = component_speed_defaults()

    assert defaults["auto_door"] == {"speed_profile": "task_point", "locked": True}
    assert defaults["gate"] == {"speed_profile": "narrow_point", "locked": True}


def test_locked_access_component_speeds_override_stale_project_values():
    """A legacy UI selection must not change a controlled-device safety profile."""
    assert component_speed_profile("auto_door", "slow_point") == "task_point"
    assert component_speed_profile("gate", "single_point") == "narrow_point"


def test_component_speed_defaults_are_reloaded_when_the_template_json_changes(
    tmp_path, monkeypatch,
):
    config = tmp_path / "component-defaults.json"
    payload = {
        "schema": 1,
        "component_speed_defaults": {
            "auto_door": {"speed_profile": "task_point", "locked": True},
            "gate": {"speed_profile": "narrow_point", "locked": True},
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(defaults_module, "COMPONENT_DEFAULTS_PATH", config)

    assert defaults_module.component_speed_profile("auto_door", "slow_point") == "task_point"
    payload["component_speed_defaults"]["auto_door"]["speed_profile"] = "slow_point"
    config.write_text(json.dumps(payload), encoding="utf-8")

    assert defaults_module.component_speed_profile("auto_door", "task_point") == "slow_point"
