"""数据管理与录像回放路由模块。"""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from drisca.core.paths import PROJECT_ROOT
from drisca.core.tools import query_recorder_info, replay_recorder
from drisca.launcher.runtime import Runtime
from drisca.launcher.schemas import NoteRequest, RecorderInfoRequest, ReplayRequest, SessionSelectionRequest


def build_data_router(
    get_runtime: Callable[[], Runtime],
    ensure_idle: Callable[[], None],
    safe_name: Callable[[str], str],
) -> APIRouter:
    """构建会话查询、删除、导出与录像回放路由。"""
    router = APIRouter()

    def recorder_path(name: str) -> Path:
        root = (PROJECT_ROOT / get_runtime().machine.recorder_dir).resolve()
        path = (root / name).resolve()
        if path.parent != root or path.suffix != '.rec' or not path.is_file():
            raise HTTPException(404, '录像不存在')
        return path

    @router.put('/api/sessions/{session_id}/note')
    def session_note(session_id: str, request: NoteRequest):
        with get_runtime().db_session() as db:
            if db.get_session(session_id) is None:
                raise HTTPException(404, '会话不存在')
            db.update_session_note(session_id, request.note)
        return {'ok': True}

    @router.get('/api/sessions')
    def sessions(start_date: str = '', end_date: str = '', status: str = '', search: str = ''):
        with get_runtime().db_session() as db:
            rows = db.list_sessions()
            frame_counts = db.count_all_session_frames()
            items = []
            for row in rows:
                date = datetime.fromtimestamp(row.started_at).strftime('%Y-%m-%d')
                if (start_date and date < start_date) or (end_date and date > end_date):
                    continue
                if status and status != row.status:
                    continue
                if search.lower() not in (row.session_id + row.subject_id).lower():
                    continue
                items.append({**asdict(row), 'frame_count': frame_counts.get(row.session_id, 0)})
            return {'total': len(rows), 'items': items}

    @router.get('/api/sessions/{session_id}')
    def session(session_id: str):
        with get_runtime().db_session() as db:
            row = db.get_session(session_id)
            if row is None:
                raise HTTPException(404, '会话不存在')
            return {
                'session': asdict(row),
                'events': [asdict(e) for e in db.list_session_events(session_id)],
                'frame_count': db.count_session_frames(session_id),
                'run_config': json.loads(row.run_config_json),
            }

    @router.post('/api/sessions/delete')
    def delete_sessions(request: SessionSelectionRequest):
        rt = get_runtime()
        if not request.session_ids:
            raise HTTPException(422, '请选择会话')
        if rt.state['session_id'] in request.session_ids:
            raise HTTPException(409, '请先结束选中的实验')
        if rt.state['export']['running']:
            raise HTTPException(409, '请等待当前导出完成')
        with rt.db_session() as db:
            db.delete_sessions(request.session_ids)
        return {'ok': True}

    @router.post('/api/export')
    def export(request: SessionSelectionRequest):
        rt = get_runtime()
        if not request.session_ids:
            raise HTTPException(422, '请选择会话')
        if rt.state['export']['running']:
            raise HTTPException(409, '正在导出')
        rt.update(export={'running': True, 'progress': 0, 'path': None, 'error': None})

        def work():
            path = (
                PROJECT_ROOT / rt.machine.export_dir / f'{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}'
            ).resolve()
            try:
                with rt.db_session() as db:
                    existing = {row.session_id for row in db.list_sessions()}
                    if not set(request.session_ids) <= existing:
                        raise ValueError('选中的会话不存在')
                    db.export_sessions(
                        path,
                        request.session_ids,
                        lambda progress: rt.update(
                            export={
                                'running': True,
                                'progress': progress,
                                'path': str(path),
                                'error': None,
                            }
                        ),
                    )
                rt.update(export={'running': False, 'progress': 100, 'path': str(path), 'error': None})
            except Exception as exc:
                rt.update(export={'running': False, 'progress': 0, 'path': None, 'error': str(exc)})
                raise

        rt.background(work)
        return {'ok': True}

    @router.get('/api/recordings')
    def recordings(search: str = '', page: int = 1, page_size: int = 20):
        if page < 1 or page_size < 1:
            raise HTTPException(422, '分页参数无效')
        directory = PROJECT_ROOT / get_runtime().machine.recorder_dir
        if not directory.is_dir():
            return {'total': 0, 'items': []}
        paths = sorted(
            (p for p in directory.glob('*.rec') if search.lower() in p.name.lower()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return {
            'total': len(paths),
            'items': [
                {'name': p.name, 'size_bytes': p.stat().st_size, 'modified_at': p.stat().st_mtime}
                for p in paths[(page - 1) * page_size : page * page_size]
            ],
        }

    @router.post('/api/recordings/info')
    def recorder_info(request: RecorderInfoRequest):
        api = get_runtime().api
        if api is None:
            raise HTTPException(409, 'CARLA 尚未连接')
        return {'text': query_recorder_info(api, recorder_path(request.name))}

    @router.post('/api/recordings/replay')
    def replay(request: ReplayRequest):
        ensure_idle()
        api = get_runtime().api
        if api is None:
            raise HTTPException(409, 'CARLA 尚未连接')
        replay_recorder(
            api,
            recorder_path(request.name),
            request.start_time,
            request.duration,
            request.time_factor,
            request.follow_actor_id,
            ignore_hero=False,
        )
        return {'ok': True}

    return router
