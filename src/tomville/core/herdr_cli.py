"""The herdr CLI contract shared by subprocess callers and the CI help check."""
import re

# Only 0.9.5 has been verified. Widen after testing another stable version.
TESTED_VERSIONS = ((0, 9, 5), (0, 9, 5))
TESTED_RANGE = '–'.join('.'.join(map(str, v)) for v in TESTED_VERSIONS)

# command: (number of leading positional arguments, option: takes a value).
# Agent CLI arguments after `--` are deliberately outside herdr's contract.
CALLS = {
    ('--version',): (0, {}),
    ('agent', 'list'): (0, {}),
    ('agent', 'rename'): (2, {}),
    ('agent', 'prompt'): (2, {'--wait': False, '--timeout': True}),
    ('agent', 'send-keys'): (2, {}),
    ('agent', 'start'): (1, {'--kind': True, '--pane': True, '--timeout': True}),
    ('agent', 'explain'): (1, {}),
    ('pane', 'list'): (0, {}),
    ('pane', 'read'): (1, {'--source': True, '--lines': True}),
    ('pane', 'process-info'): (0, {'--pane': True}),
    ('pane', 'run'): (2, {}),
    ('pane', 'close'): (1, {}),
    ('pane', 'split'): (1, {'--direction': True, '--cwd': True, '--no-focus': False}),
    ('tab', 'list'): (0, {}),
    ('tab', 'create'): (0, {'--cwd': True, '--label': True, '--no-focus': False}),
    ('tab', 'close'): (1, {}),
    ('worktree', 'create'): (0, {'--branch': True, '--cwd': True, '--label': True, '--no-focus': False}),
    ('worktree', 'open'): (0, {'--path': True, '--cwd': True, '--label': True, '--no-focus': False}),
    ('integration', 'status'): (0, {}),
}


def argv(*args):
    """Reject undeclared commands/options so production and CI cannot drift."""
    command = tuple(args[:1] if args[:1] == ('--version',) else args[:2])
    if command not in CALLS:
        raise ValueError(f'Undeclared herdr command: {command}')
    positional, options = CALLS[command]
    rest = list(args[len(command) + positional:])
    while rest:
        option = rest.pop(0)
        if option == '--':
            break
        if option not in options:
            raise ValueError(f'Undeclared herdr option for {command}: {option}')
        if options[option]:
            if not rest:
                raise ValueError(f'Missing value for herdr {option}')
            rest.pop(0)
    return ['herdr', *args]


def tested_version(text):
    match = re.fullmatch(r'herdr\s+(\d+)\.(\d+)\.(\d+)\s*', text.strip())
    return bool(match and TESTED_VERSIONS[0] <= tuple(map(int, match.groups())) <= TESTED_VERSIONS[1])


def usage_hint(error):
    """Usage/argument errors take precedence over agent detection advice."""
    text = str(error)
    if not re.search(r'(?im)^\s*usage:|unexpected argument|unrecognized (?:option|argument|subcommand)|unknown (?:option|argument|subcommand)|required arguments?|missing (?:required )?argument|invalid (?:value|argument)', text):
        return None
    command = re.search(r'herdr\s+([a-z-]+)(?:\s+([a-z-]+))?', text, re.I)
    name = 'herdr ' + ' '.join(p for p in command.groups() if p) if command else 'herdr command'
    return f'tmv and herdr disagree on `{name}`; check `herdr --version` (tested {TESTED_RANGE})'
