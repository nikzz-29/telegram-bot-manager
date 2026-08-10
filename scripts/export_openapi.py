"""Dump the API's OpenAPI schema to a file.

The Mini App's typed client is generated from this, so it has to be producible
without a running server — `task client` writes the schema and regenerates the
TypeScript in one step, and CI can diff the result to catch a drifted client.

DECISION: written to `apps/miniapp/openapi.json` and committed. A generated
client whose source schema is not in the tree cannot be reviewed, and a reviewer
seeing `openapi.json` move in a diff knows the panel's contract changed.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

DEFAULT_TARGET = Path("apps/miniapp/openapi.json")


def dump(target: Path) -> Path:
    # Imported lazily: this module is also the CLI entrypoint, and importing the
    # app pulls in the whole dependency graph.
    from api.app import create_app

    schema = create_app().openapi()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    written = dump(target)
    schema = json.loads(written.read_text(encoding="utf-8"))
    operations = sum(len(methods) for methods in schema["paths"].values())
    print(f"{written}: {len(schema['paths'])} paths, {operations} operations")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
