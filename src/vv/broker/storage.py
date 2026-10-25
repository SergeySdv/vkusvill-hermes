import fcntl
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

from vv.errors import Code, VVError


class Vault:
    def __init__(self, directory: Path, key: str):
        if any(parent.is_symlink() for parent in (directory, *directory.parents)):
            raise ValueError("Vault ancestors must not be symlinks.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Vault directory must be owner-only (0700), not a symlink.")
        self.directory = directory
        self.lock_timeout = 5
        self.cipher = Fernet(key.encode())
        for name in ("vault.sqlite3", "lock"):
            descriptor = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(descriptor)
            os.close(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                raise ValueError("Unsafe vault file.")
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(name TEXT PRIMARY KEY, payload BLOB NOT NULL, expires REAL NOT NULL)"
            )

    @contextmanager
    def transaction(self):
        descriptor = os.open(self.directory / "lock", os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "w") as lock:
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise VVError(
                            Code.STORAGE_ERROR, "Vault busy; request not executed."
                        ) from None
                    time.sleep(0.02)
            connection = sqlite3.connect(self.directory / "vault.sqlite3")
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def get(self, connection, name):
        row = connection.execute(
            "SELECT payload, expires FROM records WHERE name=?", (name,)
        ).fetchone()
        if row is None or row[1] <= time.time():
            return None
        value = json.loads(self.cipher.decrypt(row[0]))
        if value["name"] != name:
            raise ValueError("Vault binding mismatch.")
        return value["data"]

    def put(self, connection, name, data, ttl=600):
        encrypted = self.cipher.encrypt(json.dumps({"name": name, "data": data}).encode())
        connection.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
            (name, encrypted, time.time() + ttl if ttl is not None else float("inf")),
        )

    def delete(self, connection, name):
        connection.execute("DELETE FROM records WHERE name=?", (name,))

    def prune(self, connection):
        connection.execute("DELETE FROM records WHERE expires<=?", (time.time(),))

    def snapshot(self):
        with self.transaction() as connection:
            with sqlite3.connect(":memory:") as snapshot:
                connection.backup(snapshot)
                if snapshot.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("Vault integrity check failed.")
                records = []
                for name, payload, expires in snapshot.execute("SELECT * FROM records"):
                    value = json.loads(self.cipher.decrypt(payload))
                    if value["name"] != name:
                        raise ValueError("Vault binding mismatch.")
                    if name in ("identity", "account", "public_context"):
                        records.append(
                            [name, payload.decode(), None if expires == float("inf") else expires]
                        )
                return records
