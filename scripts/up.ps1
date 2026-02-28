$ErrorActionPreference = 'Stop'

if (-not (Test-Path .env)) {
	if (Test-Path .env.example) {
		Write-Host '.env not found. Creating from .env.example...'
		Copy-Item .env.example .env
	} else {
		throw '.env and .env.example are both missing.'
	}
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
	throw 'Docker CLI not found. Install Docker Desktop/Engine first.'
}

if ($env:FORCE_RESET_PROXY -eq '1') {
	Write-Host 'Force-resetting proxy container...'
	docker compose rm -s -f proxy | Out-Null
}

Write-Host 'Starting stack with rebuild...'
$composeArgs = @('up', '-d', '--build', '--remove-orphans')
if ($env:COMPOSE_FORCE_RECREATE -eq '1') {
	$composeArgs += '--force-recreate'
}
docker compose @composeArgs

Write-Host 'Current services:'
docker compose ps

Write-Host 'Health endpoint check (proxy):'
try {
	Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1/api/health' -TimeoutSec 6 | Out-Null
	Write-Host 'OK: http://127.0.0.1/api/health'
} catch {
	Write-Host 'Warning: health check failed via localhost proxy. Check `docker compose logs proxy backend`.'
}

Write-Host 'Done.'
