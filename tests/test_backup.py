#!/usr/bin/env python3
"""Auto-test for pg_dump backup script (Task 6)."""
import subprocess
import sys
import os
import glob
import time
import pytest

BACKUP_DIR = "/home/stas/backups"
BACKUP_SCRIPT = "/home/stas/fashion-bot/backup.sh"

# These tests check host filesystem paths — skip when running inside Docker
_IN_DOCKER = os.path.isfile("/.dockerenv")
_skip_in_docker = pytest.mark.skipif(_IN_DOCKER, reason="backup.sh is on host, not in Docker container")


@_skip_in_docker
def test_backup_script_exists():
    assert os.path.isfile(BACKUP_SCRIPT), f"FAIL: backup.sh не найден: {BACKUP_SCRIPT}"
    assert os.access(BACKUP_SCRIPT, os.X_OK), f"FAIL: backup.sh не исполняемый"
    print("PASS: backup.sh существует и исполняемый")


@_skip_in_docker
def test_backup_runs():
    before = set(glob.glob(f"{BACKUP_DIR}/fashion_*.sql.gz"))
    result = subprocess.run(
        ["bash", BACKUP_SCRIPT],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"FAIL: backup.sh завершился с кодом {result.returncode}")
        print(f"stderr: {result.stderr[:200]}")
        return False

    after = set(glob.glob(f"{BACKUP_DIR}/fashion_*.sql.gz"))
    new_files = after - before
    if not new_files:
        print(f"FAIL: бэкап не создал новый файл в {BACKUP_DIR}")
        return False

    backup_file = list(new_files)[0]
    size = os.path.getsize(backup_file)
    if size < 100:
        print(f"FAIL: файл бэкапа слишком маленький ({size} bytes): {backup_file}")
        return False

    print(f"PASS: бэкап создан: {os.path.basename(backup_file)} ({size} bytes)")
    print(f"stdout: {result.stdout.strip()}")
    return True


@_skip_in_docker
def test_old_backups_cleanup():
    # Verify find -mtime +7 -delete line is present in script
    with open(BACKUP_SCRIPT) as f:
        content = f.read()
    assert "mtime +7" in content or "mtime+7" in content, \
        "FAIL: cleanup старых бэкапов не настроен в backup.sh"
    print("PASS: cleanup бэкапов старше 7 дней присутствует в скрипте")


if __name__ == "__main__":
    test_backup_script_exists()
    ok = test_backup_runs()
    test_old_backups_cleanup()
    if ok:
        print("Все тесты PASS")
    else:
        sys.exit(1)
