"""Machine setup, kept separate from unattended workers."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import uuid

from .core import GIB, Store

CATEGORIES = {
    'checkpoints': ['checkpoints'], 'text_encoders': ['clip', 'text_encoders'],
    'clip_vision': ['clip_vision'], 'configs': ['configs'], 'controlnet': ['controlnet'],
    'diffusion_models': ['unet', 'diffusion_models'], 'embeddings': ['embeddings'],
    'ipadapter': ['ipadapter'], 'loras': ['loras'], 'upscale_models': ['upscale_models'],
    'vae': ['vae'], 'audio_encoders': ['audio_encoders'], 'model_patches': ['model_patches'],
    'inpaint': ['inpaint'], 'clip': ['clip'], 'mmaudio': ['mmaudio'],
    'ultralytics': ['ultralytics'], 'ultralytics_bbox': ['ultralytics/bbox'],
    'animatediff_models': ['animatediff_models'], 'animatediff_motion_lora': ['animatediff_motion_lora'],
    'facerestore_models': ['facerestore_models'], 'insightface': ['insightface'],
    'hypernetworks': ['hypernetworks'], 'style_models': ['style_models'],
    'vae_approx': ['vae_approx'], 'gligen': ['gligen'], 'photomaker': ['photomaker'],
}


def profile(windows=True):
    text = '# Drive Manager: existing SSD models first, HDD fallback. No model files moved.\n'
    # Default paths are prepended by ComfyUI, so the final F section takes priority.
    for key, root, default in [('drive_manager_hdd', 'D:/models/' if windows else '/mnt/d/models/', False),
                               ('drive_manager_ssd', 'F:/models/' if windows else '/mnt/f/models/', True)]:
        text += key + ':\n  base_path: ' + root + '\n'
        if default:
            text += '  is_default: true\n'
        for category, dirs in CATEGORIES.items():
            existing = [d for d in dirs if (Path('/mnt/f/models' if default else '/mnt/d/models') / d).is_dir()]
            if not existing:
                continue
            text += f'  {category}: |\n' + ''.join('    ' + d + '/\n' for d in existing)
    return text


def profiles(store):
    directory = store.state / 'profiles'
    directory.mkdir(exist_ok=True)
    for name, windows in [('comfyui-f-first.yaml', True), ('comfyui-wsl-f-first.yaml', False)]:
        (directory / name).write_text(profile(windows))


def install_comfy(store):
    profiles(store)
    marker = '# BEGIN DRIVE MANAGER MODEL ROUTING\n'
    end = '# END DRIVE MANAGER MODEL ROUTING\n'
    targets = [Path('/mnt/d/models/extra_model_paths.yaml'),
               Path('/mnt/c/Users/cosgroma/AppData/Roaming/ComfyUI/extra_models_config.yaml')]
    installed = []
    for target in targets:
        if not target.is_file() or target.is_symlink():
            continue
        original = target.read_bytes()
        text = original.decode('utf-8')
        if marker in text:
            before, tail = text.split(marker, 1)
            if end not in tail:
                raise ValueError('Unfinished managed routing block: ' + str(target))
            _, after = tail.split(end, 1)
            text = before + after
        desired = text.rstrip() + '\n\n' + marker + profile(True) + end
        if desired.encode() != original:
            backup = store.state / 'config-backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
            backup.mkdir(parents=True)
            (backup / 'original').write_bytes(original)
            (backup / 'metadata.json').write_text(json.dumps({'path': str(target), 'sha256': hashlib.sha256(original).hexdigest()}, indent=2))
            temporary = target.with_name(target.name + '.drive-manager.tmp')
            with temporary.open('x') as f:
                f.write(desired)
                f.flush()
                import os
                os.fsync(f.fileno())
            shutil.copystat(target, temporary)
            if target.read_bytes() != original:
                temporary.unlink()
                raise ValueError('Configuration changed during preparation: ' + str(target))
            temporary.replace(target)
            store.event('Installed F-first ComfyUI routing; original backed up: ' + str(target))
        installed.append({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    with store.db() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('model_routing',?)",
                   (json.dumps({'comfyui': installed, 'lmstudio': 'D:/models; migration review needed',
                                'requires_app_restart': True}),))
    return installed


def seed(store):
    profiles(store)
    # Start with high-value metadata. No content hashing of terabyte captures.
    for path, depth in [('/mnt/f/models', -1), ('/mnt/d/models', -1),
                        ('/mnt/f/wsl_imports', -1), ('/mnt/f/installers', -1),
                        ('/mnt/d/wsl-exports', -1), ('/mnt/d/data', 1),
                        ('/mnt/d/.backups', -1), ('/mnt/e/.backups', -1),
                        ('/mnt/f/Photos', -1), ('/mnt/h/Photos', -1)]:
        if Path(path).is_dir():
            store.scan(path, depth)
            store.schedule(path, depth, 86400 if path.endswith('/models') else 7 * 86400)
    for root in store.roots:
        if root.is_dir():
            store.scan(str(root), 0)
    leads = [
        ('/mnt/f/wsl_imports/ubuntu', 'Registered Ubuntu distribution occupies about 717 GiB on the SSD. '
         'Review whether this older distribution is still needed; virtual disks require a dedicated offline workflow.'),
        ('/mnt/d/wsl-exports/Ubuntu-24.04-20260614-191807.tar', '153 GiB June WSL export. '
         'Review retention and verify a newer restore point before considering removal.'),
        ('/mnt/f/Photos', 'Approximately 395 GiB on the model SSD. Compare against H:/Photos '
         'before choosing archival or duplicate cleanup.'),
    ]
    with store.db() as db:
        for path, reason in leads:
            if not Path(path).exists():
                continue
            ident = hashlib.sha256(('lead:' + path).encode()).hexdigest()[:32]
            db.execute("INSERT OR IGNORE INTO candidates(id,kind,source,reason,created,updated) "
                       "VALUES(?,'inspect',?,?,?,?)", (ident, path, reason, time.time(), time.time()))
    store.event('Initial live metadata scans queued; historical report leads require fresh verification')


def suggest(store):
    base = Path('/mnt/f/installers')
    target = Path('/mnt/d/archive/ssd-offload/installers')
    count = 0
    if base.is_dir():
        for path in base.rglob('*'):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {'.exe', '.msi', '.msix', '.zip', '.7z', '.iso', '.tar', '.gz', '.tgz'}:
                continue
            destination = target / path.relative_to(base)
            if destination.exists():
                continue
            store.propose(str(path), str(destination), 'move',
                          'Installer archive offload: preserve the installer on the capacity HDD. '
                          'The SSD recovery original requires a separate removal approval to reclaim space.')
            count += 1
    store.event(f'Prepared {count} installer offload proposals for review; no source files moved')
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['seed', 'profiles', 'install-comfy', 'suggest', 'route-models', 'migrate-recovery', 'status'])
    parser.add_argument('--state', default=str(Path.home() / '.local/share/drive-manager'))
    args = parser.parse_args()
    store = Store(args.state)
    if args.command == 'seed':
        seed(store)
    elif args.command == 'profiles':
        profiles(store)
    elif args.command == 'install-comfy':
        print(json.dumps(install_comfy(store), indent=2))
    elif args.command == 'suggest':
        print(suggest(store))
    elif args.command == 'route-models':
        from .models import propose_used
        with store.db() as db:
            db.execute("INSERT OR IGNORE INTO policies VALUES('existing-model-ssd-route',?,?,?,1,1,?)",
                       ('/mnt/d/models', '/mnt/f/models', 'model_route', time.time()))
        print('Proposals prepared:', len(propose_used(store)))
    elif args.command == 'migrate-recovery':
        from .models import migrate_recovery
        print('Recovery folders relocated:', migrate_recovery(store))
    else:
        result = store.snapshot()
        print(json.dumps({k: result[k] for k in ('totals', 'jobs', 'policies')}, indent=2))


if __name__ == '__main__':
    main()
