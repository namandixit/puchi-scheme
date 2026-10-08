@echo off
REM Definition of done for any puchi change: this script exits 0.
REM   1) amalgamate
REM   2) full suite under MSVC + Clang (all three numeric configs, execute)
REM   3) same suite again under Clang ASan+UBSan
REM Run from the repo root:  puchi\tools\build_puchi_tests.bat
REM Requires: cl and clang on PATH, Git Bash for amalgamate.sh,
REM           clang_rt.asan_dynamic-*.dll (under clang -print-resource-dir).
REM
REM Three numeric configs (each compiler / sanitizer pass):
REM   integer — PUCHI_INTEGER_ONLY          (C suite)
REM   default — fixnums + flonums           (C suite)
REM   tower   — PUCHI_ENABLE_NUMERICAL_TOWER (Scheme suites)
REM
REM Note: Chibi .sld/.scm libraries contain complex literals (+i, etc.), so
REM the Scheme harness requires the numerical tower. Slimmer configs use
REM C-side eval suites against the embedded init instead.
REM
REM CMD labels are unique only by the first 8 characters — keep them distinct.

setlocal EnableExtensions
set ROOT=%~dp0..\..
cd /d "%ROOT%"

set TEST=puchi\test
set OUT=%TEST%\build

if not exist "%OUT%" mkdir "%OUT%"

where cl >nul 2>&1
if errorlevel 1 (
  echo cl ^(MSVC^) not found on PATH
  exit /b 1
)
where clang >nul 2>&1
if errorlevel 1 (
  echo clang not found on PATH
  exit /b 1
)

echo === check generated FFI stubs in lib/ ===
set NEED_STUBS=
if not exist "lib\scheme\bytevector.c" set NEED_STUBS=1
if not exist "lib\chibi\io\io.c" set NEED_STUBS=1
if not exist "lib\chibi\filesystem.c" set NEED_STUBS=1
if not exist "lib\chibi\win32\process-win32.c" set NEED_STUBS=1
if defined NEED_STUBS (
  echo Missing generated lib/**/*.c stubs. Generate from *.stub with a built chibi:
  echo   bash puchi/tools/generate_harness_stubs.sh path\to\chibi-scheme.exe
  echo Or build Chibi normally ^(CMake/Make^) first so those files exist under lib/.
  exit /b 1
)

echo === amalgamating ===
"C:\Program Files\Git\bin\bash.exe" -lc "./puchi/tools/amalgamate.sh"
if %ERRORLEVEL% NEQ 0 exit /b 1

call :do_suite msvc
if %ERRORLEVEL% NEQ 0 exit /b 1
call :do_suite clang
if %ERRORLEVEL% NEQ 0 exit /b 1
call :do_suite asan
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === all three puchi configs passed ^(msvc + clang + clang ASan/UBSan^) ===
endlocal
exit /b 0

REM ---------------------------------------------------------------------------
:do_suite
set TAG=%~1
echo.
echo ========== [%TAG%] ==========

if /I "%TAG%"=="msvc" goto do_msvc
if /I "%TAG%"=="clang" goto do_clng
if /I "%TAG%"=="asan" goto do_asan
echo unknown compiler tag: %TAG%
exit /b 1

:do_msvc
REM No /I. — puchi.h must be a true single-header (tests use #include "../puchi.h").
set CF=/nologo /W4 /O2 /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE
set HF=/I%TEST%\harness-include

echo === [%TAG%][integer] C suite ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_integer_smoke.exe %TEST%\puchi_integer_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] C suite ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_slim_smoke.exe %TEST%\puchi_slim_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] smoke ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_smoke.exe %TEST%\puchi_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] two-host smoke ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_two_host_smoke.exe %TEST%\puchi_two_host_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_two_host_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] harness ===
cl %CF% %HF% /DPUCHI_ENABLE_NUMERICAL_TOWER /Fo%OUT%\%TAG%_harness_tower.obj /c %TEST%\puchi_harness.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% %HF% /DPUCHI_ENABLE_NUMERICAL_TOWER /Fo%OUT%\%TAG%_harness_clibs_tower.obj /c %TEST%\puchi_harness_clibs.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% /Fe:%OUT%\%TAG%_harness_tower.exe %OUT%\%TAG%_harness_tower.obj %OUT%\%TAG%_harness_clibs_tower.obj
if %ERRORLEVEL% NEQ 0 exit /b 1
goto do_scm

:do_clng
REM No -I. — puchi.h must be a true single-header (tests use #include "../puchi.h").
set CF=-O2 -D_CRT_SECURE_NO_WARNINGS -D_CRT_NONSTDC_NO_DEPRECATE -Weverything
set HF=-I%TEST%\harness-include
goto do_clb

:do_asan
REM Runtime net for GC / layout / UB bugs the optimized suite can miss.
REM ASan DLL lives under clang's resource dir on Windows; put it on PATH.
for /f "usebackq delims=" %%i in (`clang -print-resource-dir`) do set CLANG_RESOURCE=%%i
if not defined CLANG_RESOURCE (
  echo clang -print-resource-dir failed — required for ASan runtime
  exit /b 1
)
if not exist "%CLANG_RESOURCE%\lib\windows\clang_rt.asan_dynamic-x86_64.dll" (
  echo Missing ASan runtime: %CLANG_RESOURCE%\lib\windows\clang_rt.asan_dynamic-x86_64.dll
  exit /b 1
)
set "PATH=%CLANG_RESOURCE%\lib\windows;%PATH%"
REM ASan + UBSan; abort on first hit. Aligned bytecode + safe fixnum read
REM (features force / patch 005) keep these checks meaningful on x86.
set CF=-O1 -g -fno-omit-frame-pointer -fsanitize=address -fsanitize=undefined -fno-sanitize-recover=all -D_CRT_SECURE_NO_WARNINGS -D_CRT_NONSTDC_NO_DEPRECATE
set HF=-I%TEST%\harness-include
goto do_clb

:do_clb
echo === [%TAG%][integer] C suite ===
clang %CF% -o "%OUT%\%TAG%_integer_smoke.exe" %TEST%\puchi_integer_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] C suite ===
clang %CF% -o "%OUT%\%TAG%_slim_smoke.exe" %TEST%\puchi_slim_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] smoke ===
clang %CF% -o "%OUT%\%TAG%_smoke.exe" %TEST%\puchi_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] two-host smoke ===
clang %CF% -o "%OUT%\%TAG%_two_host_smoke.exe" %TEST%\puchi_two_host_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_two_host_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] harness ===
clang %CF% %HF% -DPUCHI_ENABLE_NUMERICAL_TOWER -c %TEST%\puchi_harness.c -o "%OUT%\%TAG%_harness_tower.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% %HF% -DPUCHI_ENABLE_NUMERICAL_TOWER -c %TEST%\puchi_harness_clibs.c -o "%OUT%\%TAG%_harness_clibs_tower.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% -o "%OUT%\%TAG%_harness_tower.exe" "%OUT%\%TAG%_harness_tower.o" "%OUT%\%TAG%_harness_clibs_tower.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
goto do_scm

:do_scm
echo === [%TAG%][tower] r7rs-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\r7rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] syntax-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\syntax-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] division-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\division-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] unicode-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib -xchibi tests\unicode-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%] all three configs passed ===
exit /b 0
