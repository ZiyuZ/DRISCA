"""开发时启动 Vite，并随桌面窗口回收前端进程。"""

import os
import shutil
import socket
import subprocess
import threading
from contextlib import contextmanager

import win32api  # ty: ignore[import-not-found]
import win32con
import win32job  # ty: ignore[import-not-found]

from drisca.core.paths import PROJECT_ROOT


@contextmanager
def frontend_dev_server(backend_port: int):
    bun = shutil.which('bun')
    if bun is None:
        raise FileNotFoundError('请先安装 Bun，并将其加入 PATH。')
    job = win32job.CreateJobObject(None, '')
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    process = None
    assigned = False
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        process = subprocess.Popen(
            [
                bun,
                str(PROJECT_ROOT / 'frontend/node_modules/vite/bin/vite.js'),
                '--host',
                '127.0.0.1',
                '--port',
                str(port),
                '--strictPort',
            ],
            cwd=PROJECT_ROOT / 'frontend',
            env={**os.environ, 'DRISCA_BACKEND_PORT': str(backend_port), 'NO_COLOR': '1'},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
        )
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, process.pid)
        try:
            win32job.AssignProcessToJobObject(job, handle)
            assigned = True
        finally:
            handle.Close()
        ready = threading.Event()
        started = False

        def output() -> None:
            nonlocal started
            assert process is not None and process.stdout is not None
            for line in process.stdout:
                print(line, end='', flush=True)
                if url in line:
                    started = True
                    ready.set()
            ready.set()

        reader = threading.Thread(target=output, daemon=True)
        reader.start()
        if not ready.wait(20):
            raise TimeoutError('Vite 启动超时，请查看终端输出。')
        if not started or process.poll() is not None:
            raise RuntimeError('Vite 启动失败，请查看终端输出。')
        yield url
    finally:
        job.Close()
        if process is not None:
            if not assigned and process.poll() is None:
                process.terminate()
            process.wait()
