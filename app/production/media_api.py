"""Shot media HTTP endpoints; no model calls in web requests."""
from fastapi.responses import FileResponse
from app.production.media_contracts import CreateMediaRun, SelectMedia
from app.production.media_service import MediaService


def install_media_routes(router, invoke):
    base = '/projects/{project_id}/storyboards/{storyboard_id}'

    @router.get(base + '/frame-prompt')
    def frame_prompt(project_id: str, storyboard_id: str, version: int, shot_key: str, frame_role: str = 'first'):
        return invoke(lambda store: MediaService(store).prompt(project_id, storyboard_id, version, shot_key, frame_role))

    @router.get(base + '/video-input', summary='预览单镜视频输入，不提交外部生成')
    def video_input(project_id: str, storyboard_id: str, version: int, shot_key: str):
        return invoke(lambda store: MediaService(store).video_input(project_id, storyboard_id, version, shot_key))

    @router.post(base + '/media-runs', status_code=201)
    def create_media(project_id: str, storyboard_id: str, request: CreateMediaRun):
        return invoke(lambda store: MediaService(store).create(project_id, storyboard_id, request))

    @router.get(base + '/media-runs')
    def media_runs(project_id: str, storyboard_id: str, version: int | None = None):
        return invoke(lambda store: MediaService(store).list(project_id, storyboard_id, version))

    @router.post(base + '/media-runs/{run_id}/select')
    def select_media(project_id: str, storyboard_id: str, run_id: str, request: SelectMedia):
        return invoke(lambda store: MediaService(store).select(project_id, storyboard_id, run_id, request.expected_version))

    @router.post(base + '/media-runs/{run_id}/cancel')
    def cancel_media(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: MediaService(store).cancel(project_id, storyboard_id, run_id))

    @router.post(base + '/media-runs/{run_id}/abandon')
    def abandon_media(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda store: MediaService(store).abandon(project_id, storyboard_id, run_id))

    @router.get('/projects/{project_id}/media/{media_id}')
    def media_file(project_id: str, media_id: str):
        path, mime = invoke(lambda store: MediaService(store).media(project_id, media_id))
        return FileResponse(path, media_type=mime, headers={'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'private, max-age=3600'})
