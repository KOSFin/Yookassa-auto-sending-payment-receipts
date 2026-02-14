$ErrorActionPreference = 'Stop'

Write-Host 'Stopping orphan/old proxy container (if exists)...'
docker compose rm -s -f proxy | Out-Null

Write-Host 'Starting stack with rebuild...'
docker compose up -d --build --remove-orphans

Write-Host 'Done.'
