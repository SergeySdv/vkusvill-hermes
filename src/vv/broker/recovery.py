import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet

from vv.auth import private_read
from vv.broker.service import Broker, Settings
from vv.broker.storage import Vault


def private_write(path, payload):
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Unsafe destination parent.")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def archive_payload(config_path):
    settings = Settings.model_validate(private_read(config_path))
    broker = Broker(settings)
    return {
        "schema_version": 1,
        "created_at": time.time(),
        "settings": settings.model_dump(mode="json"),
        "records": broker.vault.snapshot(),
    }


def backup(config_path, destination, recipient):
    if not recipient.startswith("age1") or not recipient.isalnum():
        raise ValueError("Use an age public recovery recipient.")
    payload = json.dumps(archive_payload(config_path)).encode()
    result = subprocess.run(
        ["age", "--encrypt", "--recipient", recipient],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    private_write(destination, result.stdout)


def materialize(payload, destination, *, rotate=False):
    if not destination.is_absolute():
        raise ValueError("Use an absolute recovery destination.")
    if payload.get("schema_version") != 1 or destination.exists() or destination.is_symlink():
        raise ValueError("Restore requires a new directory and a supported archive.")
    parent = destination.parent
    if not parent.is_dir() or any(item.is_symlink() for item in (parent, *parent.parents)):
        raise ValueError("Unsafe recovery parent.")
    original = Settings.model_validate(payload["settings"])
    cipher = Fernet(original.encryption_key.encode())
    records = {}
    for name, encrypted, expires in payload["records"]:
        value = json.loads(cipher.decrypt(encrypted.encode()))
        if (
            name not in ("identity", "account", "public_context")
            or name in records
            or value["name"] != name
        ):
            raise ValueError("Invalid recovery record.")
        records[name] = (value["data"], expires)
    if records.get("identity", (None,))[0] != {
        "owner_id": original.owner_id,
        "bot_id": original.bot_token.split(":", 1)[0],
    }:
        raise ValueError("Recovery identity mismatch.")
    stage = Path(tempfile.mkdtemp(prefix=".vv-recovery-", dir=parent))
    try:
        values = original.model_dump()
        if rotate:
            values.update(
                encryption_key=Fernet.generate_key().decode(), bridge_key=secrets.token_urlsafe(32)
            )
        vault = Vault(stage / "vault", values["encryption_key"])
        with vault.transaction() as connection:
            for name, (data, expires) in records.items():
                vault.put(
                    connection, name, data, ttl=None if expires is None else expires - time.time()
                )
        candidate = Settings(**{**values, "vault_directory": stage / "vault"})
        Broker(candidate).ready()
        candidate.vault_directory = destination / "vault"
        private_write(stage / "broker.json", candidate.model_dump_json().encode())
        private_write(
            stage / "bridge.json", json.dumps({"bridge_key": candidate.bridge_key}).encode()
        )
        os.rename(stage, destination)
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def restore(archive, identity_file, destination):
    descriptor = os.open(identity_file, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Recovery identity must be owner-only.")
    result = subprocess.run(
        ["age", "--decrypt", "--identity", str(identity_file), str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=30,
    )
    materialize(json.loads(result.stdout), destination)


def prepare(seed_file, destination, image, *, local_image=False):
    if not destination.is_absolute():
        raise ValueError("Use an absolute bundle destination.")
    if destination.is_symlink() or any(part.is_symlink() for part in destination.parents):
        raise ValueError("Unsafe bundle destination.")
    if not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", image) and not (
        local_image and re.fullmatch(r"sha256:[a-f0-9]{64}", image)
    ):
        raise ValueError("An immutable reviewed image digest is required.")
    seed = private_read(seed_file)
    if set(seed) != {"public_origin", "owner_id", "bot_token"}:
        raise ValueError("Only an origin and verified owner/bot identity are accepted.")
    settings = Settings(
        **seed,
        bridge_key=secrets.token_urlsafe(32),
        encryption_key=Fernet.generate_key().decode(),
        vault_directory=Path("/var/lib/vv-auth"),
    )
    if settings.public_origin != "https://vv-jarvis.buzzersteam.net":
        raise ValueError("This pilot targets only the reviewed Jarvis hostname.")
    manifest = {
        "schema_version": 1,
        "target": "jarvis",
        "host": "hermes-research-01",
        "image": image,
        "public_origin": settings.public_origin,
        "owner_id": settings.owner_id,
        "bot_id": settings.bot_token.split(":", 1)[0],
    }
    if destination.exists():
        if destination.is_symlink() or destination.stat().st_mode & 0o077:
            raise ValueError("Unsafe existing bundle.")
        previous = Settings.model_validate(private_read(destination / "broker.json"))
        if private_read(destination / "manifest.json") != manifest or any(
            getattr(previous, field) != value for field, value in seed.items()
        ):
            raise ValueError("Deployment identity or image changed; explicit review required.")
        if private_read(destination / "bridge.json") != {"bridge_key": previous.bridge_key}:
            raise ValueError("Bridge credential mismatch.")
        return
    stage = Path(tempfile.mkdtemp(prefix=".vv-prepare-", dir=destination.parent))
    try:
        private_write(stage / "broker.json", settings.model_dump_json().encode())
        private_write(
            stage / "bridge.json", json.dumps({"bridge_key": settings.bridge_key}).encode()
        )
        private_write(stage / "manifest.json", json.dumps(manifest).encode())
        (stage / "vault").mkdir(mode=0o700)
        os.rename(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(
        description="Offline administrator recovery; never run in Hermes"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("prepare")
    initialize.add_argument("--seed-file", type=Path, required=True)
    initialize.add_argument("--directory", type=Path, required=True)
    initialize.add_argument("--image", required=True)
    initialize.add_argument(
        "--local-image",
        action="store_true",
        help="Unpublished pilot only: immutable local Docker image ID",
    )
    save = commands.add_parser("backup")
    save.add_argument("--config", type=Path, required=True)
    save.add_argument("--output", type=Path, required=True)
    save.add_argument("--recipient", required=True)
    load = commands.add_parser("restore")
    load.add_argument("--archive", type=Path, required=True)
    load.add_argument("--identity-file", type=Path, required=True)
    load.add_argument("--directory", type=Path, required=True)
    rotate = commands.add_parser("rotate-copy")
    rotate.add_argument("--config", type=Path, required=True)
    rotate.add_argument("--directory", type=Path, required=True)
    rotate.add_argument("--offline", required=True, action="store_true")
    menu = commands.add_parser("menu")
    menu.add_argument("--config", type=Path, required=True)
    menu.add_argument("--action", choices=("status", "enable", "restore"), required=True)
    args = parser.parse_args()
    try:
        if args.command == "menu":
            from vv.broker.menu import configure

            print(json.dumps(configure(args.config, args.action)))
            return
        elif args.command == "prepare":
            prepare(args.seed_file, args.directory, args.image, local_image=args.local_image)
        elif args.command == "backup":
            backup(args.config, args.output, args.recipient)
        elif args.command == "restore":
            restore(args.archive, args.identity_file, args.directory)
        else:
            materialize(archive_payload(args.config), args.directory, rotate=True)
    except Exception:
        parser.exit(1, "Recovery failed; source unchanged, details suppressed.\n")
    print(json.dumps({"ok": True, "operation": args.command, "live_modified": False}))


if __name__ == "__main__":
    main()
