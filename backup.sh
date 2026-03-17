#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/home/stas/backups
mkdir -p $BACKUP_DIR
docker exec docker-postgres-1 pg_dump -U user fashion | \
  gzip > $BACKUP_DIR/fashion_$DATE.sql.gz
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
echo "Backup done: fashion_$DATE.sql.gz"
