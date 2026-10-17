"""Small subprocess boundary shared by the one-shot CLI commands."""
import subprocess


def run_command(args, project):
    result = subprocess.run(args, cwd=project, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise OSError(result.stderr.strip() or result.stdout.strip() or f'{args[0]} failed')
    return result.stdout.strip()
