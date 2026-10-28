# Chamado pelo instalar-inicio.bat (como administrador). Cria a tarefa "Central de demandas":
# ao iniciar o sistema, roda servidor-sempre.bat com a conta de quem usa o PC, sem limite de tempo e sem parar na bateria.
param([Parameter(Mandatory = $true)][string]$Python)
$ErrorActionPreference = 'Stop'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$nome = 'Central de demandas'

# a conta de quem está no PC (o administrador que autorizou pode ser outro)
$usuario = (Get-CimInstance Win32_ComputerSystem).UserName
if (-not $usuario) { $usuario = "$env:USERDOMAIN\$env:USERNAME" }
Write-Host "A Central vai rodar com a conta $usuario, mesmo antes de alguem entrar no Windows."
$cred = Get-Credential -UserName $usuario -Message "Senha da conta $usuario (fica guardada pelo Windows, nao pelo programa)"
if (-not $cred) { Write-Host 'Cancelado: nada foi criado.'; exit 1 }

$acao = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\cmd.exe" `
  -Argument "/c `"`"$pasta\servidor-sempre.bat`" `"$Python`"`"" -WorkingDirectory $pasta
$gatilho = New-ScheduledTaskTrigger -AtStartup
$ajustes = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $ajustes `
  -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
Write-Host "Pronto: tarefa '$nome' criada."

& $Python (Join-Path $pasta 'servidor.py') --ligado
if ($LASTEXITCODE -eq 0) {
  Write-Host 'A Central ja esta ligada (provavelmente pelo iniciar.bat). Feche a janela preta dela e reinicie o PC:'
  Write-Host 'dai em diante ela liga sozinha.'
} else {
  Start-ScheduledTask -TaskName $nome
  Write-Host 'A Central foi ligada agora pela tarefa. Abra http://127.0.0.1:8090 no navegador.'
}
