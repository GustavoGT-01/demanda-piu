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


start "" http://127.0.0.1:8090
"%PY%" %PYARG% servidor.py
echo.
echo O servidor parou. Veja a mensagem acima.
pause
