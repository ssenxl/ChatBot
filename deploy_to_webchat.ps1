# Deploy webchat to docker-webchat server
# Usage: .\deploy_to_webchat.ps1

$Server = "docker-webchat"
$Username = "scm"
$BuildDir = "/home/scm/webchat-build"
$ComposeDir = "/opt/webchat/compose"
$EnvDir = "/opt/webchat/env"
$LogDir = "/opt/webchat/logs"
$DataDir = "/data/webchat/db/postgres"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deploying Webchat to docker-webchat" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# ตรวจสอบ SSH/SCP
if (-not (Get-Command ssh -ErrorAction SilentlyContinue) -or -not (Get-Command scp -ErrorAction SilentlyContinue)) {
    Write-Host "Error: SSH/SCP not found. Install OpenSSH Client." -ForegroundColor Red
    exit 1
}

# สร้าง dirs บน server
Write-Host "`n[1/5] Creating directory structure on server..." -ForegroundColor Green
ssh "$Username@$Server" "mkdir -p $BuildDir"
ssh "$Username@$Server" "sudo mkdir -p $ComposeDir $EnvDir $LogDir $DataDir && sudo chown -R scm:scm /opt/webchat /data/webchat"

# Copy .env
Write-Host "[2/5] Copying .env to server..." -ForegroundColor Green
scp .env "${Username}@${Server}:${EnvDir}/.env"

# Copy ไฟล์ Python และ config
Write-Host "[3/5] Copying application files..." -ForegroundColor Green
$files = @(
    "requirements.txt", "Dockerfile", "docker-compose.yml",
    "chatbot_app.py", "database.py", "response_processor.py",
    "intent_detector.py", "data_cache.py", "powerbi_connector.py",
    "suggestion_engine.py", "mcp_client.py", "mcp_config.json",
    "main.py", "cache.py", "load_balancer.py", "security.py", "utils.py",
    "morning_greeting.py", "check_no_group.py", "gunicorn.conf.py",
    "rate_limit.py", "teams_bot.py"
)
foreach ($file in $files) {
    if (Test-Path $file) {
        scp $file "${Username}@${Server}:${BuildDir}/"
        Write-Host "  Copied: $file" -ForegroundColor Gray
    }
}

# Copy directories
$dirs = @("templates", "static", "mcp_servers", "User_login")
foreach ($dir in $dirs) {
    if (Test-Path $dir) {
        scp -r $dir "${Username}@${Server}:${BuildDir}/"
        Write-Host "  Copied: $dir/" -ForegroundColor Gray
    }
}

# Build image และ start บน server
Write-Host "`n[4/5] Building Docker image on server..." -ForegroundColor Green
ssh "$Username@$Server" @"
set -e
cp $BuildDir/docker-compose.yml $ComposeDir/docker-compose.yml
cd $BuildDir
docker build -t webchat-app:latest .
"@

Write-Host "`n[5/5] Starting containers..." -ForegroundColor Green
ssh "$Username@$Server" @"
set -e
docker compose -f $ComposeDir/docker-compose.yml --env-file $EnvDir/.env up -d
echo ''
echo '=== Container status ==='
docker compose -f $ComposeDir/docker-compose.yml --env-file $EnvDir/.env ps
echo ''
echo '=== Logs (20 lines) ==='
docker compose -f $ComposeDir/docker-compose.yml --env-file $EnvDir/.env logs --tail=20
"@

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "Deploy complete! http://docker-webchat:5000" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
