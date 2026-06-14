from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .dreamina import DreaminaService
from .pool import DreaminaPool

app = FastAPI(title="Ainong Local API", version="0.1.0")
pool = DreaminaPool()
dreamina = DreaminaService(pool)


class TaskRequest(BaseModel):
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)


@app.on_event("startup")
def startup() -> None:
    pool.ensure()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/dreamina/accounts")
def list_accounts() -> dict[str, object]:
    return {"accounts": pool.list_accounts()}


@app.post("/v1/dreamina/login")
async def start_login() -> dict[str, object]:
    try:
        return await dreamina.start_login()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/dreamina/login/{session_id}/check")
async def check_login(session_id: str) -> dict[str, object]:
    try:
        return await dreamina.check_login(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/dreamina/tasks")
async def submit_task(request: TaskRequest) -> dict[str, object]:
    try:
        return await dreamina.submit_task(request.command, request.args)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/dreamina/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, object]:
    try:
        return await dreamina.get_task(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
