import json
from uuid import uuid4

import typer
from pydantic import BaseModel

from vv import __version__
from vv.errors import VVError


def emit(data=None, *, error: VVError | None = None, warnings: list[str] | None = None):
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    typer.echo(
        json.dumps(
            {
                "schema_version": 1,
                "ok": error is None,
                "data": data if error is None else None,
                "error": (
                    {
                        "code": error.code.value,
                        "message": error.message,
                        "retryable": error.retryable,
                    }
                    if error
                    else None
                ),
                "warnings": warnings or [],
                "meta": {"cli_version": __version__, "request_id": str(uuid4())},
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )
