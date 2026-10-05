import os
import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from typer.core import TyperGroup
from typer.exceptions import TyperException

from vv import __version__
from vv.application import Application
from vv.errors import Code, VVError
from vv.mcp_provider import MCPProvider
from vv.models import Request
from vv.output import emit
from vv.store import Store

JsonFlag = Annotated[bool, typer.Option("--json", help="JSON is the default output format.")]


class SafeGroup(TyperGroup):
    def main(self, *args, **kwargs):
        kwargs["standalone_mode"] = False
        try:
            return super().main(*args, **kwargs)
        except VVError as error:
            emit(error=error)
        except TyperException:
            emit(error=VVError(Code.INVALID_INPUT, "Invalid command or arguments; consult --help."))
        except ValidationError:
            emit(error=VVError(Code.INVALID_INPUT, "Input does not match the local schema."))
        except (OSError, sqlite3.Error):
            emit(error=VVError(Code.STORAGE_ERROR, "Could not access local input or storage."))
        except (ValueError, UnicodeError):
            emit(error=VVError(Code.INVALID_INPUT, "Input must be valid UTF-8 JSON."))
        except Exception:
            emit(error=VVError(Code.INTERNAL_ERROR, "Unexpected failure; raw details suppressed."))
        raise SystemExit(1)


app = typer.Typer(cls=SafeGroup, no_args_is_help=True, pretty_exceptions_enable=False)
product = typer.Typer()
basket = typer.Typer()
app.add_typer(product, name="product")
app.add_typer(basket, name="basket")


def application() -> Application:
    directory = Path(os.environ.get("VV_STATE_DIR", str(Path.home() / ".local/state/vv")))
    return Application(Store(directory, os.environ.get("VV_PROFILE", "default")), MCPProvider())


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    json_output: JsonFlag = False,
    version: Annotated[bool, typer.Option("--version", is_eager=True)] = False,
):
    if version:
        if json_output:
            emit({"version": __version__})
        else:
            typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def doctor(
    json_output: JsonFlag = False,
    live: Annotated[
        bool, typer.Option("--live", help="Test the public MCP with one search.")
    ] = False,
):
    service = application()
    with service.store.transaction():
        pass
    emit(
        {
            "storage": "ok",
            "profile": service.store.profile,
            "provider": "public_mcp",
            "network_checked": live,
            "auth": "not_configured",
            "link_creation_enabled": True,
            "live": service.provider.health() if live else None,
        },
        warnings=["PUBLIC_CATALOG: address availability and final delivery price are unknown."],
    )


@product.command()
def search(
    query: str,
    limit: Annotated[int, typer.Option(min=1, max=10)] = 5,
    page: Annotated[int, typer.Option(min=1, max=99999)] = 1,
    json_output: JsonFlag = False,
):
    emit(application().provider.search(query, limit, page))


@product.command()
def get(
    product_id: Annotated[int, typer.Argument(min=1, max=999999999)],
    json_output: JsonFlag = False,
):
    emit(application().provider.get(product_id))


@product.command()
def analogs(
    product_id: Annotated[int, typer.Argument(min=1, max=999999999)],
    json_output: JsonFlag = False,
):
    emit(application().provider.analogs(product_id))


@basket.command("import")
def import_basket(
    name: str,
    file: Annotated[Path, typer.Option("--file")],
    json_output: JsonFlag = False,
):
    with file.open("rb") as source:
        contents = source.read(1_048_577)
    if len(contents) > 1_048_576:
        raise VVError(Code.INVALID_INPUT, "Request exceeds 1 MiB.")
    request = Request.model_validate_json(contents)
    emit(
        application().import_request(name, request),
        warnings=["UNVERIFIED_INPUT: imported ids and human quantities are local intent only."],
    )


@basket.command()
def show(name: str, json_output: JsonFlag = False):
    emit(application().store.show(name))


@basket.command()
def check(
    name: str,
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
    json_output: JsonFlag = False,
):
    emit(
        application().check(name, refresh),
        warnings=[
            "PUBLIC_CATALOG: inspect blocking checks; stock and final delivery price are unknown."
            if refresh
            else "LOCAL_ONLY: use --refresh before requesting a link."
        ],
    )


@basket.command()
def link(
    name: str,
    checked_hash: Annotated[str, typer.Option("--checked-hash")],
    json_output: JsonFlag = False,
):
    emit(application().link(name, checked_hash))


def main():
    app()
