"""Audited project-owned preview cache; never a robot runtime cache."""
from copy import deepcopy
from hashlib import sha256
from functools import lru_cache
from importlib import import_module
import json
from pathlib import Path
from types import CodeType

from . import task_compiler as tc
from . import location_manifest as lm
from . import component_defaults
from .task_compiler import Artifact, CompilationPreview


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def stable_code_bytes(code):
    """Ignore extraction paths and canonicalize hash-randomized constants."""
    def normalize(value):
        if isinstance(value, CodeType):
            return {'code': value.co_code.hex(), 'constants': normalize(value.co_consts),
                    'names': value.co_names, 'locals': value.co_varnames,
                    'free': value.co_freevars, 'cells': value.co_cellvars,
                    'args': (value.co_argcount, value.co_posonlyargcount, value.co_kwonlyargcount),
                    'flags': value.co_flags, 'name': value.co_name,
                    'exceptions': getattr(value, 'co_exceptiontable', b'').hex()}
        if isinstance(value, frozenset):
            members = [normalize(c) for c in value]
            return {'frozenset': sorted(members, key=_json)}
        if isinstance(value, tuple):
            return {'tuple': [normalize(c) for c in value]}
        if isinstance(value, bytes):
            return {'bytes': value.hex()}
        if value is Ellipsis:
            return {'ellipsis': True}
        if isinstance(value, complex):
            return {'complex': repr(value)}
        return value
    return _json(normalize(code))


@lru_cache(maxsize=1)
def _compiler_code_digest():
    digest = sha256()
    for name in ('task_compiler', 'fixed_task_compiler', 'fixed_route_geometry', 'fixed_multi_export', 'location_manifest',
                 'automatic_route', 'map_reachability', 'task_preview_cache',
                 'execution_chain', 'component_defaults', 'task_lines', 'task_path',
                 'task_route_families', 'task_status_codes', 'localization_assets', 'virtual_walls'):
        module = import_module('.'+name, __package__)
        code = module.__loader__.get_code(module.__name__)
        digest.update(name.encode()+b'\0'+stable_code_bytes(code))
    return digest.digest()


def input_fingerprint(document, map_root):
    """Hash actual source bytes, including edits, code, templates and clouds.

    Timestamps alone cannot detect same-size replacements on coarse clocks.
    An unavailable or uncontrolled source disables reuse and leaves reporting
    of the precise validation error to the existing compiler.
    """
    try:
        project = deepcopy(document)
        project.pop('updated_at', None)
        project.get('task_compiler', {}).get('identity', {}).pop('last_preview_input_sha256', None)
        digest = sha256(b'task-preview-cache-v1\0'+_json(project))
        root = Path(map_root).resolve()
        for asset in document.get('map_assets', []):
            tc._source_path(asset, root)
        files = [('maps/'+path.relative_to(root).as_posix(), path) for path in root.rglob('*')]
        template_root = Path(tc.TEMPLATE_ROOT)
        files.extend(('templates/'+path.relative_to(template_root).as_posix(), path)
                     for path in template_root.rglob('*'))
        files.extend([('status-registry', tc.task_status_codes_module.STATUS_CODE_PATH),
                      ('component-defaults', component_defaults.COMPONENT_DEFAULTS_PATH)])
        digest.update(_compiler_code_digest())
        digest.update(lm.localization_template_text(document, map_root=root).encode('utf-8'))
        for name, path in sorted(set(files)):
            if path.is_symlink():
                return None
            if path.is_dir():
                continue
            digest.update(name.encode('utf-8')+b'\0')
            member = sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(1024*1024):
                    member.update(chunk)
            digest.update(member.digest())
        # Validate the status registry even when returning a cached result.
        digest.update(tc.task_status_codes_module.task_status_code_snapshot().raw_bytes)
        return digest.hexdigest()
    except (OSError, ValueError, TypeError, AttributeError, ImportError):
        return None


def cache_record(fingerprint, payload):
    return {'fingerprint': fingerprint, 'payload': payload,
            'payload_sha256': sha256(_json(payload)).hexdigest()}


def load_preview(export_root, fingerprint, expected_hash):
    if not fingerprint or not expected_hash:
        return None
    try:
        record = json.loads((export_root/'preview-cache.json').read_text(encoding='utf-8'))
        payload = record['payload']
        if (record['fingerprint'] != fingerprint or payload['input_sha256'] != expected_hash
                or record['payload_sha256'] != sha256(_json(payload)).hexdigest()):
            return None
        directory = (export_root/expected_hash).resolve()
        if directory.parent != export_root.resolve() or (export_root/expected_hash).is_symlink():
            return None
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if manifest != payload['manifest'] or manifest.get('input_sha256') != expected_hash:
            return None
        artifacts = []
        for item in payload['artifacts']:
            path = (directory/item['path']).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                return None
            content = path.read_bytes()
            if len(content) != item['size_bytes'] or sha256(content).hexdigest() != item['sha256']:
                return None
            artifacts.append(Artifact(item['path'], content, item['sha256']))
        return CompilationPreview(expected_hash, payload['task_json'], tuple(artifacts),
                                  manifest, payload['derived_points'],
                                  tuple(payload['warnings']), tuple(payload['errors']))
    except (OSError, ValueError, KeyError, TypeError):
        return None
