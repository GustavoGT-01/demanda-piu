@echo off
rem Liga a Central de demandas e abre no navegador. Feche esta janela para desligar.
cd /d "%~dp0"
title Central de demandas - servidor (nao feche)

rem Python: prefere o lancador "py -3"; depois o Python da pasta do usuario; por ultimo "python" do PATH.
set "PY="
set "PYARG="
where py >nul 2>nul && set "PY=py" && set "PYARG=-3"
if not defined PY if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY set "PY=python"
"%PY%" %PYARG% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
  echo ERRO: e preciso o Python 3.10 ou mais novo, e ele nao foi encontrado.
  echo Instale o Python em https://www.python.org/downloads/ e abra este arquivo de novo.
  pause
  exit /b 1
)

set "PORTA=%DEMANDAS_PORT%"
if not defined PORTA set "PORTA=8090"

rem Ja ligada (pela tarefa "iniciar com o Windows" ou outra janela): so abre o navegador.
"%PY%" %PYARG% servidor.py --ligado
if not errorlevel 1 (
  echo A Central ja esta ligada. Abrindo no navegador...
  start "" http://127.0.0.1:%PORTA%
  timeout /t 3 >nul
  exit /b 0
)

start "" http://127.0.0.1:%PORTA%
"%PY%" %PYARG% servidor.py
echo.
echo O servidor parou. Veja a mensagem acima.
pause
