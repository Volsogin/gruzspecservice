"""Write the OpenAPI contract to docs/openapi.json (`make openapi`)."""

from __future__ import annotations

import json

from app.core.config import REPO_DIR, Settings
from app.main import create_app


def main() -> None:
    app = create_app(Settings(_env_file=None, run_background_tasks=False, log_json=False))
    target = REPO_DIR / "docs" / "openapi.json"
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {target.relative_to(REPO_DIR)} ({len(app.openapi()['paths'])} paths)")


if __name__ == "__main__":
    main()
