from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from linkwatch.audit import audit_site
from linkwatch.fetch import assess
from linkwatch.urls import parse_http_url

logger = logging.getLogger(__name__)
app = FastAPI(title="Linkwatch")
JOBS: dict[str, dict] = {}
# asyncio only holds a weak reference to a running task, so an audit that nothing
# else refers to can be garbage-collected mid-run and leave its job stuck on
# "running" forever. Keep a strong reference until it finishes.
RUNNING: set[asyncio.Task] = set()
TEMPLATE = Path(__file__).parent / "templates" / "index.html"


class AuditIn(BaseModel):
    url: str | None = None
    sample: bool = False
    max_pages: int | None = Field(default=None, ge=1)
    max_links: int | None = Field(default=None, ge=1, le=20000)
    use_browser: bool = False
    use_sitemap: bool = True


@app.get("/")
def index() -> FileResponse:
    return FileResponse(TEMPLATE)


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.post("/api/audits")
async def start_audit(body: AuditIn) -> dict[str, str]:
    url = ""
    if not body.sample:
        try:
            url = parse_http_url(body.url or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state, _reason = assess(url)
        if state == "denied":
            raise HTTPException(
                status_code=400,
                detail="That URL isn't on the public web, so Linkwatch won't crawl it.",
            )
    job_id = uuid4().hex
    JOBS[job_id] = {"status": "queued", "progress": "Queued", "report": None, "error": None}
    task = asyncio.create_task(_run(job_id, url, body))
    RUNNING.add(task)
    task.add_done_callback(RUNNING.discard)
    return {"id": job_id}


@app.get("/api/audits/{job_id}")
def get_audit(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No audit with that id.")
    return job


async def _run(job_id: str, url: str, body: AuditIn) -> None:
    job = JOBS[job_id]
    job["status"] = "running"

    def progress(message: str) -> None:
        job["progress"] = message

    try:
        report = await asyncio.wait_for(
            audit_site(
                url,
                sample=body.sample,
                max_pages=body.max_pages,
                max_links=body.max_links,
                use_browser=body.use_browser,
                use_sitemap=body.use_sitemap,
                on_progress=progress,
            ),
            timeout=7200,
        )
    except ValueError as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        return
    except TimeoutError:
        job["status"] = "error"
        job["error"] = "The audit ran past two hours and stopped. Try fewer pages."
        return
    except Exception:
        logger.exception("audit failed")
        job["status"] = "error"
        job["error"] = "The audit failed before it could finish."
        return
    job["report"] = report.to_dict()
    job["status"] = "done"
    job["progress"] = "Finished"


def main() -> None:
    import uvicorn

    uvicorn.run("linkwatch.app:app", host="127.0.0.1", port=8000)
