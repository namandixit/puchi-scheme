@echo off
REM Build and run core-language tests for the puchi amalgamation.
REM Always runs under both MSVC (cl) and Clang.
REM Run from the repo root:  puchi\tools\build_puchi_tests.bat
REM Requires: cl and clang on PATH, Git Bash for amalgamate.sh.
REM
REM Three numeric configs (each compiler):
REM   integer — PUCHI_INTEGER_ONLY          (C suite)
REM   default — fixnums + flonums           (C suite)
REM   tower   — PUCHI_ENABLE_NUMERICAL_TOWER (Scheme suites)
REM
REM Note: Chibi .sld/.scm libraries contain complex literals (+i, etc.), so
REM the Scheme harness requires the numerical tower. Slimmer configs use
REM C-side eval suites against the embedded init instead.

setlocal
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
if errorlevel 1 exit /b 1

call :run_suite msvc
if errorlevel 1 exit /b 1
call :run_suite clang
if errorlevel 1 exit /b 1

echo === all three puchi configs passed ^(msvc + clang^) ===
endlocal
exit /b 0

REM ---------------------------------------------------------------------------
:run_suite
set TAG=%~1
echo.
echo ========== [%TAG%] ==========

if /I "%TAG%"=="msvc" goto :run_msvc
if /I "%TAG%"=="clang" goto :run_clang
echo unknown compiler tag: %TAG%
exit /b 1

:run_msvc
REM No /I. — puchi.h must be a true single-header (tests use #include "../puchi.h").
set CF=/nologo /W1 /O2 /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE
set HF=/I%TEST%\harness-include

echo === [%TAG%][integer] C suite ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_integer_smoke.exe %TEST%\puchi_integer_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][default] C suite ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_slim_smoke.exe %TEST%\puchi_slim_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] smoke ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_smoke.exe %TEST%\puchi_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] harness ===
cl %CF% %HF% /DPUCHI_ENABLE_NUMERICAL_TOWER /Fo%OUT%\%TAG%_harness_tower.obj /c %TEST%\puchi_harness.c
if errorlevel 1 exit /b 1
cl %CF% %HF% /DPUCHI_ENABLE_NUMERICAL_TOWER /Fo%OUT%\%TAG%_harness_clibs_tower.obj /c %TEST%\puchi_harness_clibs.c
if errorlevel 1 exit /b 1
cl %CF% /Fe:%OUT%\%TAG%_harness_tower.exe %OUT%\%TAG%_harness_tower.obj %OUT%\%TAG%_harness_clibs_tower.obj
if errorlevel 1 exit /b 1
goto :run_scheme

:run_clang
REM No -I. — puchi.h must be a true single-header (tests use #include "../puchi.h").
set CF=-O2 -D_CRT_SECURE_NO_WARNINGS -D_CRT_NONSTDC_NO_DEPRECATE -Wno-everything
set HF=-I%TEST%\harness-include

echo === [%TAG%][integer] C suite ===
clang %CF% -o "%OUT%\%TAG%_integer_smoke.exe" %TEST%\puchi_integer_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][default] C suite ===
clang %CF% -o "%OUT%\%TAG%_slim_smoke.exe" %TEST%\puchi_slim_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] smoke ===
clang %CF% -o "%OUT%\%TAG%_smoke.exe" %TEST%\puchi_smoke.c
if errorlevel 1 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] harness ===
clang %CF% %HF% -DPUCHI_ENABLE_NUMERICAL_TOWER -c %TEST%\puchi_harness.c -o "%OUT%\%TAG%_harness_tower.o"
if errorlevel 1 exit /b 1
clang %CF% %HF% -DPUCHI_ENABLE_NUMERICAL_TOWER -c %TEST%\puchi_harness_clibs.c -o "%OUT%\%TAG%_harness_clibs_tower.o"
if errorlevel 1 exit /b 1
clang -o "%OUT%\%TAG%_harness_tower.exe" "%OUT%\%TAG%_harness_tower.o" "%OUT%\%TAG%_harness_clibs_tower.o"
if errorlevel 1 exit /b 1
goto :run_scheme

:run_scheme
echo === [%TAG%][tower] r7rs-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\r7rs-tests.scm
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] syntax-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\syntax-tests.scm
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] division-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib tests\division-tests.scm
if errorlevel 1 exit /b 1

echo === [%TAG%][tower] unicode-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib -xchibi tests\unicode-tests.scm
if errorlevel 1 exit /b 1

echo === [%TAG%] all three configs passed ===
exit /b 0
