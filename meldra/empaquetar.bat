@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Meldra - generador del paquete
echo   ------------------------------
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    for /f "delims=" %%B in ('dir /b /s "%ProgramFiles%\Blender Foundation\python.exe" 2^>nul') do set "PY=%%B"
)
if not defined PY (
    echo   ERROR: no encuentro ningun Python. Instala Python o Blender.
    goto :fin
)
echo   Python : !PY!

set "BL="
for /f "delims=" %%B in ('dir /b /s "%ProgramFiles%\Blender Foundation\blender.exe" 2^>nul') do set "BL=%%B"
if defined BL echo   Blender: !BL!
echo.

if defined BL (
    echo   [1/3] Pasando las pruebas...
    "!BL!" --background --factory-startup --python "pruebas\prueba.py" > "%TEMP%\meldra-pruebas.txt" 2>&1
    if errorlevel 1 (
        echo         FALLAN. Mira %TEMP%\meldra-pruebas.txt
        goto :fin
    )
    for /f "tokens=*" %%L in ('findstr /c:"comprobaciones pasan" "%TEMP%\meldra-pruebas.txt"') do echo         %%L
) else (
    echo   [1/3] Sin Blender: me salto las pruebas.
)

echo   [2/3] Empaquetando...
set "ZIP="
set "RESUMEN="
for /f "tokens=*" %%L in ('"!PY!" empaquetar.py') do (
    if defined ZIP set "RESUMEN=!ZIP!"
    set "ZIP=%%L"
)
if not defined ZIP (
    echo         ERROR al empaquetar.
    goto :fin
)
echo         !ZIP!
if defined RESUMEN echo         !RESUMEN!

echo   [3/3] Validando el manifiesto...
if defined BL (
    "!BL!" --command extension validate "!ZIP!" >nul 2>&1
    if errorlevel 1 (
        echo         EL MANIFIESTO NO VALIDA.
        goto :fin
    )
    echo         correcto
) else (
    echo         sin Blender, no se puede validar
)

echo.
echo   Listo para distribuir:
echo   !ZIP!
echo.
echo   Instalar en local : Edit ^> Preferences ^> Add-ons ^> Install from Disk
echo   Publicar gratis   : https://extensions.blender.org  (submit a new extension)
echo   Difundir           : blenderartists.org  /  blender-addons.org
echo.

:fin
echo.
pause
endlocal
