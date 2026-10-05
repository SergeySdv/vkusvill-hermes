import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from vv.errors import Code, VVError
from vv.models import Basket, Request

NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def validate_name(name: str) -> str:
    if not NAME.fullmatch(name):
        raise VVError(Code.INVALID_INPUT, "Use 1–64 letters, digits, underscores or hyphens.")
    return name


def checked_hash(profile: str, basket: Basket) -> str:
    value = {
        "schema_version": 1,
        "profile": profile,
        "name": basket.name,
        "revision": basket.revision,
        "request": basket.request.model_dump(mode="json"),
        "report": basket.report.model_dump(mode="json") if basket.report else None,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class Store:
    def __init__(self, directory: Path, profile: str = "default"):
        self.directory = directory
        self.profile = validate_name(profile)

    @contextmanager
    def transaction(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / "baskets.sqlite3"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        connection = sqlite3.connect(path, timeout=5)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS baskets "
                "(profile TEXT, name TEXT, body TEXT NOT NULL, PRIMARY KEY (profile, name))"
            )
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load(self, connection: sqlite3.Connection, name: str) -> Basket:
        validate_name(name)
        row = connection.execute(
            "SELECT body FROM baskets WHERE profile=? AND name=?", (self.profile, name)
        ).fetchone()
        if row is None:
            raise VVError(Code.NOT_FOUND, "Basket not found in this profile.")
        return Basket.model_validate_json(row[0])

    def save(self, connection: sqlite3.Connection, basket: Basket) -> None:
        connection.execute(
            "INSERT INTO baskets(profile,name,body) VALUES(?,?,?) "
            "ON CONFLICT(profile,name) DO UPDATE SET body=excluded.body",
            (self.profile, basket.name, basket.model_dump_json()),
        )

    def import_request(self, name: str, request: Request) -> Basket:
        validate_name(name)
        with self.transaction() as connection:
            try:
                old = self.load(connection, name)
            except VVError as error:
                if error.code != Code.NOT_FOUND:
                    raise
                revision = 1
            else:
                revision = old.revision + 1
            basket = Basket(name=name, revision=revision, request=request)
            self.save(connection, basket)
        return basket

    def show(self, name: str) -> Basket:
        with self.transaction() as connection:
            return self.load(connection, name)
