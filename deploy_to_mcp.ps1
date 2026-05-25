# Deployment script for MCP Server (PowerShell version)
# Usage: .\deploy_to_mcp.ps1

$Server = "docker-mcp"
$Username = "scm"
$RemoteDir = "/home/scm/powerbi-api"
$Port = 22

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deploying PowerBI API to MCP Server" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Server: $Server"
Write-Host "Username: $Username"
Write-Host "Remote Directory: $RemoteDir"
Write-Host ""

# Check if SCP and SSH are available
$sshExists = Get-Command ssh -ErrorAction SilentlyContinue
$scpExists = Get-Command scp -ErrorAction SilentlyContinue

if (-not $sshExists -or -not $scpExists) {
    Write-Host "Error: SSH/SCP not found. Please install OpenSSH client." -ForegroundColor Red
    Write-Host "On Windows, you can install it via: Settings > Apps > Optional Features > OpenSSH Client" -ForegroundColor Yellow
    exit 1
}

# Create remote directory
Write-Host "Creating remote directory..." -ForegroundColor Green
ssh -p $Port $Username@$Server "mkdir -p $RemoteDir"

# Files to copy
$files = @(
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "chatbot_app.py",
    "app.py",
    "auth.py",
    "cache.py",
    "database.py",
    "intent_detector.py",
    "powerbi_api_connector.py",
    "response_processor.py",
    "security.py",
    "suggestion_engine.py",
    "utils.py",
    "mcp_config.json",
    "mcp_client.py"
)

# Copy files
Write-Host "Copying application files..." -ForegroundColor Green
foreach ($file in $files) {
    if (Test-Path $file) {
        scp -P $Port $file "$Username@${Server}:${RemoteDir}/"
        Write-Host "  Copied: $file" -ForegroundColor Gray
    } else {
        Write-Host "  Warning: $file not found, skipping..." -ForegroundColor Yellow
    }
}

# Copy directories
Write-Host "Copying directories..." -ForegroundColor Green
$directories = @("templates", "static", "mcp_servers")
foreach ($dir in $directories) {
    if (Test-Path $dir) {
        scp -P $Port -r $dir "$Username@${Server}:${RemoteDir}/"
        Write-Host "  Copied: $dir/" -ForegroundColor Gray
    } else {
        Write-Host "  Warning: $dir/ not found, skipping..." -ForegroundColor Yellow
    }
}

# Build and run on remote server
Write-Host "Building and starting container on remote server..." -ForegroundColor Green
$remoteCommand = @"
cd $RemoteDir
docker-compose down
docker-compose build
docker-compose up -d
echo "Deployment completed!"
docker-compose logs -f --tail=50
"@

ssh -p $Port $Username@$Server $remoteCommand

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deployment completed successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
