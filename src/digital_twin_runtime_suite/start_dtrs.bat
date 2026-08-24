:: SPDX-FileCopyrightText: 2026 Maksim Pospelkov
:: SPDX-License-Identifier: MIT
@echo off
setlocal EnableExtensions

set "APP_DIR=%~dp0"
for %%I in ("%APP_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "APP_KIT=%APP_DIR%apps\digital_twin_runtime_suite.kit"
set "DTRS_PORTABLE_ROOT=%REPO_ROOT%\out\dtrs_kit_runtime"
set "DRIVE_ROOT=%~d0\"
set "CHECK_ONLY="
set "CONSOLE_MODE="

:parse_args
if "%~1"=="" goto :args_parsed
if /i "%~1"=="--check" set "CHECK_ONLY=1"
if /i "%~1"=="/check" set "CHECK_ONLY=1"
if /i "%~1"=="--console" set "CONSOLE_MODE=1"
if /i "%~1"=="/console" set "CONSOLE_MODE=1"
shift
goto :parse_args

:args_parsed

if not defined DTRS_KIT_RELEASE (
    if defined KIT_RELEASE set "DTRS_KIT_RELEASE=%KIT_RELEASE%"
)

if not defined DTRS_KIT_CAE_RELEASE (
    if defined KIT_CAE_RELEASE set "DTRS_KIT_CAE_RELEASE=%KIT_CAE_RELEASE%"
)

if not defined DTRS_KIT_RELEASE (
    for /f "delims=" %%K in ('dir /b /ad "%DRIVE_ROOT%*kit*app*" 2^>nul') do (
        if exist "%DRIVE_ROOT%%%K\_build\windows-x86_64\release\kit\kit.exe" (
            set "DTRS_KIT_RELEASE=%DRIVE_ROOT%%%K\_build\windows-x86_64\release"
            goto :found_release
        )
    )
)

:found_release
if not defined DTRS_KIT_RELEASE (
    echo Unable to find a built Omniverse Kit release.
    echo Set DTRS_KIT_RELEASE to the release directory, then run this file again.
    echo Example: set DTRS_KIT_RELEASE=path\to\kit-app-template\_build\windows-x86_64\release
    pause
    exit /b 1
)

if not defined DTRS_KIT_CAE_RELEASE (
    for /f "delims=" %%K in ('dir /b /ad "%DRIVE_ROOT%*kit*cae*" 2^>nul') do (
        if exist "%DRIVE_ROOT%%%K\_build\windows-x86_64\release\exts" (
            set "DTRS_KIT_CAE_RELEASE=%DRIVE_ROOT%%%K\_build\windows-x86_64\release"
            goto :found_kit_cae_release
        )
    )
)

:found_kit_cae_release
if not defined DTRS_KIT_CAE_RELEASE (
    echo Unable to find a built NVIDIA Kit-CAE release.
    echo Set DTRS_KIT_CAE_RELEASE to the release directory, then run this file again.
    exit /b 1
)

if not exist "%DTRS_KIT_CAE_RELEASE%\exts" (
    echo Kit-CAE extension folder was not found:
    echo %DTRS_KIT_CAE_RELEASE%\exts
    exit /b 1
)

if not exist "%DTRS_KIT_RELEASE%\kit\kit.exe" (
    echo Kit executable was not found:
    echo %DTRS_KIT_RELEASE%\kit\kit.exe
    pause
    exit /b 1
)

if not exist "%APP_KIT%" (
    echo Digital Twin Runtime Suite app config was not found:
    echo %APP_KIT%
    pause
    exit /b 1
)

if defined CHECK_ONLY (
    echo Digital Twin Runtime Suite launcher check
    echo Repo root: %REPO_ROOT%
    echo App kit:   %APP_KIT%
    echo Kit root:  %DTRS_KIT_RELEASE%
    echo Kit exe:   %DTRS_KIT_RELEASE%\kit\kit.exe
    echo Kit-CAE:    %DTRS_KIT_CAE_RELEASE%
    exit /b 0
)

pushd "%REPO_ROOT%" || exit /b 1
if defined CONSOLE_MODE (
    echo Starting Digital Twin Runtime Suite in console diagnostic mode.
    "%DTRS_KIT_RELEASE%\kit\kit.exe" "%APP_KIT%" --portable-root "%DTRS_PORTABLE_ROOT%" --ext-folder "%DTRS_KIT_RELEASE%\exts" --ext-folder "%DTRS_KIT_RELEASE%\extscache" --ext-folder "%DTRS_KIT_RELEASE%\apps" --ext-folder "%DTRS_KIT_CAE_RELEASE%\exts"
    set "KIT_EXIT_CODE=%ERRORLEVEL%"
    popd
    echo.
    echo Digital Twin Runtime Suite exited with code %KIT_EXIT_CODE%.
    pause
    exit /b %KIT_EXIT_CODE%
)
start "Digital Twin Runtime Suite" "%DTRS_KIT_RELEASE%\kit\kit.exe" "%APP_KIT%" --portable-root "%DTRS_PORTABLE_ROOT%" --ext-folder "%DTRS_KIT_RELEASE%\exts" --ext-folder "%DTRS_KIT_RELEASE%\extscache" --ext-folder "%DTRS_KIT_RELEASE%\apps" --ext-folder "%DTRS_KIT_CAE_RELEASE%\exts"
popd

exit /b 0
