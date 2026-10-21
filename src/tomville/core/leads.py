"""Private pane-to-ville hints; hooks must still validate the ville's own state."""
import json
import os
from pathlib import Path
import tempfile

from tomville.core.locks import file_lock


def registry_path():
    return Path.home() / '.config/tomville/leads.json'


def read():
    path = registry_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or any(
        not isinstance(pane, str) or not pane or not isinstance(folder, str) or not Path(folder).is_absolute()
        for pane, folder in data.items()
    ):
        raise ValueError('invalid lead registry')
    return data


def lookup(pane):
    folder = read().get(pane)
    return Path(folder) if folder is not None else None


def write(data):
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.leads-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)  # mkstemp keeps the registry mode 600, including upgrades.
    finally:
        Path(name).unlink(missing_ok=True)


def register(project, pane):
    if not pane:
        return
    folder = str(project.resolve())
    with file_lock(registry_path().with_suffix('.lock')):
        data = {p: root for p, root in read().items() if root != folder}
        data[pane] = folder
        write(data)


def unregister(project):
    if not registry_path().exists():
        return
    folder = str(project.resolve())
    with file_lock(registry_path().with_suffix('.lock')):
        data = read()
        remaining = {p: root for p, root in data.items() if root != folder}
        if remaining != data:
            write(remaining)
