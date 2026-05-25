#!/bin/bash

# Deployment script for MCP Server
# Usage: ./deploy_to_mcp.sh

SERVER="docker-mcp"
USERNAME="scm"
REMOTE_DIR="/home/scm/powerbi-api"
PORT=22

echo "=========================================="
echo "Deploying PowerBI API to MCP Server"
echo "=========================================="
echo "Server: $SERVER"
echo "Username: $USERNAME"
echo "Remote Directory: $REMOTE_DIR"
echo ""

# Create remote directory
echo "Creating remote directory..."
ssh -p $PORT $USERNAME@$SERVER "mkdir -p $REMOTE_DIR"

# Copy necessary files
echo "Copying application files..."
scp -P $PORT requirements.txt $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT Dockerfile $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT docker-compose.yml $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT chatbot_app.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT app.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT auth.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT cache.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT database.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT intent_detector.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT powerbi_api_connector.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT response_processor.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT security.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT suggestion_engine.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT utils.py $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT mcp_config.json $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT mcp_client.py $USERNAME@$SERVER:$REMOTE_DIR/

# Copy directories
echo "Copying directories..."
scp -P $PORT -r templates $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT -r static $USERNAME@$SERVER:$REMOTE_DIR/
scp -P $PORT -r mcp_servers $USERNAME@$SERVER:$REMOTE_DIR/

# Build and run on remote server
echo "Building and starting container on remote server..."
ssh -p $PORT $USERNAME@$SERVER << EOF
cd $REMOTE_DIR
docker-compose down
docker-compose build
docker-compose up -d
echo "Deployment completed!"
docker-compose logs -f --tail=50
EOF

echo ""
echo "=========================================="
echo "Deployment completed successfully!"
echo "=========================================="
