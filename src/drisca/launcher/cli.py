"""通过管理服务执行 Launcher 命令行操作。"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from drisca.core.config import RunSettings, load_machine_config


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description='DRISCA 管理端；操作命令连接已运行的管理服务')
    mode = root.add_mutually_exclusive_group()
    mode.add_argument('--web', action='store_true', help='仅启动 Web 管理服务')
    mode.add_argument('--dev', action='store_true', help='启动桌面与前端热更新')
    root.add_argument('--url', help='操作命令使用的管理服务地址，默认读取主机配置')
    commands = root.add_subparsers(dest='command')
    commands.add_parser('status', help='输出运行状态')
    commands.add_parser('logs', help='输出最近的运行日志')
    commands.add_parser('presets', help='列出实验预设')
    carla = commands.add_parser('carla', help='管理 CARLA Unreal').add_subparsers(
        dest='action', required=True
    )
    start = carla.add_parser('start', help='按主机配置启动 Unreal')
    start.add_argument('--kind', choices=('editor', 'packaged'), help='临时选择编辑器版或打包版')
    carla.add_parser('connect', help='连接配置中的 CARLA 服务')
    stop = carla.add_parser('stop', help='关闭 Launcher 启动的 Unreal，实验需已结束')
    experiment = commands.add_parser('experiment', help='管理单次实验').add_subparsers(
        dest='action', required=True
    )
    run = experiment.add_parser('start', help='开始实验')
    run.add_argument('--preset', required=True, help='预设名称，例如 basic')
    run.add_argument('--subject', default='', help='被试编号')
    run.add_argument('--save', action=argparse.BooleanOptionalAction, default=True, help='保存实验数据')
    run.add_argument('--record', action='store_true', help='启用 CARLA 录像')
    end = experiment.add_parser('stop', help='结束实验，保留 Unreal')
    for operation in (start, stop, run, end):
        operation.add_argument('--wait', action='store_true', help='等待操作完成并输出最终状态')
        operation.add_argument('--timeout', type=float, default=180, help='等待秒数，默认 180')
    request = commands.add_parser('request', help='直接调用管理 HTTP 接口')
    request.add_argument('method', choices=('GET', 'POST', 'PUT', 'DELETE'))
    request.add_argument('path', help='接口路径，例如 /api/world/map')
    body = request.add_mutually_exclusive_group()
    body.add_argument('--data', help='JSON 请求正文')
    body.add_argument('--data-file', type=Path, help='UTF-8 JSON 请求文件')
    return root


def request(base: str, path: str, method: str = 'GET', data=None):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = Request(base.rstrip('/') + path, body, {'Content-Type': 'application/json'}, method=method)
    try:
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode('utf-8')
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc


def wait_for_operation(base: str, args: argparse.Namespace):
    deadline = time.monotonic() + args.timeout
    while True:
        state = request(base, '/api/status')
        if args.command == 'carla':
            phase = state['unreal']['phase']
            done = phase == ('running' if args.action == 'start' else 'stopped')
            failed = phase == 'error'
        else:
            phase = state['phase']
            done = phase == ('running' if args.action == 'start' else 'idle')
            failed = phase == 'idle' and (args.action == 'start' or state['worker_state'] == 'error')
        if failed:
            raise RuntimeError(state['error'] or '操作失败，请查看管理端日志')
        if done:
            return state
        if time.monotonic() >= deadline:
            raise TimeoutError('等待操作超时，可用 status 和 logs 查看进展')
        time.sleep(0.25)


def execute(args: argparse.Namespace) -> int:
    try:
        if args.web or args.dev:
            raise ValueError('--web 和 --dev 用于启动管理端，请与操作命令分开执行')
        if args.url:
            base = args.url
        else:
            service = load_machine_config().service
            host = '127.0.0.1' if service.launcher_host in ('0.0.0.0', '::') else service.launcher_host
            base = f'http://{host}:{service.launcher_port}'
        if args.command in ('status', 'logs'):
            result = request(base, '/api/' + args.command)
        elif args.command == 'presets':
            result = request(base, '/api/bootstrap')['presets']
        elif args.command == 'carla':
            path = '/api/connect' if args.action == 'connect' else '/api/carla/' + args.action
            data = {'kind': args.kind} if args.action == 'start' else None
            result = request(base, path, 'POST', data)
        elif args.command == 'experiment':
            data = None
            if args.action == 'start':
                run = RunSettings(
                    subject_id=args.subject, save_data=args.save, enable_carla_recorder=args.record
                )
                data = {'preset_name': args.preset, 'run': run.model_dump(mode='json')}
            result = request(base, '/api/experiment/' + args.action, 'POST', data)
        else:
            data = args.data_file.read_text(encoding='utf-8-sig') if args.data_file else args.data
            if not args.path.startswith('/api/'):
                raise ValueError('接口路径应以 /api/ 开头')
            result = request(base, args.path, args.method, json.loads(data) if data else None)
        if getattr(args, 'wait', False):
            result = wait_for_operation(base, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
