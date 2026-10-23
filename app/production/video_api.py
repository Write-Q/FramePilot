"""Video job routes; concrete adapters must be registered explicitly by the host."""
from app.production.video_runtime import VideoRequest, VideoRuntime
from app.production.media_contracts import SelectMedia
from fastapi.responses import FileResponse
from app.production.video_files import VideoFiles


def install_video_routes(router, invoke, app):
    base = '/projects/{project_id}/storyboards/{storyboard_id}/video-runs'

    def runtime(store):
        return VideoRuntime(store, adapters=getattr(app.state, 'video_adapters', {}),
                            files=getattr(app.state, 'video_files', None))

    @router.get('/video-adapters')
    def adapters():
        return {'registered': sorted(getattr(app.state, 'video_adapters', {})),
                'media_validator_configured': bool(getattr(getattr(app.state, 'video_files', None) or VideoFiles(), 'validated_video', False)),
                'capabilities_verified': False}

    @router.post(base, status_code=201)
    def create(project_id: str, storyboard_id: str, request: VideoRequest):
        return invoke(lambda store: runtime(store).create(project_id, storyboard_id, request))

    @router.get(base)
    def runs(project_id: str, storyboard_id: str, version: int | None = None):
        return invoke(lambda store: runtime(store).list(project_id, storyboard_id, version))

    @router.get(base + '/{run_id}/media')
    def media(project_id: str, storyboard_id: str, run_id: str):
        path, mime = invoke(lambda store: runtime(store).media(project_id, storyboard_id, run_id))
        return FileResponse(path, media_type=mime, headers={'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'private, max-age=3600'})

    @router.post(base + '/{run_id}/cancel')
    def cancel(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: runtime(store).cancel(project_id, storyboard_id, run_id))

    @router.post(base + '/{run_id}/abandon')
    def abandon(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: runtime(store).abandon(project_id, storyboard_id, run_id))

    @router.post(base + '/{run_id}/recover-poll')
    def recover(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: runtime(store).recover_poll(project_id, storyboard_id, run_id))

    @router.post(base + '/{run_id}/select')
    def select(project_id: str, storyboard_id: str, run_id: str, request: SelectMedia):
        return invoke(lambda store: runtime(store).select(project_id, storyboard_id, run_id, request.expected_version))
