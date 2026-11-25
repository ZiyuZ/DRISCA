#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <stdio.h>

static BOOL path_exists(const wchar_t *path) {
    DWORD attrs = GetFileAttributesW(path);
    return attrs != INVALID_FILE_ATTRIBUTES;
}

static void show_error(const wchar_t *message) {
    MessageBoxW(NULL, message, L"DRISCA 启动失败", MB_OK | MB_ICONERROR);
}

static DWORD run_process(
    wchar_t *cmd_line,
    const wchar_t *work_dir,
    DWORD creation_flags,
    BOOL *not_found
) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    *not_found = FALSE;

    if (!CreateProcessW(
            NULL,
            cmd_line,
            NULL,
            NULL,
            FALSE,
            creation_flags,
            NULL,
            work_dir,
            &si,
            &pi)) {
        DWORD err = GetLastError();
        if (err == ERROR_FILE_NOT_FOUND || err == ERROR_PATH_NOT_FOUND) {
            *not_found = TRUE;
        }
        return err ? err : 1;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD exit_code = 0;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return exit_code;
}

static BOOL build_path(wchar_t *out, size_t out_len, const wchar_t *root, const wchar_t *rel) {
    int n = _snwprintf_s(out, out_len, _TRUNCATE, L"%ls\\%ls", root, rel);
    return n > 0;
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)pCmdLine;
    (void)nCmdShow;

    wchar_t exe_path[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        show_error(L"无法获取 DRISCA.exe 所在路径。");
        return 1;
    }

    wchar_t *last_slash = wcsrchr(exe_path, L'\\');
    if (!last_slash) {
        show_error(L"无法解析 DRISCA 项目根目录。");
        return 1;
    }
    *last_slash = L'\0';
    const wchar_t *root = exe_path;

    wchar_t check_path[MAX_PATH];
    if (!build_path(check_path, MAX_PATH, root, L"pyproject.toml") || !path_exists(check_path)) {
        show_error(L"请将 DRISCA.exe 放在 DRISCA 项目根目录（与 pyproject.toml 同级）运行。");
        return 1;
    }

    BOOL not_found = FALSE;

    /* 1. 首次缺少 .venv 时自动执行 uv sync */
    build_path(check_path, MAX_PATH, root, L".venv\\Scripts\\python.exe");
    if (!path_exists(check_path)) {
        wchar_t cmd[] = L"uv sync";
        DWORD code = run_process(cmd, root, CREATE_NEW_CONSOLE, &not_found);
        if (not_found) {
            show_error(
                L"未找到 uv。\n\n"
                L"请先安装 uv（https://docs.astral.sh/uv/），安装完成后重新双击 DRISCA.exe。"
            );
            return 1;
        }
        if (code != 0) {
            wchar_t msg[512];
            _snwprintf_s(
                msg,
                512,
                _TRUNCATE,
                L"Python 依赖同步失败（uv sync 退出码 %lu）。\n\n"
                L"请在项目目录打开终端手动运行 uv sync 查看详细错误。",
                code
            );
            show_error(msg);
            return 1;
        }
    }

    /* 2. 首次缺少前端构建产物时自动安装并构建前端 */
    build_path(check_path, MAX_PATH, root, L"src\\drisca\\launcher\\static\\index.html");
    if (!path_exists(check_path)) {
        wchar_t nm_path[MAX_PATH];
        build_path(nm_path, MAX_PATH, root, L"frontend\\node_modules");
        if (!path_exists(nm_path)) {
            wchar_t install_cmd[] = L"bun install --cwd frontend --frozen-lockfile";
            DWORD code = run_process(install_cmd, root, CREATE_NEW_CONSOLE, &not_found);
            if (not_found) {
                show_error(
                    L"未找到 Bun。\n\n"
                    L"首次启动需要构建管理界面，请先安装 Bun（https://bun.sh/），安装完成后重新双击 DRISCA.exe。"
                );
                return 1;
            }
            if (code != 0) {
                wchar_t msg[512];
                _snwprintf_s(
                    msg,
                    512,
                    _TRUNCATE,
                    L"前端依赖安装失败（bun install 退出码 %lu）。\n\n"
                    L"请在项目目录打开终端手动运行：\nbun install --cwd frontend --frozen-lockfile",
                    code
                );
                show_error(msg);
                return 1;
            }
        }

        wchar_t build_cmd[] = L"bun run --cwd frontend build";
        DWORD code = run_process(build_cmd, root, CREATE_NEW_CONSOLE, &not_found);
        if (not_found) {
            show_error(
                L"未找到 Bun。\n\n"
                L"首次启动需要构建管理界面，请先安装 Bun（https://bun.sh/），安装完成后重新双击 DRISCA.exe。"
            );
            return 1;
        }
        if (code != 0) {
            wchar_t msg[512];
            _snwprintf_s(
                msg,
                512,
                _TRUNCATE,
                L"管理界面构建失败（bun run build 退出码 %lu）。\n\n"
                L"请在项目目录打开终端手动运行：\nbun run --cwd frontend build",
                code
            );
            show_error(msg);
            return 1;
        }
    }

    /* 3. 无黑框静默拉起 DRISCA 管理端 */
    wchar_t launch_cmd[] = L"uv run --no-sync -m drisca.launcher";
    DWORD code = run_process(launch_cmd, root, CREATE_NO_WINDOW, &not_found);
    if (not_found) {
        show_error(
            L"未找到 uv。\n\n"
            L"请先安装 uv（https://docs.astral.sh/uv/），安装完成后重新双击 DRISCA.exe。"
        );
        return 1;
    }
    if (code != 0) {
        wchar_t msg[512];
        _snwprintf_s(
            msg,
            512,
            _TRUNCATE,
            L"DRISCA 管理端异常退出（退出码 %lu）。\n\n"
            L"请在项目目录打开终端运行以下命令查看详细日志：\nuv run -m drisca.launcher",
            code
        );
        show_error(msg);
        return 1;
    }

    return 0;
}
