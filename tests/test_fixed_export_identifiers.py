from copy import deepcopy
from pathlib import Path
import re

import pytest

from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed, waypoints


@pytest.mark.parametrize('mode', ['single', 'multi'])
def test_fixed_runtime_identifiers_and_xml_names_are_ascii(two_map_project, mode):
    project = fixed_project(two_map_project)
    project['task_mode'] = mode
    project['task_lines'][0]['name'] = '超市取货'
    if mode == 'multi':
        project['task_lines'][0]['steps'].pop()
    for component in project['components']:
        component['label'] = '起点' if component['kind'] == 'start' else '目标点·测试'
    for waypoint in project['waypoints']:
        waypoint['label'] = '门口过渡点'
    before = deepcopy(project)
    preview = compile_fixed(project)
    names = {Path(a.relative_path).stem for a in preview.artifacts if a.relative_path.endswith('.xml')}
    assert names and all(re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in names)
    nodes = waypoints(preview)
    assert {w['waypoint_task_id'] for w in nodes if w['waypoint_task_id']} == names
    assert all(re.fullmatch(r'[A-Za-z0-9_-]+', w['waypoint_id']) for w in nodes)
    assert [t['waypoint_id'] for t in preview.manifest['waypoint_trace']] == [w['waypoint_id'] for w in nodes]
    assert preview.manifest['active_task_line']['name'] == '超市取货'
    assert project == before


def test_ascii_line_names_remain_unique_after_chinese_and_sanitized_collisions(two_map_project):
    project = fixed_project(two_map_project)
    original = project['task_lines'][0]
    project['task_lines'] = [dict(original, id=f'line-{i}', name=name)
                             for i, name in enumerate(['超市取货', '医院送货', 'line_01', 'A/路线', 'A?路线'])]
    exported = []
    for line in project['task_lines']:
        project['active_task_line_id'] = line['id']
        preview = compile_fixed(project)
        names = {Path(a.relative_path).name for a in preview.artifacts if a.relative_path.endswith('.xml')}
        assert all(name.isascii() for name in names)
        assert not any(names & previous for previous in exported)
        exported.append(names)
