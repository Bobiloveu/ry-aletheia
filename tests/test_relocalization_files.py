from pathlib import Path
import os

import autodrive_console.relocalization_files as module

import pytest

from autodrive_console.relocalization_files import LocalizationConfigFiles, LocalizationConfigFileError


@pytest.fixture
def configs(tmp_path, monkeypatch):
    root = tmp_path / 'localization'
    root.mkdir()
    maps = tmp_path / 'maps'
    monkeypatch.setattr(module.MapAssetCache, 'ALLOWED_ROOTS', (maps,))
    current = maps / 'P2' / 'map.yaml'
    current.parent.mkdir(parents=True)
    current.write_text('image: map.pgm\n')
    path = root / 'floor.yaml'
    path.write_text(f'system:\n  map_path: {current.parent}\n  init_pose: {{x: 99}}\n')
    return LocalizationConfigFiles(root), root, current, path


def test_browser_lists_one_level_yaml_files_and_stays_inside_root(configs, tmp_path):
    catalog, root, current, path = configs
    (root / 'nested').mkdir()
    (root / 'notes.txt').write_text('not a config')
    (root / 'outside').symlink_to(tmp_path / 'maps', target_is_directory=True)
    result = catalog.browse('')
    assert result['path'] == str(root)
    assert result['parent'] is None
    assert [item['name'] for item in result['directories']] == ['nested']
    assert [item['name'] for item in result['files']] == ['floor.yaml']
    assert catalog.browse(str(root / 'nested'))['parent'] == str(root)
    with pytest.raises(LocalizationConfigFileError):
        catalog.browse(str(current.parent))


def test_selection_is_read_only_and_validates_the_current_map(configs):
    catalog, root, current, path = configs
    before = path.read_bytes()
    selection = catalog.select(str(path), current)
    assert selection.path == path
    catalog.revalidate(selection, current)
    assert path.read_bytes() == before
    assert sorted(root.iterdir()) == [path]


@pytest.mark.parametrize('failure', ['outside', 'symlink', 'missing', 'directory', 'wrong_extension',
                                   'nonexistent_map', 'missing_map', 'relative_map', 'malformed', 'oversize', 'traversal'])
def test_invalid_selection_is_rejected(configs, tmp_path, failure):
    catalog, root, current, path = configs
    selected = str(path)
    if failure == 'outside':
        outside = tmp_path / 'outside.yaml'; outside.write_bytes(path.read_bytes()); selected = str(outside)
    elif failure == 'symlink':
        outside = tmp_path / 'outside.yaml'; outside.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(outside)
    elif failure == 'missing': path.unlink()
    elif failure == 'directory': path.unlink(); path.mkdir()
    elif failure == 'wrong_extension':
        other = path.with_suffix('.txt'); path.rename(other); selected = str(other)
    elif failure == 'nonexistent_map': path.write_text(f'system: {{map_path: {root / "missing"}}}')
    elif failure == 'missing_map': path.write_text('system: {}')
    elif failure == 'relative_map': path.write_text('system: {map_path: ../maps/P2}')
    elif failure == 'malformed': path.write_text('system: [')
    elif failure == 'oversize': path.write_bytes(b' ' * (512 * 1024 + 1))
    elif failure == 'traversal': selected = str(root / '..' / root.name / path.name)
    with pytest.raises(LocalizationConfigFileError): catalog.select(selected, current)


def test_same_path_replaced_after_selection_is_rejected(configs):
    catalog, root, current, path = configs
    selected = catalog.select(str(path), current)
    replacement = root / 'replacement.yaml'
    replacement.write_bytes(path.read_bytes())
    replacement.replace(path)
    with pytest.raises(LocalizationConfigFileError): catalog.revalidate(selected, current)


@pytest.mark.parametrize('duplicate', ['system', 'map_path', 'merge'])
def test_duplicate_map_binding_is_not_accepted(configs, duplicate):
    catalog, root, current, path = configs
    if duplicate == 'system':
        path.write_text(f'system: {{map_path: {root}}}\nsystem: {{map_path: {current.parent}}}\n')
    elif duplicate == 'map_path':
        path.write_text(f'system:\n  map_path: {root}\n  map_path: {current.parent}\n')
    else:
        path.write_text(f'defaults: &base {{map_path: {current.parent}}}\nsystem: {{<<: *base}}\n')
    with pytest.raises(LocalizationConfigFileError): catalog.select(str(path), current)


@pytest.mark.parametrize('when', ['first_open', 'file_open'])
def test_parent_directory_swapped_to_outside_symlink_before_open_is_rejected(configs, tmp_path, monkeypatch, when):
    catalog, root, current, original_path = configs
    parent = root / 'configs'; parent.mkdir()
    path = parent / 'floor.yaml'; path.write_bytes(original_path.read_bytes())
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'floor.yaml').write_bytes(path.read_bytes())
    original_open = os.open
    swapped = False
    def swap_then_open(raw, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and (when == 'first_open' or str(raw) == path.name):
            swapped = True
            parent.rename(root / 'previous')
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(raw, flags, *args, **kwargs)
    monkeypatch.setattr(module.os, 'open', swap_then_open)
    with pytest.raises(LocalizationConfigFileError): catalog.select(str(path), current)


def test_manual_selection_can_target_another_existing_map(configs):
    catalog, root, current, path = configs
    target = current.parent.parent / 'P1'
    target.mkdir()
    (target / 'map.yaml').write_text('image: map.pgm\n')
    path.write_text(f'system: {{map_path: {target}}}')
    selection = catalog.select(str(path), current)
    assert selection.map_directory == target
    catalog.revalidate(selection, current)

@pytest.mark.parametrize('failure', ['missing', 'outside_symlink', 'replaced'])
def test_selected_target_map_file_is_checked_and_revalidated(configs, tmp_path, failure):
    catalog, root, current, path = configs
    if failure == 'replaced':
        selection = catalog.select(str(path), current)
        replacement = current.parent/'replacement.yaml'
        replacement.write_bytes(current.read_bytes())
        replacement.replace(current)
        with pytest.raises(LocalizationConfigFileError):catalog.revalidate(selection,current)
    else:
        current.unlink()
        if failure == 'outside_symlink':
            other = tmp_path/'outside.yaml';other.write_text('image: map.pgm\n')
            current.symlink_to(other)
        with pytest.raises(LocalizationConfigFileError):catalog.select(str(path),current)
