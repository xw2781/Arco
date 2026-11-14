from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from app_server import config
from app_server.schemas.workflow import WorkflowLoadRequest, WorkflowSaveAsRequest, WorkflowSaveRequest


def _sanitize_workflow_filename(name: str) -> str:
    out = config.encode_filename_segment((name or "").strip())
    return out.strip() or "workflow"


def save_workflow(req: WorkflowSaveRequest, workflow_dir: str, workflow_ext: str) -> Dict[str, Any]:
    name = _sanitize_workflow_filename(req.name or "workflow")
    os.makedirs(workflow_dir, exist_ok=True)
    path = os.path.join(workflow_dir, f"{name}{workflow_ext}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(req.data, f, ensure_ascii=True, indent=2)

    prev = req.prev_path
    if prev:
        try:
            prev_path = Path(prev).resolve()
            new_path = Path(path).resolve()
            root = Path(workflow_dir).resolve()
            if prev_path != new_path and str(prev_path).startswith(str(root) + os.sep):
                if prev_path.exists():
                    prev_path.unlink()
        except Exception:
            pass

    return {"ok": True, "path": path}


def save_workflow_as(req: WorkflowSaveAsRequest, workflow_dir: str, workflow_ext: str) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(400, "Missing path")
    p = Path(req.path)
    if not p.is_absolute():
        p = Path(workflow_dir) / p
    if p.suffix.lower() not in (".json", workflow_ext):
        p = p.with_suffix(workflow_ext)
    os.makedirs(p.parent, exist_ok=True)
    with open(str(p), "w", encoding="utf-8") as f:
        json.dump(req.data, f, ensure_ascii=True, indent=2)
    return {"ok": True, "path": str(p)}


def get_workflow_default_dir(workflow_dir: str) -> Dict[str, Any]:
    os.makedirs(workflow_dir, exist_ok=True)
    return {"path": workflow_dir}


def get_template_default_dir() -> Dict[str, Any]:
    template_dir = config.get_template_dir()
    os.makedirs(template_dir, exist_ok=True)
    return {"path": template_dir}


def load_workflow(req: WorkflowLoadRequest, workflow_dir: str, workflow_ext: str) -> Dict[str, Any]:
    if not req.path:
        raise HTTPException(400, "Missing path")
    p = Path(req.path)
    if not p.is_absolute():
        p = Path(workflow_dir) / p
    if p.suffix == "":
        p = p.with_suffix(workflow_ext)
    if not p.exists():
        raise HTTPException(404, f"Workflow not found: {p}")
    with open(str(p), "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"ok": True, "path": str(p), "data": data}
