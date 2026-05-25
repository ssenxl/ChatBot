# MCP Server Deployment Guide

## Overview
This guide explains how to deploy the PowerBI API application to the MCP server at `docker-mcp`.

## Server Credentials
- **Hostname:** docker-mcp
- **Username:** scm
- **Password:** Webchat.2026
- **SSH Port:** 22
- **Remote Port:** 8000

## Prerequisites

### On Local Machine (Windows)
1. Install OpenSSH Client (if not already installed):
   - Go to Settings > Apps > Optional Features
   - Click "Add a feature" and search for "OpenSSH Client"
   - Install it

2. Verify SSH/SCP are available:
   ```powershell
   ssh -V
   scp -V
   ```

### On Remote Server (docker-mcp)
Ensure Docker and Docker Compose are installed:
```bash
docker --version
docker-compose --version
```

## Deployment Methods

### Method 1: Automated Deployment (Recommended)

#### Using PowerShell (Windows)
```powershell
.\deploy_to_mcp.ps1
```

#### Using Bash (Linux/Mac/WSL)
```bash
chmod +x deploy_to_mcp.sh
./deploy_to_mcp.sh
```

### Method 2: Manual Deployment

#### Step 1: Connect to Remote Server
```bash
ssh scm@docker-mcp
# Enter password: Webchat.2026
```

#### Step 2: Create Application Directory
```bash
mkdir -p /home/scm/powerbi-api
cd /home/scm/powerbi-api
```

#### Step 3: Copy Files from Local Machine
On your local machine (in the project directory):
```bash
scp requirements.txt scm@docker-mcp:/home/scm/powerbi-api/
scp Dockerfile scm@docker-mcp:/home/scm/powerbi-api/
scp docker-compose.yml scm@docker-mcp:/home/scm/powerbi-api/
scp *.py scm@docker-mcp:/home/scm/powerbi-api/
scp mcp_config.json scm@docker-mcp:/home/scm/powerbi-api/
scp -r templates scm@docker-mcp:/home/scm/powerbi-api/
scp -r static scm@docker-mcp:/home/scm/powerbi-api/
scp -r mcp_servers scm@docker-mcp:/home/scm/powerbi-api/
```

#### Step 4: Build and Run on Remote Server
```bash
cd /home/scm/powerbi-api
docker-compose down
docker-compose build
docker-compose up -d
```

#### Step 5: Check Logs
```bash
docker-compose logs -f
```

## MCP Configuration

The `mcp_config.json` file has been updated with the correct server configuration:

```json
{
  "docker_mcp": {
    "type": "ssh_tunnel",
    "ssh_host": "docker-mcp",
    "ssh_port": 22,
    "ssh_username": "scm",
    "ssh_password": "Webchat.2026",
    "remote_port": 8000,
    "enabled": true
  }
}
```

## Accessing the Application

Once deployed, the application will be accessible at:
- **Internal:** http://docker-mcp:5000
- **Via SSH Tunnel:** http://localhost:8000 (if tunnel is configured)

## Useful Commands

### View Running Containers
```bash
ssh scm@docker-mcp
docker ps
```

### View Logs
```bash
ssh scm@docker-mcp
cd /home/scm/powerbi-api
docker-compose logs -f
```

### Restart the Application
```bash
ssh scm@docker-mcp
cd /home/scm/powerbi-api
docker-compose restart
```

### Stop the Application
```bash
ssh scm@docker-mcp
cd /home/scm/powerbi-api
docker-compose down
```

### Update the Application
1. Make changes locally
2. Run the deployment script again:
   ```powershell
   .\deploy_to_mcp.ps1
   ```

## Troubleshooting

### SSH Connection Issues
- Verify the hostname is resolvable: `ping docker-mcp`
- Check firewall settings
- Ensure SSH service is running on the remote server

### Docker Build Failures
- Check Docker is installed: `docker --version`
- Verify Docker service is running: `sudo systemctl status docker`
- Check build logs: `docker-compose logs`

### Application Not Starting
- Check port 5000 is not already in use: `netstat -tlnp | grep 5000`
- View container logs: `docker-compose logs`
- Check environment variables in docker-compose.yml

### Permission Issues
- Ensure the user has Docker permissions: `sudo usermod -aG docker scm`
- Restart SSH session after adding user to docker group

## Security Notes

⚠️ **Important Security Considerations:**

1. The SSH password is stored in `mcp_config.json` - consider using SSH keys instead
2. For production, use environment variables or secrets management
3. Restrict SSH access to specific IP addresses
4. Keep Docker and dependencies updated
5. Use HTTPS/TLS for production deployments
6. Implement proper authentication for the application

## Support

For issues or questions, check:
- Docker logs: `docker-compose logs`
- Application logs in the container
- MCP client configuration in `mcp_config.json`
