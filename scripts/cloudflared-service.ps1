# cloudflared-service.ps1
# Запускает cloudflared quick tunnel, обновляет .env, перезапускает app-контейнер.
# Регистрируется как Task Scheduler задача (аналог systemd на Windows).

param(
    [string]$EnvFile = "C:\Users\User\Downloads\fashion-bot\.env",
    [string]$LocalUrl = "http://localhost:8000",
    [string]$LogFile = "C:\Users\User\Downloads\fashion-bot\scripts\cloudflared.log",
    [string]$CloudflaredBin = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
)

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $Msg" | Tee-Object -FilePath $LogFile -Append
}

Write-Log "=== cloudflared-service start ==="

# Убить предыдущий экземпляр если есть
Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# Временный лог tunnel
$tunnelLog = "$env:TEMP\cf_tunnel_$((Get-Date).Ticks).log"

# Запустить tunnel
$proc = Start-Process `
    -FilePath $CloudflaredBin `
    -ArgumentList "tunnel","--url",$LocalUrl,"--logfile",$tunnelLog `
    -PassThru -WindowStyle Hidden

Write-Log "cloudflared PID: $($proc.Id)"

# Ждём URL (до 30 сек)
$url = ""
$tries = 0
while ($tries -lt 60) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $tunnelLog) {
        $content = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($content -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $url = $Matches[0]
            break
        }
    }
    $tries++
}

if (-not $url) {
    Write-Log "ERROR: не удалось получить tunnel URL"
    exit 1
}

Write-Log "Tunnel URL: $url"

# Обновить TELEGRAM_WEBHOOK_URL в .env
if (Test-Path $EnvFile) {
    $envContent = Get-Content $EnvFile -Raw
    if ($envContent -match 'TELEGRAM_WEBHOOK_URL=.*') {
        $envContent = $envContent -replace 'TELEGRAM_WEBHOOK_URL=.*', "TELEGRAM_WEBHOOK_URL=$url"
    } else {
        $envContent += "`nTELEGRAM_WEBHOOK_URL=$url"
    }
    Set-Content -Path $EnvFile -Value $envContent -NoNewline
    Write-Log ".env обновлён: TELEGRAM_WEBHOOK_URL=$url"
} else {
    Write-Log "WARNING: .env не найден по пути $EnvFile"
}

# Сохранить PID и URL для мониторинга
@{ pid = $proc.Id; url = $url; started = (Get-Date -Format "o") } |
    ConvertTo-Json | Set-Content "$PSScriptRoot\cloudflared.state.json"

# Перезапустить app-контейнер чтобы подхватил новый webhook URL
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    Write-Log "Перезапускаем app-контейнер..."
    $composeFile = "C:\Users\User\Downloads\fashion-bot\docker\docker-compose.yml"
    & docker compose -f $composeFile restart app 2>&1 | ForEach-Object { Write-Log $_ }
} else {
    Write-Log "docker не найден в PATH — перезапусти контейнер вручную: docker compose restart app"
}

Write-Log "=== Готово. Tunnel: $url ==="

# Держим скрипт живым пока процесс cloudflared работает
$proc.WaitForExit()
Write-Log "cloudflared завершился (exit: $($proc.ExitCode)) — перезапуск через 5 сек..."
Start-Sleep -Seconds 5

# Рестарт себя (loop — Task Scheduler перезапустит при падении)
exit 1
