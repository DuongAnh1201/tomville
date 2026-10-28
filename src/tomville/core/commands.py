"""Small subprocess boundary shared by the one-shot CLI commands."""
import subprocess

from tomville.core.herdr_cli import argv


def run_command(args, project, *, timeout=30):
    if args[0] == 'herdr':
        args = argv(*args[1:])
    result = subprocess.run(args, cwd=project, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f'{args[0]} failed'
        if args[0] == 'herdr':
            detail = ' '.join(args[:3]) + ': ' + detail
        raise OSError(detail)
    return result.stdout.strip()
