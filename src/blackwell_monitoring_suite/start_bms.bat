@echo off
setlocal EnableExtensions

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "APP_KIT=%APP_DIR%apps\blackwell_monitoring_suite.kit"
set "DRIVE_ROOT=%~d0\"
set "CHECK_ONLY="

if /i "%~1"=="--check" set "CHECK_ONLY=1"
if /i "%~1"=="/check" set "CHECK_ONLY=1"

if not defined BMS_KIT_RELEASE (
    if defined KIT_RELEASE set "BMS_KIT_RELEASE=%KIT_RELEASE%"
)

if not defined BMS_KIT_CAE_RELEASE (
    if defined KIT_CAE_RELEASE set "BMS_KIT_CAE_RELEASE=%KIT_CAE_RELEASE%"
)

if not defined BMS_KIT_RELEASE (
    for /f "delims=" %%K in ('dir /b /ad "%DRIVE_ROOT%*kit*app*" 2^>nul') do (
        if exist "%DRIVE_ROOT%%%K\_build\windows-x86_64\release\kit\kit.exe" (
            set "BMS_KIT_RELEASE=%DRIVE_ROOT%%%K\_build\windows-x86_64\release"
            goto :found_release
        )
    )
)

:found_release
if not defined BMS_KIT_RELEASE (
    echo Unable to find a built Omniverse Kit release.
    echo Set BMS_KIT_RELEASE to the release directory, then run this file again.
    echo Example: set BMS_KIT_RELEASE=path\to\kit-app-template\_build\windows-x86_64\release
    pause
    exit /b 1
)

if not defined BMS_KIT_CAE_RELEASE (
    for /f "delims=" %%K in ('dir /b /ad "%DRIVE_ROOT%*kit*cae*" 2^>nul') do (
        if exist "%DRIVE_ROOT%%%K\_build\windows-x86_64\release\exts" (
            set "BMS_KIT_CAE_RELEASE=%DRIVE_ROOT%%%K\_build\windows-x86_64\release"
            goto :found_kit_cae_release
        )
    )
)

:found_kit_cae_release
if not defined BMS_KIT_CAE_RELEASE (
    echo Unable to find a built NVIDIA Kit-CAE release.
    echo Set BMS_KIT_CAE_RELEASE to the release directory, then run this file again.
    exit /b 1
)

if not exist "%BMS_KIT_CAE_RELEASE%\exts" (
    echo Kit-CAE extension folder was not found:
    echo %BMS_KIT_CAE_RELEASE%\exts
    exit /b 1
)

if not exist "%BMS_KIT_RELEASE%\kit\kit.exe" (
    echo Kit executable was not found:
    echo %BMS_KIT_RELEASE%\kit\kit.exe
    pause
    exit /b 1
)

if not exist "%APP_KIT%" (
    echo Blackwell Monitoring Suite app config was not found:
    echo %APP_KIT%
    pause
    exit /b 1
)

if defined CHECK_ONLY (
    echo Blackwell Monitoring Suite launcher check
    echo Repo root: %REPO_ROOT%
    echo App kit:   %APP_KIT%
    echo Kit root:  %BMS_KIT_RELEASE%
    echo Kit exe:   %BMS_KIT_RELEASE%\kit\kit.exe
    echo Kit-CAE:    %BMS_KIT_CAE_RELEASE%
    exit /b 0
)

pushd "%REPO_ROOT%" || exit /b 1
start "Blackwell Monitoring Suite" "%BMS_KIT_RELEASE%\kit\kit.exe" "%APP_KIT%" --ext-folder "%BMS_KIT_RELEASE%\exts" --ext-folder "%BMS_KIT_RELEASE%\extscache" --ext-folder "%BMS_KIT_RELEASE%\apps" --ext-folder "%BMS_KIT_CAE_RELEASE%\exts"
popd

exit /b 0
