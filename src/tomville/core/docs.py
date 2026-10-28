"""Shared Markdown docs: safe paths, headings, section addressing, version tags. No UI code."""
from dataclasses import dataclass
import datetime as dt
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

NOTES = 'notes'
HEADING = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
SEPARATOR = '>'


class DocError(ValueError):
    """A doc problem the user can fix; the message says how."""


class DocConflict(DocError):
    """An edit overlaps someone else's change; `diff` shows what the other side did."""

    def __init__(self, message, diff='', version=''):
        super().__init__(message)
        self.diff, self.version = diff, version


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int  # 0-based index of the heading line
    end: int  # 0-based index one past the section's last line
    path: tuple  # titles from the top-level ancestor down to this heading


def version_tag(data):
    """A short content hash for a whole file (bytes or text)."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()[:12]


def parse_headings(text):
    """ATX headings outside fenced code blocks, with the line range of each section."""
    found = []
    fence = None
    lines = text.splitlines()
    for number, line in enumerate(lines):
        marker = FENCE.match(line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        if match := HEADING.match(line):
            found.append((len(match.group(1)), match.group(2).strip(), number))
    headings, stack = [], []
    for index, (level, title, number) in enumerate(found):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end = next((n for lv, _, n in found[index + 1:] if lv <= level), len(lines))
        headings.append(Heading(level, title, number, end, tuple(t for _, t in stack)))
    return headings


def doc_title(text, fallback=''):
    return next((h.title for h in parse_headings(text) if h.level == 1), fallback)


def parse_section_path(value):
    parts = [part.strip() for part in value.split(SEPARATOR)]
    if not value.strip() or any(not part for part in parts):
        raise DocError(f'bad section path {value!r}: use "Heading" or "Parent {SEPARATOR} Child"')
    return tuple(parts)


def find_section(text, section):
    """The one heading whose path ends with `section` ("A > B"); errors if none or several."""
    wanted = parse_section_path(section)
    matches = [h for h in parse_headings(text) if h.path[-len(wanted):] == wanted]
    if not matches:
        known = ', '.join(f'"{" > ".join(h.path)}"' for h in parse_headings(text)) or 'the file has no headings'
        raise DocError(f'no section "{section}"; known sections: {known}')
    if len(matches) > 1:
        where = ', '.join(f'line {h.line + 1} ("{" > ".join(h.path)}")' for h in matches)
        raise DocError(f'section "{section}" matches {len(matches)} headings ({where}); add the parent heading, like "Parent {SEPARATOR} {section}"')
    return matches[0]


def section_text(text, section):
    heading = find_section(text, section)
    lines = text.splitlines(keepends=True)
    return ''.join(lines[heading.line:heading.end])


def project_root(project):
    """The main checkout, so every worktree sees the same notes/ (git's common dir)."""
    try:
        common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                cwd=project, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return Path(project).resolve()
    if common.returncode:
        return Path(project).resolve()
    return Path(common.stdout.strip()).parent.resolve()


def doc_roots(root, names):
    """Resolved root folders; each must stay inside the project."""
    roots = []
    for name in names:
        folder = (root / name).resolve()
        if not folder.is_relative_to(root):
            raise DocError(f'docs root {name!r} is outside the project')
        roots.append(folder)
    return roots


def resolve_doc(root, names, path, *, must_exist=True):
    """Check the B7 safety rules and return the real path of a doc.

    Only .md files, only under the configured roots, nothing outside the project,
    and no symlink that points out of it (resolving follows links, so a link out
    of the project fails the same check as a path out of it).
    """
    root = root.resolve()
    raw = Path(path).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.suffix.lower() != '.md':
        raise DocError(f'{path}: only .md files are allowed')
    # `resolve()` collapses `..` and follows symlinks; the result is the real location.
    real = candidate.resolve()
    if not real.is_relative_to(root):
        raise DocError(f'{path}: outside the project ({root})' if not candidate.is_symlink()
                       else f'{path}: a symlink pointing outside the project')
    if any(p == '.git' for p in real.relative_to(root).parts):
        raise DocError(f'{path}: files inside .git are not docs')
    if real.suffix.lower() != '.md':
        raise DocError(f'{path}: a symlink to a file that is not .md')
    roots = doc_roots(root, names)
    if not any(real.is_relative_to(folder) for folder in roots):
        allowed = ', '.join(str(f.relative_to(root)) or '.' for f in roots)
        raise DocError(f'{path}: not under a docs root ({allowed}); change [docs] roots to allow it')
    if must_exist and not real.is_file():
        raise DocError(f'{path}: no such doc' + (' (it is a folder)' if real.is_dir() else ''))
    return real


def relative(root, path):
    return path.relative_to(root.resolve()).as_posix()


def last_change(root, path):
    """(editor, ISO time) from git when the file is tracked, else the file's mtime."""
    try:
        result = subprocess.run(['git', 'log', '-1', '--format=%an%x09%aI', '--', str(path)],
                                cwd=root, capture_output=True, text=True, timeout=5)
        editor, _, when = result.stdout.strip().partition('\t')
        if result.returncode == 0 and when:
            return editor, when
    except (OSError, subprocess.SubprocessError):
        pass
    when = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec='seconds')
    return '', when


