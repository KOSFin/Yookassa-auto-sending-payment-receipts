$ErrorActionPreference = 'Stop'

Write-Host 'Stopping orphan/old proxy container (if exists)...'
docker compose rm -s -f proxy | Out-Null

Write-Host 'Starting stack with rebuild...'
$composeArgs = @('up', '-d', '--build', '--remove-orphans')
if ($env:COMPOSE_FORCE_RECREATE -eq '1') {
	$composeArgs += '--force-recreate'
}
docker compose @composeArgs

Write-Host 'Done.'
