"""Strict Telegram HTML and bounded, file/hunk-aware diff messages. No UI code."""
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
import json
import re
import shlex
import ast

from tomville.core.commands import run_command

LIMIT = 4096
CODE_OPEN = '<pre><code class="language-diff">'
CODE_CLOSE = '</code></pre>'


def units(text):
    # Entity offsets in Telegram use UTF-16; this also bounds serialized HTML.
    return len(text.encode('utf-16-le')) // 2


def code_pieces(atoms, limit):
    """Split escaped code at lines, then characters/entities for oversized lines."""
    if limit < 1:
        raise ValueError('message limit too small for code block')
    current, used, line = [], 0, []
    lines = []
    for atom in atoms:
        line.append(atom)
        if atom == '\n':
            lines.append(line)
            line = []
    if line:
        lines.append(line)
    for line in lines:
        width = sum(units(a) for a in line)
        if current and used + width > limit:
            yield ''.join(current)
            current, used = [], 0
        for atom in line:
            width = units(atom)
            if width > limit:
                raise ValueError('message limit too small for a code character')
            if used + width > limit:
                yield ''.join(current)
                current, used = [], 0
            current.append(atom)
            used += width
    if current:
        yield ''.join(current)


class _Chunks(HTMLParser):
    def __init__(self, size):
        super().__init__(convert_charrefs=False)
        if size < 1:
            raise ValueError('message limit must be positive')
        self.size, self.parts, self.current, self.length, self.tags = size, [], '', 0, []
        self.mode, self.atoms, self.opening, self.ending = '', [], '', ''

    def closing(self):
        return ''.join(f'</{t}>' for t in reversed(self.tags))

    def flush(self):
        if self.current:
            self.parts.append(self.current + self.closing())
        self.current = ''.join(f'<{t}>' for t in self.tags)
        self.length = units(self.current)

    def add(self, atom):
        if self.mode:
            if self.mode == 'pre-end':
                raise ValueError('only </pre> may follow a block’s </code>')
            self.atoms.append(atom)
            return
        width = units(atom)
        if width + units(self.closing()) + units(''.join(f'<{t}>' for t in self.tags)) > self.size:
            raise ValueError('message limit too small for HTML')
        if self.length + width + units(self.closing()) > self.size:
            self.flush()
        self.current += atom
        self.length += width

    def block(self):
        opening, ending, atoms = self.opening, self.ending, self.atoms
        self.mode, self.atoms = '', []
        whole = opening + ''.join(atoms) + ending
        if units(whole) <= self.size:
            self.add(whole)
            return
        self.flush()
        for piece in code_pieces(atoms, self.size - units(opening + ending)):
            self.add(opening + piece + ending)

    def handle_starttag(self, tag, attrs):
        if self.mode:
            if self.mode == 'pre' and not self.atoms and tag == 'code':
                if attrs and (len(attrs) != 1 or attrs[0][0] != 'class' or not re.fullmatch(r'language-[A-Za-z0-9_+#.-]{1,40}', attrs[0][1] or '')):
                    raise ValueError('code blocks allow only class="language-X"')
                attribute = f' class="{attrs[0][1]}"' if attrs else ''
                self.mode, self.opening, self.ending = 'pre-code', '<pre><code' + attribute + '>', '</code></pre>'
            else:
                self.handle_data(self.get_starttag_text())
            return
        if tag not in ('b', 'i', 'code', 'pre') or attrs:
            raise ValueError('Telegram text supports only b, i, code and pre/code with a language class')
        if tag in ('code', 'pre'):
            if self.tags:
                raise ValueError('code cannot be nested inside bold or italic')
            self.mode, self.opening, self.ending = tag, f'<{tag}>', f'</{tag}>'
            return
        if units(f'<{tag}></{tag}>' + self.closing() + ''.join(f'<{t}>' for t in self.tags)) > self.size:
            raise ValueError('message limit too small for HTML')
        if self.length + units(f'<{tag}></{tag}>' + self.closing()) > self.size:
            self.flush()
        self.current += f'<{tag}>'
        self.length += units(f'<{tag}>')
        self.tags.append(tag)

    def handle_endtag(self, tag):
        if self.mode:
            if (self.mode == 'code' and tag == 'code') or (self.mode in ('pre', 'pre-end') and tag == 'pre'):
                self.block()
            elif self.mode == 'pre-code' and tag == 'code':
                self.mode = 'pre-end'
            else:
                self.handle_data(f'</{tag}>')
            return
        if not self.tags or self.tags[-1] != tag:
            raise ValueError('Unbalanced Telegram HTML')
        self.current += f'</{self.tags.pop()}>'
        self.length += units(f'</{tag}>')

    def handle_data(self, text):
        for char in text:
            self.add(escape(char, quote=False))

    def handle_entityref(self, name):
        if name not in ('amp', 'lt', 'gt', 'quot'):
            if not self.mode:
                raise ValueError('Unsupported HTML entity')
            self.handle_data('&' + name + ';')
        else:
            self.add(f'&{name};')

    def handle_charref(self, name):
        try:
            value = int(name[1:], 16) if name.lower().startswith('x') else int(name)
            if not 0 < value <= 0x10ffff or 0xd800 <= value <= 0xdfff:
                raise ValueError()
        except ValueError:
            raise ValueError('Invalid HTML character reference') from None
        self.add(f'&#{name};')

    def handle_startendtag(self, tag, attrs):
        if not self.mode:
            raise ValueError('Self-closing HTML tags are not supported')
        self.handle_data(self.get_starttag_text())

    def handle_comment(self, text):
        if not self.mode:
            raise ValueError('HTML comments are not supported')
        self.handle_data('<!--' + text + '-->')

    def handle_decl(self, text):
        if not self.mode:
            raise ValueError('HTML declarations are not supported')
        self.handle_data('<!' + text + '>')

    def handle_pi(self, text):
        if not self.mode:
            raise ValueError('HTML processing instructions are not supported')
        self.handle_data('<?' + text + '>')

    def unknown_decl(self, text):
        raise ValueError('Unsupported HTML declaration')


