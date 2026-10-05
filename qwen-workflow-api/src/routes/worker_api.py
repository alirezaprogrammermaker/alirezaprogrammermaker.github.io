from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from authz.auth import require_worker_key
from schemas.worker import ClaimRequest, CompleteRequest
from services import worker_jobs
from services.completions import job_to_openai_shape

router = APIRouter(prefix="/v1/worker", tags=["worker"])


@router.post("/claim", dependencies=[Depends(require_worker_key)])
async def claim(body: ClaimRequest, request: Request):
    """GHA poller: read-only peek when empty (saves D1 writes)."""
    payload = await worker_jobs.claim_next(request.scope["env"], body.worker_id)
    if not payload:
        return Response(status_code=204)
    return payload


@router.post("/jobs/{job_id}/complete", dependencies=[Depends(require_worker_key)])
async def complete(job_id: str, body: CompleteRequest, request: Request):
    row = await worker_jobs.complete_job(request.scope["env"], job_id, body)
    return job_to_openai_shape(row)