def list_docs(root, names, folder=NOTES):
    """Every doc under `folder` (default notes/) with its title, last editor and last change."""
    root = root.resolve()
    start = (root / folder).resolve()
    if not start.is_relative_to(root):
        raise DocError(f'{folder}: outside the project')
    if not start.exists():
        return []
    if not start.is_dir():
        raise DocError(f'{folder}: not a folder')
    if not any(start.is_relative_to(r) or r.is_relative_to(start) for r in doc_roots(root, names)):
        raise DocError(f'{folder}: not under a docs root; change [docs] roots to allow it')
    docs = []
    for current, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__'))
        for name in sorted(files):
            if not name.lower().endswith('.md'):
                continue
            try:
                real = resolve_doc(root, names, Path(current) / name)
                text = real.read_text(encoding='utf-8')
            except (DocError, UnicodeDecodeError, OSError):
                continue  # unsafe links and unreadable files are not listed
            editor, when = last_change(root, real)
            docs.append(dict(path=relative(root, real), title=doc_title(text, real.stem),
                             editor=editor, changed=when, version=version_tag(text),
                             conflicted=is_conflicted(root, relative(root, real))))
    return docs


def read_doc(root, names, path, section=None, state_root=None):
    real = resolve_doc(root, names, path)
    data = real.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise DocError(f'{path}: not UTF-8 text') from exc
    body = section_text(text, section) if section else text
    store_object(state_root or root, text)  # the base for a later `edit --base TAG`
    return dict(path=relative(root, real), section=section, version=version_tag(data), text=body,
                conflicted=is_conflicted(root, relative(root, real)))


def new_doc(root, names, path, title, state_root=None):
    title = title.strip()
    if not title or '\n' in title:
        raise DocError('--title must be one line of text')
    real = resolve_doc(root, names, path, must_exist=False)
    if real.exists():
        raise DocError(f'{path}: already exists; use `tmv doc read` to see it')
    text = f'# {title}\n\n'
    real.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(real, 'x', encoding='utf-8') as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise DocError(f'{path}: already exists') from exc
    store_object(state_root or root, text)
    return dict(path=relative(root, real), title=title, version=version_tag(text))


# --- safe edits: lock, base objects, 3-way merge, conflict marks -------------------------

TAG = re.compile(r'[0-9a-f]{12}')
MARKERS = re.compile(r'^(<{7} |>{7} )', re.M)


def locate(project, path):
    """(doc root, state root) for a path given by an agent in `project`.

    Team notes (`notes/...`) live in the main checkout, shared by every worktree.
    Every other doc is written in the caller's own worktree, so the PR flow applies.
    """
    main = project_root(project)
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=project,
                             capture_output=True, text=True, timeout=5)
        top = Path(top.stdout.strip()).resolve() if top.returncode == 0 else Path(project).resolve()
    except (OSError, subprocess.SubprocessError):
        top = Path(project).resolve()
    raw = Path(path).expanduser()
    shared = main / NOTES
    if raw.is_absolute():
        inside = raw.resolve().is_relative_to(shared.resolve())
    else:
        inside = raw.parts[:1] == (NOTES,)
    return (main if inside else top), main


