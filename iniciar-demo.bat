@echo off
rem Liga a Central de demandas em MODO DEMONSTRACAO: dados ficticios, base propria (data-demo) e porta
rem 8091. A Central de verdade (iniciar.bat, porta 8090, pasta data) nao e tocada e pode rodar ao mesmo tempo.
cd /d "%~dp0"
title Central de demandas - DEMONSTRACAO (nao feche)

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

rem Base e porta separadas das de verdade. O MODO faz a tela mostrar o selo de demonstracao.
set "DEMANDAS_DATA=%~dp0data-demo"
set "DEMANDAS_PORT=8091"
set "DEMANDAS_MODO=demo"

rem Ja ligada (outra janela): so abre o navegador.
"%PY%" %PYARG% servidor.py --ligado
if not errorlevel 1 (
  echo A demonstracao ja esta ligada. Abrindo no navegador...
  start "" http://127.0.0.1:%DEMANDAS_PORT%
  timeout /t 3 >nul
  exit /b 0
)

rem Gera os dados ficticios na primeira vez (nas seguintes so avisa que ja existem).
echo Preparando os dados ficticios da demonstracao...
"%PY%" %PYARG% demo.py seed
if errorlevel 1 (
  echo.
  echo ERRO: nao foi possivel preparar os dados da demonstracao. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
echo Para gerar os dados de novo antes de apresentar: %PY% %PYARG% demo.py seed --refazer
echo.
start "" http://127.0.0.1:%DEMANDAS_PORT%
"%PY%" %PYARG% servidor.py
echo.
echo O servidor da demonstracao parou. Veja a mensagem acima.
pause
