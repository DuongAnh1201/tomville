"""Who talks to whom: the message log, `tmv send`, and the Claude Code hook.

herdr doesn't record who sent a prompt, so Tomville logs it itself in
`<repo>/.tomville/messages.jsonl`, one JSON line per message. The log always lives
in the main repo, also when written from a git worktree, so every agent's
messages end up in one place.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tomville.core.models import Message

LOG = Path('.tomville') / 'messages.jsonl'
TELEGRAM_PREFIX = '📱 Tom (Telegram): '


def repo_root(cwd: Path) -> Path:
    """The main repo for `cwd`, following a worktree back to its repo; else `cwd`."""
    try:
        common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return cwd
    if common.returncode:
        return cwd
    return Path(common.stdout.strip()).parent


def log_path(project: Path) -> Path:
    return project / LOG


def append(project: Path, message: Message) -> None:
    path = log_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {'time': message.time.isoformat(timespec='seconds'), 'from': message.sender, 'to': message.to, 'text': message.text, 'via': message.via}
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(line, ensure_ascii=False) + '\n')


def parse_line(line: str) -> Message | None:
    try:
        d = json.loads(line)
        return Message(datetime.fromisoformat(d['time']), d.get('from'), d['to'], d['text'], d.get('via', 'send'))
    except (ValueError, KeyError, TypeError):
        return None


@dataclass
class LogFollower:
    """Reads messages added to the log since the last call."""

    path: Path
    offset: int = 0

    def skip_existing(self) -> None:
        self.offset = self.path.stat().st_size if self.path.exists() else 0

    def read_new(self) -> list[Message]:
        if not self.path.exists():
            self.offset = 0
            return []
        size = self.path.stat().st_size
        if size < self.offset:  # the log was cleared
            self.offset = 0
        if size == self.offset:
            return []
        with self.path.open('rb') as f:
            f.seek(self.offset)
            data = f.read()
        end = data.rfind(b'\n') + 1  # leave a half-written last line for next time
        self.offset += end
        lines = data[:end].decode('utf-8', 'replace').splitlines()
        return [m for m in map(parse_line, lines) if m]


def sender_name() -> str | None:
    """This pane's agent name in herdr, or None when it can't be told."""
    pane = os.environ.get('HERDR_PANE_ID')
    if not pane:
        return None
    from tomville.core.events import agent_list

    try:
        agents = asyncio.run(agent_list())
    except (OSError, ValueError, KeyError, asyncio.TimeoutError):
        return None
    return next((a.name for a in agents if a.pane_id == pane), None)


def send(project: Path, to: str, text: str, wait: bool = False, timeout: int | None = None, *, sender: str | None = None, via: str = 'send', target: str | None = None, prompt_prefix: str = '') -> str:
    """Prompt through herdr, then log the recipient name.

    `target` optionally selects a resolved pane; `prompt_prefix` labels delivery
    without changing the logged text. Nothing is logged if herdr refuses.
    """
    args = ['herdr', 'agent', 'prompt', target or to, prompt_prefix + text]
    if wait:
        args.append('--wait')
    if timeout is not None:
        args += ['--timeout', str(timeout)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise OSError(result.stderr.strip() or result.stdout.strip() or 'herdr agent prompt failed')
    append(project, Message(datetime.now(timezone.utc), sender if sender is not None else sender_name(), to, text, via))
    return result.stdout.strip()


PROMPT = re.compile(r'(?:^|[;&|]\s*)herdr\s+(?:--\S+\s+\S+\s+)*agent\s+prompt\s')


def prompts_in(command: str) -> list[tuple[str, str]]:
    """(target, text) for each `herdr agent prompt TARGET TEXT` in a shell command."""
    found = []
    for match in PROMPT.finditer(command):
        try:
            words = shlex.split(command[match.end():], comments=True)
        except ValueError:
            continue
        words = [w for w in words if not w.startswith('-')]
        if len(words) >= 2:
            found.append((words[0], words[1]))
    return found


def claude_hook(stdin=None) -> int:
    """Claude Code PreToolUse hook: log direct `herdr agent prompt` calls.

    Never blocks the tool call and prints nothing, whatever goes wrong.
    """
    try:
        data = json.load(stdin or sys.stdin)
        if data.get('tool_name') != 'Bash':
            return 0
        found = prompts_in(data.get('tool_input', {}).get('command', ''))
        if not found:
            return 0
        project = repo_root(Path(data.get('cwd') or os.getcwd()))
        sender = sender_name()
        for to, text in found:
            append(project, Message(datetime.now(timezone.utc), sender, to, text, 'hook'))
    except Exception:  # a broken hook must never stop Claude
        pass
    return 0
