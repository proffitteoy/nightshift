from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def save_json(data: Any, target_file: Path) -> Path:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target_file.with_name(f"{target_file.name}.{uuid4().hex}.tmp")
    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_file, target_file)
    return target_file


def read_json(source_file: Path) -> Any:
    with source_file.open("r", encoding="utf-8") as file:
        return json.load(file)
