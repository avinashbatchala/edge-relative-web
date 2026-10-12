"""Regenerate checked-in schemas; frontend types are generated from OpenAPI."""

import json
from pathlib import Path
from typing import Union
from pydantic import TypeAdapter
from app.main import app
from app.contracts import StatusEvent, QuoteEvent, SnapshotEvent

root = Path(__file__).resolve().parents[1]
(root / "contracts" / "openapi.json").write_text(
    json.dumps(app.openapi(), indent=2) + "\n"
)
(root / "contracts" / "websocket.schema.json").write_text(
    json.dumps(
        TypeAdapter(Union[StatusEvent, QuoteEvent, SnapshotEvent]).json_schema(),
        indent=2,
    )
    + "\n"
)
