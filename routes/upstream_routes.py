"""Cached public upstream history for users; deliberate network reads for admins."""
from fastapi import APIRouter, HTTPException, Query, Request
from core.middleware import require_admin
from src.auth_helpers import require_user
from src.upstream_updates import UpdateTracker, UpdateError


def setup_upstream_routes(tracker=None):
    tracker = tracker or UpdateTracker()
    router = APIRouter(prefix="/api/upstream")

    def access(request, project_id=None, online=False):
        require_user(request)
        if online:
            require_admin(request)
        if project_id is not None:
            try:
                tracker.project(project_id)
            except KeyError:
                raise HTTPException(404, "Project is not tracked")

    async def execute(operation):
        try:
            return await operation
        except UpdateError as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.get("")
    async def projects(request: Request):
        access(request)
        try:
            require_admin(request)
            can_check = True
        except HTTPException:
            can_check = False
        return {"projects": [tracker.view(key) for key in tracker.projects], "can_check": can_check}

    @router.post("/{project_id}/check")
    async def check(project_id: str, request: Request):
        access(request, project_id, online=True)
        return await execute(tracker.check(project_id))

    @router.get("/{project_id}/history")
    @router.post("/{project_id}/history")
    async def history(project_id: str, request: Request, page: int = Query(1, ge=1, le=10000)):
        online = request.method == "POST"
        access(request, project_id, online=online)
        return await execute(tracker.history(project_id, page, online=online))

    @router.get("/{project_id}/commits/{sha}")
    @router.post("/{project_id}/commits/{sha}")
    async def detail(project_id: str, sha: str, request: Request):
        online = request.method == "POST"
        access(request, project_id, online=online)
        return await execute(tracker.detail(project_id, sha, online=online))

    return router
