"""CI only: check stable herdr's CLI without starting panes or agents."""
import re
import subprocess

from tomville.core.herdr_cli import CALLS


def check(run=subprocess.run):
    for command, (_, options) in CALLS.items():
        args = ['herdr', *command]
        if command != ('--version',):
            args.append('--help')
        result = run(args, capture_output=True, text=True, timeout=30, check=True)
        help_text = result.stdout + result.stderr
        for option in options:
            if not re.search(r'(?<![\w-])' + re.escape(option) + r'(?![\w-])', help_text):
                raise ValueError(f'{" ".join(args)} no longer documents {option}')
        print(f'OK: {" ".join(args)}')


if __name__ == '__main__':
    check()
