"""Run one ClipForge controller per project, holding an OS lock until it exits."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def acquire(file):
    file.seek(0)
    if os.name == 'nt':
        import msvcrt
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
    else:
        import fcntl
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-dir', required=True, type=Path)
    parser.add_argument('--action', required=True, choices=['start', 'resume'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        parser.error('missing controller command')
    args.project_dir.mkdir(parents=True, exist_ok=True)
    with (args.project_dir / 'controller.lock').open('a+b') as lock:
        # Windows locks a byte range; ensure a byte exists before trying to lock it.
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b'0')
            lock.flush()
        if not acquire(lock):
            print('Controller already running for this project; request ignored.', flush=True)
            return 2
        status_path = args.project_dir / 'controller-status.json'
        status = {'action': args.action, 'status': 'running', 'started_at': time.time()}

        def save():
            temp = status_path.with_suffix('.tmp')
            temp.write_text(json.dumps(status), encoding='utf-8')
            os.replace(temp, status_path)

        save()
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, check=False)
            status.update(status='finished', exit_code=result.returncode, finished_at=time.time())
            return result.returncode
        except OSError as error:
            print(f'Controller could not start: {error}', file=sys.stderr, flush=True)
            status.update(status='failed_to_start', finished_at=time.time())
            return 1
        finally:
            save()


if __name__ == '__main__':
    raise SystemExit(main())
