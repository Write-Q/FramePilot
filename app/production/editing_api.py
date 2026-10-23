"""Local postproduction routes; renders never invoke a model provider."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.production.editing_contracts import AcceptRequest, ExportRequest, TimelineRequest
from app.production.editing_service import EditingService


def install_editing_routes(router, invoke):
    base = '/projects/{project_id}/storyboards/{storyboard_id}/editing'

    @router.get(base)
    @router.get(base + '/timeline')
    def summary(project_id: str, storyboard_id: str, version: int | None = None):
        return invoke(lambda store: EditingService(store).list(project_id, storyboard_id, version))

    @router.post(base + '/timeline', status_code=201)
    def save(project_id: str, storyboard_id: str, request: TimelineRequest):
        return invoke(lambda store: EditingService(store).save(project_id, storyboard_id, request))

    @router.post(base + '/audio', status_code=201)
    async def upload_audio(project_id: str, storyboard_id: str, request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(413, '音频文件不能超过20MiB')
        mime = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        return await run_in_threadpool(invoke, lambda store: EditingService(store).upload_audio(
            project_id, storyboard_id, bytes(data), mime))

    @router.get(base + '/audio')
    def audio_list(project_id: str, storyboard_id: str):
        return invoke(lambda store: EditingService(store).list(project_id, storyboard_id)['audio'])

    @router.get(base + '/audio/{asset_id}/media')
    def audio(project_id: str, storyboard_id: str, asset_id: str):
        path, mime = invoke(lambda store: EditingService(store).audio_media(project_id, storyboard_id, asset_id))
        return FileResponse(path, media_type=mime, headers={'X-Content-Type-Options': 'nosniff'})

    @router.get(base + '/exports')
    def exports(project_id: str, storyboard_id: str):
        return invoke(lambda store: EditingService(store).exports(project_id, storyboard_id))

    @router.post(base + '/exports', status_code=201)
    def export(project_id: str, storyboard_id: str, request: ExportRequest):
        return invoke(lambda store: EditingService(store).create_export(project_id, storyboard_id, request))

    @router.post(base + '/exports/{export_id}/abandon')
    def abandon(project_id: str, storyboard_id: str, export_id: str):
        return invoke(lambda store: EditingService(store).abandon(project_id, storyboard_id, export_id))

    @router.post(base + '/exports/{export_id}/accept')
    def accept(project_id: str, storyboard_id: str, export_id: str, request: AcceptRequest):
        return invoke(lambda store: EditingService(store).accept(project_id, storyboard_id, export_id, request))

    @router.get(base + '/exports/{export_id}/media')
    def media(project_id: str, storyboard_id: str, export_id: str):
        path, mime = invoke(lambda store: EditingService(store).media(project_id, storyboard_id, export_id))
        return FileResponse(path, media_type=mime, headers={'X-Content-Type-Options': 'nosniff'})

    @router.get(base + '/exports/{export_id}/download')
    def download(project_id: str, storyboard_id: str, export_id: str):
        path, mime = invoke(lambda store: EditingService(store).media(project_id, storyboard_id, export_id))
        return FileResponse(path, media_type=mime, filename=f'framepilot-{export_id}.mp4',
                            headers={'X-Content-Type-Options': 'nosniff'})