def chunks(text, size=LIMIT):
    parser = _Chunks(size)
    parser.feed(text)
    parser.close()
    if parser.tags or parser.mode:
        raise ValueError('Unbalanced Telegram HTML')
    if parser.current:
        parser.parts.append(parser.current)
    return parser.parts


@dataclass
class DiffFile:
    path: str
    added: int = 0
    removed: int = 0
    preamble: list = field(default_factory=list)
    hunks: list = field(default_factory=list)


def git_path(text):
    if text.startswith('"'):
        try:
            value = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            raise ValueError('invalid quoted git path') from None
        try:
            return value.encode('latin1').decode('utf-8')
        except (UnicodeError, AttributeError):
            return value
    return text


def parse_diff(text):
    files, current = [], None
    for line in text.splitlines(keepends=True):
        if line.startswith('diff --git '):
            header = line[len('diff --git '):].rstrip('\r\n')
            paths = shlex.split(header, posix=False)
            path = git_path(paths[-1]) if len(paths) == 2 else 'b/' + header.rpartition(' b/')[2]
            if not path.removeprefix('b/'):
                raise ValueError('invalid git diff file header')
            current = DiffFile(path.removeprefix('b/'))
            files.append(current)
        elif current is None:
            if line.strip():
                raise ValueError('expected a git unified diff (diff --git headers)')
        elif line.startswith('@@'):
            current.hunks.append(line)
        elif current.hunks:
            current.hunks[-1] += line
            current.added += line.startswith('+')
            current.removed += line.startswith('-')
        elif not line.startswith('index '):
            if line.startswith('+++ ') and line[4:].rstrip('\r\n') != '/dev/null':
                current.path = git_path(line[4:].rstrip('\r\n')).removeprefix('b/')
            elif line.startswith('rename to ') or line.startswith('copy to '):
                current.path = git_path(line.split(' to ', 1)[1].rstrip('\r\n'))
            current.preamble.append(line)
    return files


def _file_parts(file, capacity):
    header = f'📄 <code>{escape(file.path)}</code> (+{file.added} −{file.removed})\n'
    budget = capacity - units(header + CODE_OPEN + CODE_CLOSE)
    if budget < 8:
        raise ValueError('file header is too long for a Telegram message')
    sections = file.hunks.copy()
    if sections:
        sections[0] = ''.join(file.preamble) + sections[0]
    else:
        sections = [''.join(file.preamble) or '(No textual changes)\n']
    current = ''
    for section in sections:
        encoded = escape(section, quote=False)
        if current and units(current + encoded) > budget:
            yield header + CODE_OPEN + current + CODE_CLOSE
            current = ''
        if units(encoded) > budget:
            atoms = [escape(char, quote=False) for char in section]
            pieces = list(code_pieces(atoms, budget))
            for piece in pieces[:-1]:
                yield header + CODE_OPEN + piece + CODE_CLOSE
            current = pieces[-1]
        else:
            current += encoded
    if current:
        yield header + CODE_OPEN + current + CODE_CLOSE


def diff_messages(diff, headline, *, prefix='', size=LIMIT):
    base = prefix + headline + '\n'
    capacity = size - units(base)
    if capacity < 80:
        raise ValueError('diff title is too long for a Telegram message')
    messages, current = [], base
    files = parse_diff(diff)
    for file in files:
        parts = list(_file_parts(file, capacity))
        # Prefer the file boundary before falling back to hunk/line boundaries.
        if current != base and (len(parts) > 1 or units(current + parts[0]) > size):
            messages.append(current)
            current = base
        for part in parts:
            if units(current + part) > size:
                messages.append(current)
                current = base
            current += part
    if current != base or not messages:
        messages.append(current if files else base + 'No changes.')
    # Validate the entire batch before callers can post its first message.
    if any(len(chunks(message, size)) != 1 for message in messages):
        raise ValueError('diff message exceeds Telegram limit')
    return messages


def pr_diff(project, number, repo=''):
    args = ['--repo', repo] if repo else []
    metadata = json.loads(run_command(['gh', 'pr', 'view', str(number), '--json', 'number,title,author,additions,deletions', *args], project))
    diff = run_command(['gh', 'pr', 'diff', str(number), '--color', 'never', *args], project)
    author = (metadata.get('author') or {}).get('login', 'unknown')
    headline = (f'PR #{metadata["number"]} · <b>{escape(metadata["title"])}</b> · <code>{escape(author)}</code> '
                f'(+{metadata["additions"]} −{metadata["deletions"]})')
    return headline, diff
