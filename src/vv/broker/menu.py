"""Owner-scoped menu changes with private compare-before-restore metadata."""

from vv.auth import private_read
from vv.broker.service import Broker, Settings


def configure(config, action):
    from vv.broker.recovery import private_write

    broker = Broker(Settings.model_validate(private_read(config)))
    settings = broker.settings
    path = settings.vault_directory / "telegram-menu.json"
    identity = {"owner_id": settings.owner_id, "bot_id": settings.bot_token.split(":", 1)[0]}
    desired = {"type": "web_app", "text": "ВкусВилл", "web_app": {"url": settings.public_origin}}

    def request(method, body):
        with broker.http_factory() as client:
            response = client.post(
                "https://api.telegram.org/bot" + settings.bot_token + "/" + method,
                json={"chat_id": settings.owner_id, **body},
            )
            response.raise_for_status()
            value = response.json()
            if value.get("ok") is not True:
                raise ValueError("Menu request rejected.")
            return value["result"]

    with broker.vault.transaction():
        current = request("getChatMenuButton", {})
        if action == "status":
            return {"ok": True, "configured": current == desired}
        if path.exists():
            previous = private_read(path)
            if previous["identity"] != identity or previous["installed"] != desired:
                raise ValueError("Menu identity mismatch.")
        elif action == "enable":
            if current == desired:
                raise ValueError("Existing menu without rollback metadata.")
            import json

            previous = {"identity": identity, "previous": current, "installed": desired}
            private_write(path, json.dumps(previous).encode())
        else:
            raise ValueError("No saved menu to restore.")
        if current not in (previous["previous"], desired):
            raise ValueError("Menu changed independently; refusing overwrite.")
        target = desired if action == "enable" else previous["previous"]
        if current != target:
            if request("setChatMenuButton", {"menu_button": target}) is not True:
                raise ValueError("Menu update failed.")
        return {"ok": True, "action": action, "configured": target == desired}
