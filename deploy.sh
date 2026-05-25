#!/bin/bash
# Deploy webchat to docker-webchat server
# Usage: bash deploy.sh

set -e

SERVER="scm@docker-webchat"
BUILD_DIR="/data/docker/webchat-build"   # temp dir สำหรับ build image
COMPOSE_DIR="/opt/webchat/compose"
ENV_DIR="/opt/webchat/env"
LOG_DIR="/opt/webchat/logs"
DATA_DIR="/data/webchat/db/postgres"

echo "=== Syncing source code to server ==="
rsync -avz --progress \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.db' \
  --exclude='.env' \
  --exclude='.git/' \
  --exclude='data/' \
  ./ "$SERVER:$BUILD_DIR/"

echo ""
echo "=== Copying .env to server ==="
scp .env "$SERVER:$ENV_DIR/.env"

echo ""
echo "=== Setup dirs & build image on server ==="
ssh "$SERVER" bash -s << EOF
  set -e

  # สร้าง directory structure ตาม server rule
  mkdir -p $COMPOSE_DIR $ENV_DIR $LOG_DIR $DATA_DIR

  # copy docker-compose.yml ไปที่ /opt/webchat/compose/
  cp $BUILD_DIR/docker-compose.yml $COMPOSE_DIR/docker-compose.yml

  # Build Docker image จาก source code
  cd $BUILD_DIR
  docker build -t webchat-app:latest .

  echo ""
  echo "=== Starting containers ==="
  docker compose -f $COMPOSE_DIR/docker-compose.yml up -d

  echo ""
  echo "=== Container status ==="
  docker compose -f $COMPOSE_DIR/docker-compose.yml ps

  echo ""
  echo "=== Logs (20 lines) ==="
  docker compose -f $COMPOSE_DIR/docker-compose.yml logs --tail=20
EOF

echo ""
echo "Deploy complete! App running at http://docker-webchat:5000"
