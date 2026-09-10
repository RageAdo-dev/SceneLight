#include <windows.h>
#include <wchar.h>

static int quote_arg(wchar_t *out, size_t capacity, const wchar_t *value) {
    size_t used = wcslen(out);
    if (used + wcslen(value) + 4 >= capacity) return 0;
    if (wcschr(value, L'"')) return 0;
    out[used++] = L'"';
    for (const wchar_t *p = value; *p; ++p) {
        if (used + 2 >= capacity) return 0;
        out[used++] = *p;
    }
    out[used++] = L'"';
    out[used] = 0;
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t module[MAX_PATH], root[MAX_PATH], config[MAX_PATH], runtime[32768];
    if (!GetModuleFileNameW(NULL, module, MAX_PATH)) return 2;
    wcscpy(root, module);
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 2;
    *slash = 0;
    if (swprintf(config, MAX_PATH, L"%ls\\game\\scenelight_runtime\\native-launcher.txt", root) < 0) return 2;

    HANDLE file = CreateFileW(config, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        MessageBoxW(NULL, L"SceneLight's launcher configuration is missing. Reinstall or remove SceneLight safely.", L"SceneLight", MB_ICONERROR);
        return 3;
    }
    char utf8[32768]; DWORD read = 0;
    if (!ReadFile(file, utf8, sizeof(utf8) - 1, &read, NULL)) { CloseHandle(file); return 3; }
    CloseHandle(file); utf8[read] = 0;
    while (read && (utf8[read - 1] == '\r' || utf8[read - 1] == '\n')) utf8[--read] = 0;
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8, -1, runtime, 32768)) return 3;
    if (GetFileAttributesW(runtime) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"SceneLight's compatibility runtime is unavailable. Reinstall SceneLight to repair it.", L"SceneLight", MB_ICONERROR);
        return 4;
    }

    wchar_t command[65536] = L"";
    if (!quote_arg(command, 65536, runtime)) return 5;
    wcscat(command, L" ");
    if (!quote_arg(command, 65536, root)) return 5;
    wcscat(command, L" run");
    if (command_line && *command_line) {
        size_t required = wcslen(command) + wcslen(command_line) + 2;
        if (required >= 65536) return 5;
        wcscat(command, L" ");
        wcscat(command, command_line);
    }

    wchar_t runtime_directory[32768];
    wcscpy(runtime_directory, runtime);
    wchar_t *runtime_slash = wcsrchr(runtime_directory, L'\\');
    if (!runtime_slash) return 4;
    *runtime_slash = 0;

    STARTUPINFOW startup = { sizeof(startup) };
    PROCESS_INFORMATION process = { 0 };
    if (!CreateProcessW(runtime, command, NULL, NULL, FALSE, 0, NULL, runtime_directory, &startup, &process)) {
        MessageBoxW(NULL, L"SceneLight could not start the game runtime.", L"SceneLight", MB_ICONERROR);
        return 6;
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    return (int)exit_code;
}
