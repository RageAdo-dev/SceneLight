#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t root[32768], python[32768], command[32768], manifest[32768];
    DWORD length = GetModuleFileNameW(NULL, root, 32768);
    if (!length || length >= 32768) return 2;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 2;
    *slash = 0;
    if (wcslen(root) + 64 >= 32768) return 2;
    swprintf(python, 32768, L"%ls\\_scenelight\\python\\pythonw.exe", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        swprintf(manifest, 32768, L"%ls\\online-release.json", root);
        if (GetFileAttributesW(manifest) == INVALID_FILE_ATTRIBUTES) {
            MessageBoxW(NULL,
                L"Extract all files from the SceneLight Windows download before opening SceneLight.",
                L"SceneLight", MB_ICONINFORMATION);
            return 3;
        }
        DWORD system_length = GetSystemDirectoryW(python, 32768);
        if (!system_length || system_length + 64 >= 32768) return 2;
        wcscat(python, L"\\WindowsPowerShell\\v1.0\\powershell.exe");
        // Forward the original Windows argument string as data, never PowerShell code.
        if (!SetEnvironmentVariableW(L"SCENELIGHT_LAUNCH_ARGUMENTS", arguments)) return 2;
        if (wcslen(python) + wcslen(root) + 160 >= 32768) return 2;
        swprintf(command, 32768,
            L"\"%ls\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"%ls\\tools\\bootstrap_release.ps1\"",
            python, root);
    } else {
        if (wcslen(python) + wcslen(arguments) + 64 >= 32768) return 2;
        swprintf(command, 32768, L"\"%ls\" -m scenelight.desktop %ls", python, arguments);
    }
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION child = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, root, &startup, &child)) {
        MessageBoxW(NULL, L"SceneLight could not start. Extract a fresh copy of the Windows download.",
                    L"SceneLight", MB_ICONERROR);
        return 4;
    }
    WaitForSingleObject(child.hProcess, INFINITE);
    DWORD result = 1;
    GetExitCodeProcess(child.hProcess, &result);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return (int)result;
}
