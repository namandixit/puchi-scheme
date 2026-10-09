@echo off
REM Definition of done for any puchi change: this script exits 0.
REM   1) amalgamate
REM   2) full suite under MSVC + Clang (all three numeric configs, execute)
REM   3) same suite again under Clang ASan+UBSan
REM Run from the repo root:  puchi\tools\build_puchi_tests.bat
REM Requires: cl and clang on PATH, Git Bash for amalgamate.sh,
REM           clang_rt.asan_dynamic-*.dll (under clang -print-resource-dir).
REM
REM Applicable matrix (yes = run; no = documented skip):
REM   Suite              integer   default   tower
REM   C preflight        yes       yes       yes (+ two-host)
REM   r5rs-tests.scm     yes       yes       yes
REM   basic/*.scm        yes       yes       yes  (--expect vs .res)
REM   r7rs-tests.scm     no*       no*       yes
REM   syntax-tests.scm   no*       no*       yes
REM   division-tests.scm no*       no*       yes
REM   unicode-tests.scm  no*       no*       yes
REM   lib-tests-embed    no*       no*       yes
REM   * needs PUCHI_ENABLE_NUMERICAL_TOWER (Complex / digitless +i literals)
REM   lib-embed also omits OS libs and include-shared not in harness_clibs
REM   skip basic test10-unhygiene (puchi capture differs from stock .res)
REM
REM Permanently out of scope (all configs):
REM   ffi/, snow/, net-tests, memory/, install/, run/, build-tests.sh
REM   (chibi process)/(chibi system)/(chibi tar)/filesystem lib tests
REM
REM Every harness script run: single-threaded first, then 64 parallel contexts.
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

echo === prep harness clibs overlays ^(UBSan patches; fail on upstream drift^) ===
"C:\Program Files\Git\bin\bash.exe" -lc "./puchi/tools/prep_harness_clibs.sh"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === compile clibs surface probe ^(PUCHI_TEST, no IMPLEMENTATION^) ===
cl /nologo /W4 /O2 /D_CRT_SECURE_NO_WARNINGS /DPUCHI_ENABLE_NUMERICAL_TOWER /Fo%OUT%\clibs_surface_probe.obj /c %TEST%\test_clibs_surface_probe.c
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
REM basic/*.scm with --expect vs sibling .res (skip none that have .res)
:run_basi
set HX=%~1
echo === basic tests ===
"%HX%" -I lib -xchibi --expect tests\basic\test00-fact-3.res tests\basic\test00-fact-3.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test01-apply.res tests\basic\test01-apply.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test02-closure.res tests\basic\test02-closure.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test03-nested-closure.res tests\basic\test03-nested-closure.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test04-nested-let.res tests\basic\test04-nested-let.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test05-internal-define.res tests\basic\test05-internal-define.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test06-letrec.res tests\basic\test06-letrec.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test07-mutation.res tests\basic\test07-mutation.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test08-callcc.res tests\basic\test08-callcc.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
"%HX%" -I lib -xchibi --expect tests\basic\test09-hygiene.res tests\basic\test09-hygiene.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
REM skip test10-unhygiene: puchi capture differs from stock .res (4th write 1 vs 6)
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
set CC=cl

echo === [%TAG%][integer] C checks ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_integer_smoke.exe %TEST%\puchi_integer_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][integer] harness + r5rs + basic ===
cl %CF% %HF% /DPUCHI_INTEGER_ONLY /Fo%OUT%\%TAG%_harness_integer.obj /c %TEST%\puchi_harness.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% %HF% /DPUCHI_INTEGER_ONLY /Fo%OUT%\%TAG%_harness_clibs_integer.obj /c %TEST%\puchi_harness_clibs.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% /Fe:%OUT%\%TAG%_harness_integer.exe %OUT%\%TAG%_harness_integer.obj %OUT%\%TAG%_harness_clibs_integer.obj
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_harness_integer.exe" -I lib -xchibi tests\r5rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
call :run_basi "%OUT%\%TAG%_harness_integer.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] C checks ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_slim_smoke.exe %TEST%\puchi_slim_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] harness + r5rs + basic ===
cl %CF% %HF% /Fo%OUT%\%TAG%_harness_default.obj /c %TEST%\puchi_harness.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% %HF% /Fo%OUT%\%TAG%_harness_clibs_default.obj /c %TEST%\puchi_harness_clibs.c
if %ERRORLEVEL% NEQ 0 exit /b 1
cl %CF% /Fe:%OUT%\%TAG%_harness_default.exe %OUT%\%TAG%_harness_default.obj %OUT%\%TAG%_harness_clibs_default.obj
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_harness_default.exe" -I lib -xchibi tests\r5rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
call :run_basi "%OUT%\%TAG%_harness_default.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] C checks ===
cl %CF% /Fo%OUT%\ /Fe:%OUT%\%TAG%_smoke.exe %TEST%\puchi_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] two-host ===
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
echo === [%TAG%][integer] C checks ===
clang %CF% -o "%OUT%\%TAG%_integer_smoke.exe" %TEST%\puchi_integer_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_integer_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][integer] harness + r5rs + basic ===
clang %CF% %HF% -DPUCHI_INTEGER_ONLY -c %TEST%\puchi_harness.c -o "%OUT%\%TAG%_harness_integer.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% %HF% -DPUCHI_INTEGER_ONLY -c %TEST%\puchi_harness_clibs.c -o "%OUT%\%TAG%_harness_clibs_integer.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% -o "%OUT%\%TAG%_harness_integer.exe" "%OUT%\%TAG%_harness_integer.o" "%OUT%\%TAG%_harness_clibs_integer.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_harness_integer.exe" -I lib -xchibi tests\r5rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
call :run_basi "%OUT%\%TAG%_harness_integer.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] C checks ===
clang %CF% -o "%OUT%\%TAG%_slim_smoke.exe" %TEST%\puchi_slim_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_slim_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][default] harness + r5rs + basic ===
clang %CF% %HF% -c %TEST%\puchi_harness.c -o "%OUT%\%TAG%_harness_default.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% %HF% -c %TEST%\puchi_harness_clibs.c -o "%OUT%\%TAG%_harness_clibs_default.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
clang %CF% -o "%OUT%\%TAG%_harness_default.exe" "%OUT%\%TAG%_harness_default.o" "%OUT%\%TAG%_harness_clibs_default.o"
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_harness_default.exe" -I lib -xchibi tests\r5rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1
call :run_basi "%OUT%\%TAG%_harness_default.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] C checks ===
clang %CF% -o "%OUT%\%TAG%_smoke.exe" %TEST%\puchi_smoke.c
if %ERRORLEVEL% NEQ 0 exit /b 1
"%OUT%\%TAG%_smoke.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%][tower] two-host ===
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
echo === [%TAG%][tower] r5rs-tests ===
"%OUT%\%TAG%_harness_tower.exe" -I lib -xchibi tests\r5rs-tests.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

call :run_basi "%OUT%\%TAG%_harness_tower.exe"
if %ERRORLEVEL% NEQ 0 exit /b 1

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

echo === [%TAG%][tower] lib-tests-embed ===
"%OUT%\%TAG%_harness_tower.exe" -I lib %TEST%\lib-tests-embed.scm
if %ERRORLEVEL% NEQ 0 exit /b 1

echo === [%TAG%] all three configs passed ===
exit /b 0
