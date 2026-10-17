import hmac
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.schemas import EditBallRequest, EventRequest, MatchCreate, MatchDetailsUpdate, MatchDocument, UndoRequest
from app.services.match_service import MatchService
from app.services.pdf_export import render_scorecard_pdf

router = APIRouter(prefix="/api")


def get_service(request: Request) -> MatchService:
    return request.app.state.match_service


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/matches")
def list_matches(
    status: Literal["setup", "in_progress", "completed"] | None = None,
    service: MatchService = Depends(get_service),
) -> list[dict]:
    return service.list_matches(status)


@router.post("/matches", status_code=201)
def create_match(body: MatchCreate, service: MatchService = Depends(get_service)) -> dict:
    return service.create_match(body.model_dump())


@router.post("/matches/import", status_code=201)
async def import_match(request: Request, service: MatchService = Depends(get_service)) -> dict:
    limit = request.app.state.settings.max_import_bytes
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(413, "Import file is too large")
    try:
        doc = MatchDocument.model_validate(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "File is not valid JSON")
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid match file: {exc.errors(include_url=False)[0]['msg']}")
    return service.import_match(doc.model_dump(mode="json"))


@router.get("/matches/{match_id}")
def get_match(match_id: str, service: MatchService = Depends(get_service)) -> dict:
    return service.get_view(match_id)


@router.delete("/matches/{match_id}", status_code=204)
def delete_match(
    match_id: str,
    request: Request,
    x_delete_password: str | None = Header(default=None),
    service: MatchService = Depends(get_service),
) -> Response:
    expected = request.app.state.settings.delete_password
    if not x_delete_password or not hmac.compare_digest(x_delete_password.encode(), expected.encode()):
        raise HTTPException(403, "Incorrect delete password")
    service.delete_match(match_id)
    return Response(status_code=204)


@router.put("/matches/{match_id}/details")
def update_details(match_id: str, body: MatchDetailsUpdate, service: MatchService = Depends(get_service)) -> dict:
    return service.update_details(match_id, body.model_dump())


@router.post("/matches/{match_id}/events")
def add_event(match_id: str, body: EventRequest, service: MatchService = Depends(get_service)) -> dict:
    return service.add_event(match_id, body.event.model_dump(exclude_none=True), body.op_id)


@router.put("/matches/{match_id}/events/{index}")
def edit_ball(match_id: str, index: int, body: EditBallRequest, service: MatchService = Depends(get_service)) -> dict:
    return service.edit_ball(match_id, index, body.event.model_dump(exclude_none=True), body.op_id)


@router.post("/matches/{match_id}/undo")
def undo(match_id: str, body: UndoRequest | None = None, service: MatchService = Depends(get_service)) -> dict:
    return service.undo(match_id, body.op_id if body else None)


@router.post("/matches/{match_id}/cancel-retire")
def cancel_retire(match_id: str, body: UndoRequest | None = None, service: MatchService = Depends(get_service)) -> dict:
    return service.cancel_retirement(match_id, body.op_id if body else None)


@router.get("/matches/{match_id}/scorecard")
def scorecard(match_id: str, service: MatchService = Depends(get_service)) -> dict:
    return service.scorecard(match_id)


@router.get("/matches/{match_id}/export.pdf")
def export_pdf(match_id: str, service: MatchService = Depends(get_service)) -> Response:
    scorecard = service.scorecard(match_id)
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", scorecard["match"]["name"]).strip("-")[:40] or "match"
    return Response(
        render_scorecard_pdf(scorecard),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}-{match_id}.pdf"'},
    )


@router.get("/matches/{match_id}/export")
def export_match(match_id: str, service: MatchService = Depends(get_service)) -> JSONResponse:
    doc = service.export_match(match_id)
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", doc["name"]).strip("-")[:40] or "match"
    return JSONResponse(
        doc,
        headers={"Content-Disposition": f'attachment; filename="{filename}-{doc["id"]}.json"'},
    )
