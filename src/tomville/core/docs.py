"""Shared Markdown docs: safe paths, headings, section addressing, version tags. No UI code."""
from dataclasses import dataclass
import datetime as dt
import hashlib
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
                             editor=editor, changed=when, version=version_tag(text)))
    return docs


def read_doc(root, names, path, section=None):
    real = resolve_doc(root, names, path)
    data = real.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise DocError(f'{path}: not UTF-8 text') from exc
    body = section_text(text, section) if section else text
    return dict(path=relative(root, real), section=section, version=version_tag(data), text=body)


def new_doc(root, names, path, title):
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
    return dict(path=relative(root, real), title=title, version=version_tag(text))