def store_object(state_root, text):
    """Keep `text` by its tag; the base of later 3-way merges and history for the change log."""
    tag = version_tag(text)
    path = Path(state_root) / '.tomville/doc-objects' / tag
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f'{tag}.{os.getpid()}.tmp')
        temporary.write_text(text, encoding='utf-8')
        os.replace(temporary, path)
    return tag


def load_object(state_root, tag):
    if not TAG.fullmatch(tag):
        raise DocError(f'bad version tag {tag!r}: use the tag `tmv doc read` printed')
    path = Path(state_root) / '.tomville/doc-objects' / tag
    try:
        return path.read_text(encoding='utf-8')
    except OSError as exc:
        raise DocError(f'unknown version {tag}: read the doc again and use its new tag') from exc


def _key(rel):
    return hashlib.sha1(rel.encode()).hexdigest()[:16]


def _mark(root, rel):
    return Path(root) / '.tomville/doc-state' / f'{_key(rel)}.json'


def is_conflicted(root, rel):
    return _mark(root, rel).exists()


class _Lock:
    """An exclusive flock on a lock file in .tomville/, so edits to one doc never interleave."""

    def __init__(self, root, rel):
        self.path = Path(root) / '.tomville/doc-locks' / f'{_key(rel)}.lock'

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(self.path, 'a')
        fcntl.flock(self.stream, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        self.stream.close()  # closing releases the lock


def write_atomic(path, text):
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with open(temporary, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _lines(text):
    return text.splitlines(keepends=True)


def _ends_with_newline(lines):
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'


def apply_edit(base, section, mode, new):
    """The new full text: `new` replaces or is appended to a section (or the whole file)."""
    new_lines = _lines(new)
    _ends_with_newline(new_lines)
    lines = _lines(base)
    if section is None:
        if mode == 'replace':
            return ''.join(new_lines)
        _ends_with_newline(lines)
        return ''.join(lines + new_lines)
    heading = find_section(base, section)
    if mode == 'replace':
        first = next(iter(parse_headings(new)), None)
        if not first or first.line != next((i for i, l in enumerate(new_lines) if l.strip()), -1) or first.level != heading.level:
            raise DocError(f'--replace of a section must start with its heading line (level {heading.level}); '
                           f'`tmv doc read --section` prints it that way')
        old = lines[heading.line:heading.end]
        blanks = 0
        while blanks < len(old) and not old[len(old) - 1 - blanks].strip():
            blanks += 1
        if heading.end < len(lines) and new_lines[-1].strip():
            new_lines += ['\n'] * blanks  # keep the gap before the next heading
        lines[heading.line:heading.end] = new_lines
        return ''.join(lines)
    end = heading.end
    while end > heading.line + 1 and not lines[end - 1].strip():
        end -= 1  # insert after the section's last text, before its trailing blank lines
    if end and not lines[end - 1].endswith('\n'):
        lines[end - 1] += '\n'
    lines[end:end] = new_lines
    return ''.join(lines)


def _changes(base, other):
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != 'equal']


def _overlap(a, b):
    (a1, a2), (b1, b2) = a[:2], b[:2]
    if a1 < a2 and b1 < b2:
        return max(a1, b1) < min(a2, b2)
    if a1 == a2 and b1 == b2:
        return a1 == b1
    if a1 == a2:  # an insertion touches a range only at its end or inside it
        return b1 < a1 <= b2
    return a1 < b1 <= a2


def _apply(base, start, end, changes):
    out, pos = [], start
    for i1, i2, new in sorted(changes):
        out += base[pos:i1] + new
        pos = i2
    return out + base[pos:end]


def merge3(base, ours, theirs):
    """Line-based 3-way merge. Returns (text, number of conflicts).

    Changes that touch different lines merge. Changes to the same lines conflict unless
    both sides made the same change. Conflicts get git-style markers.
    """
    base, ours, theirs = _lines(base), _lines(ours), _lines(theirs)
    mine, other = _changes(base, ours), _changes(base, theirs)
    out, pos, conflicts = [], 0, 0
    while mine or other:
        sides = sorted([(c, 0) for c in mine[:1]] + [(c, 1) for c in other[:1]])
        (first, side), rest = sides[0], sides[1:]
        if not rest or not _overlap(first, rest[0][0]):
            out += base[pos:first[0]] + first[2]
            pos = first[1]
            (mine if side == 0 else other).pop(0)
            continue
        start, end = first[0], first[1]
        taken = ([], [])
        grew = True
        while grew:
            grew = False
            for i, queue in enumerate((mine, other)):
                while queue and _overlap((start, end), queue[0]):
                    change = queue.pop(0)
                    taken[i].append(change)
                    start, end = min(start, change[0]), max(end, change[1])
                    grew = True
        out += base[pos:start]
        mine_text, their_text = _apply(base, start, end, taken[0]), _apply(base, start, end, taken[1])
        if mine_text == their_text:
            out += mine_text
        else:
            conflicts += 1
            _ends_with_newline(mine_text)
            _ends_with_newline(their_text)
            out += ['<<<<<<< ours\n'] + mine_text + ['=======\n'] + their_text + ['>>>>>>> theirs\n']
        pos = end
    return ''.join(out + base[pos:]), conflicts


def edit_doc(root, names, path, base_tag, new, *, section=None, mode='replace', merge=False, state_root=None):
    """Edit a doc without ever silently overwriting someone else's change.

    `base_tag` is the version the writer read. If the file is still at that version the
    edit is written. If it changed, the edit is merged into the file's current content
    (3-way, against the stored base). Overlapping changes are refused with a DocConflict
    (exit code 3 on the CLI), or written with markers and marked conflicted when `merge`.
    """
    if mode not in ('replace', 'append'):
        raise DocError('mode must be replace or append')
    if not new.strip():
        raise DocError('nothing to write: the new text (stdin) is empty')
    real = resolve_doc(root, names, path)
    rel = relative(root, real)
    state_root = state_root or root
    with _Lock(root, rel):
        data = real.read_bytes()
        try:
            current = data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise DocError(f'{path}: not UTF-8 text') from exc
        current_tag = version_tag(data)
        if is_conflicted(root, rel):
            raise DocError(f'{rel} has unresolved conflicts: fix the <<<<<<< / ======= / >>>>>>> parts, '
                           f'then run `tmv doc resolve {rel}`')
        store_object(state_root, current)
        base = current if base_tag == current_tag else load_object(state_root, base_tag)
        ours = apply_edit(base, section, mode, new)
        conflicts = 0
        if base_tag == current_tag:
            result = ours
        else:
            result, conflicts = merge3(base, ours, current)
            if conflicts and not merge:
                diff = ''.join(difflib.unified_diff(_lines(base), _lines(current), 'your base', 'current file'))
                raise DocConflict(f'{rel} changed since {base_tag} and the changes overlap; '
                                  f'read it again (now {current_tag}) and redo your edit, or use --merge to write conflict markers',
                                  diff, current_tag)
        if result != current:
            write_atomic(real, result)
            store_object(state_root, result)
        if conflicts:
            mark = _mark(root, rel)
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.write_text(json.dumps({'path': rel, 'conflicts': conflicts}))
        return dict(path=rel, version=version_tag(result), merged=base_tag != current_tag and result != ours,
                    conflicted=bool(conflicts), conflicts=conflicts, written=result != current)


def resolve_doc_conflicts(root, names, path, state_root=None):
    """Clear the conflicted mark once no conflict markers are left in the file."""
    real = resolve_doc(root, names, path)
    rel = relative(root, real)
    with _Lock(root, rel):
        text = real.read_text(encoding='utf-8')
        if not is_conflicted(root, rel):
            raise DocError(f'{rel} is not marked conflicted; nothing to resolve')
        if MARKERS.search(text):
            lines = [str(n) for n, line in enumerate(text.splitlines(), 1) if MARKERS.match(line)]
            raise DocError(f'{rel} still has conflict markers (lines {", ".join(lines)}); '
                           'edit them out, keeping what you want, then run resolve again')
        _mark(root, rel).unlink(missing_ok=True)
        store_object(state_root or root, text)
        return dict(path=rel, version=version_tag(text), conflicted=False)
