@echo off
rem Desliga a Central de demandas. Serve principalmente quando ela subiu pela tarefa agendada "Central de demandas":
rem nesse caso nao existe janela preta para fechar, e um servidor morto volta sozinho em 5 s (servidor.py --sempre).
cd /d "%~dp0"
title Central de demandas - desligar

rem Python: prefere o lancador "py -3"; depois o Python da pasta do usuario; por ultimo "python" do PATH.
set "PY="
set "PYARG="
where py >nul 2>nul && set "PY=py" && set "PYARG=-3"
if not defined PY if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY set "PY=python"

rem A tarefa agendada liga a Central da porta padrao. Com DEMANDAS_PORT na mao o alvo e outra instancia (a
rem demonstracao, por exemplo): ai nao se mexe na tarefa nem no laco dela, so no servidor daquela porta.
set "DONO=1"
set "PORTA=%DEMANDAS_PORT%"
if defined PORTA (set "DONO=0") else (set "PORTA=8090")

"%PY%" %PYARG% servidor.py --ligado
if errorlevel 1 (
  echo A Central ja esta desligada.
  timeout /t 3 >nul
  exit /b 0
)

echo Desligando a Central da porta %PORTA%...

set "TAREFA=0"
if "%DONO%"=="1" (
  rem 1) O laco que religa, antes do servidor: derrubar o servidor sozinho so faria o laco subir outro em 5 s.
  powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*servidor.py*--sempre*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul

  rem 2) A tarefa agendada em si, para o Windows nao a marcar como rodando. Sem administrador isso falha, e nao faz
  rem    falta: o laco dela ja morreu no passo 1 e ela so dispara de novo quando o Windows reiniciar.
  schtasks /query /tn "Central de demandas" >nul 2>nul
  if not errorlevel 1 (
    set "TAREFA=1"
    schtasks /end /tn "Central de demandas" >nul 2>nul
  )
)

rem 3) Quem ainda escuta na porta, com os filhos. O --ligado acima ja provou que e a Central, e nao outro programa.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORTA% .*LISTENING"') do taskkill /f /t /pid %%p >nul 2>nul

rem 4) Confere depois dos 5 s que o laco esperaria, para nao anunciar desligado cedo demais.
timeout /t 8 >nul
"%PY%" %PYARG% servidor.py --ligado
if errorlevel 1 (
  echo.
  echo Pronto: a Central esta desligada.
  if "%TAREFA%"=="1" echo Ela liga sozinha outra vez quando o Windows reiniciar. Para desfazer isso: remover-inicio.bat, como administrador.
  echo Para ligar de novo agora: iniciar.bat
  timeout /t 6 >nul
  exit /b 0
)

echo.
echo A Central continua ligada na porta %PORTA%.
if "%TAREFA%"=="1" (
  echo Alguma coisa religou o servidor. Rode este arquivo com o botao direito ^> "Executar como administrador",
  echo ou rode remover-inicio.bat como administrador para a tarefa agendada parar de religar.
) else (
  echo Veja quem ocupa a porta:  netstat -ano ^| findstr :%PORTA%
)
pause
exit /b 1
