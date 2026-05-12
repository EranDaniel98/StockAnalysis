"""Export the FastAPI OpenAPI schema to a JSON file.

Phase 2 consumes this with openapi-typescript to generate Next.js client
types. Run after every endpoint shape change:

    uv run python -m scripts.export_openapi --out api-openapi.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.api.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("api-openapi.json"),
        help="Output JSON path (default: ./api-openapi.json)",
    )
    args = parser.parse_args()

    app = create_app()
    schema = app.openapi()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    paths = list(schema.get("paths", {}).keys())
    print(f"wrote {args.out} ({len(paths)} paths)", file=sys.stderr)


if __name__ == "__main__":
    main()
