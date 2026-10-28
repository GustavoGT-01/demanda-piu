@echo off
rem Chamado pela tarefa agendada "Central de demandas" (criada pelo instalar-inicio.bat): liga a Central e a religa
rem em 5 s se ela parar. O que acontece fica em data\servidor.log. Nao abre navegador nem janela.
rem O 1o argumento, se houver, e o caminho do python.exe gravado pelo instalador.
cd /d "%~dp0"

set "PY=%~1"
set "PYARG="
if defined PY goto achou
where py >nul 2>nul && set "PY=py" && set "PYARG=-3"
if not defined PY if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY set "PY=python"
:achou

"%PY%" %PYARG% servidor.py --sempre
