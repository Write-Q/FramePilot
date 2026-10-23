"""Technical video inspection and explicit manual findings; no vision-model claims."""
from fastapi.responses import FileResponse
from app.production.inspection import InspectionService
from app.production.inspection_contracts import CreateInspection, ManualReview


def install_inspection_routes(router, invoke):
    base = '/projects/{project_id}/storyboards/{storyboard_id}/video-runs/{run_id}/inspections'

    @router.post(base, status_code=201)
    def inspect(project_id: str, storyboard_id: str, run_id: str, request: CreateInspection):
        return invoke(lambda store: InspectionService(store).create(project_id, storyboard_id, run_id, request))

    @router.get(base)
    def reports(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: InspectionService(store).list(project_id, storyboard_id, run_id))

    @router.get(base + '/{inspection_id}/frames/{index}')
    def frame(project_id: str, storyboard_id: str, run_id: str, inspection_id: str, index: int):
        path, mime = invoke(lambda store: InspectionService(store).frame(project_id, storyboard_id, run_id, inspection_id, index))
        return FileResponse(path, media_type=mime, headers={'X-Content-Type-Options':'nosniff', 'Cache-Control':'private, max-age=3600'})

    @router.post(base + '/{inspection_id}/notes', status_code=201)
    def note(project_id: str, storyboard_id: str, run_id: str, inspection_id: str, request: ManualReview):
        return invoke(lambda store: InspectionService(store).note(project_id, storyboard_id, run_id, inspection_id, request))
