# Diagnostic script to debug panel authentication issues
# Usage: .\scripts\diagnose_auth.ps1

Write-Host "=== YooKassa Panel Auth Diagnostic ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check if .env file exists
Write-Host "[1] Checking .env file..." -ForegroundColor Yellow
if (-Not (Test-Path ".env")) {
    Write-Host "  ❌ .env file not found!" -ForegroundColor Red
    Write-Host "  Copy .env.example to .env and configure it." -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ .env file exists" -ForegroundColor Green

# Step 2: Load and check PANEL_LOGIN and PANEL_PASSWORD
Write-Host ""
Write-Host "[2] Checking PANEL_* variables in .env..." -ForegroundColor Yellow
$envContent = Get-Content ".env" -Raw -Encoding UTF8
$loginMatch = [regex]::Match($envContent, 'PANEL_LOGIN=(.*)$', [System.Text.RegularExpressions.RegexOptions]::Multiline)
$passwordMatch = [regex]::Match($envContent, 'PANEL_PASSWORD=(.*)$', [System.Text.RegularExpressions.RegexOptions]::Multiline)

if (-Not $loginMatch.Success) {
    Write-Host "  ❌ PANEL_LOGIN not found in .env" -ForegroundColor Red
    exit 1
}
if (-Not $passwordMatch.Success) {
    Write-Host "  ❌ PANEL_PASSWORD not found in .env" -ForegroundColor Red
    exit 1
}

$login = $loginMatch.Groups[1].Value.Trim()
$password = $passwordMatch.Groups[1].Value.Trim()

Write-Host "  PANEL_LOGIN length: $($login.Length)" -ForegroundColor White
Write-Host "  PANEL_PASSWORD length: $($password.Length)" -ForegroundColor White

if ($login.Length -eq 0) {
    Write-Host "  ❌ PANEL_LOGIN is empty!" -ForegroundColor Red
    exit 1
}
if ($password.Length -eq 0) {
    Write-Host "  ❌ PANEL_PASSWORD is empty!" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Both credentials are set" -ForegroundColor Green

# Step 3: Check for common issues
Write-Host ""
Write-Host "[3] Checking for common formatting issues..." -ForegroundColor Yellow
$issues = @()

if ($login.StartsWith('"') -or $login.StartsWith("'")) {
    $issues += "PANEL_LOGIN starts with a quote character - remove quotes unless they're part of the actual login"
}
if ($password.StartsWith('"') -or $password.StartsWith("'")) {
    $issues += "PANEL_PASSWORD starts with a quote character - remove quotes unless they're part of the actual password"
}
if ($login -match '\s$') {
    $issues += "PANEL_LOGIN has trailing whitespace"
}
if ($password -match '\s$') {
    $issues += "PANEL_PASSWORD has trailing whitespace"
}

if ($issues.Count -gt 0) {
    Write-Host "  ⚠️  Found potential issues:" -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host "    - $issue" -ForegroundColor Red
    }
} else {
    Write-Host "  ✓ No obvious formatting issues" -ForegroundColor Green
}

# Step 4: Check what backend container sees
Write-Host ""
Write-Host "[4] Checking what backend container sees..." -ForegroundColor Yellow
$backendCheck = docker compose exec -T backend python /app/scripts/check_auth_env.py 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host $backendCheck -ForegroundColor Green
} else {
    Write-Host $backendCheck -ForegroundColor Red
}

# Step 5: Show recent auth-related logs
Write-Host ""
Write-Host "[5] Recent authentication logs from backend:" -ForegroundColor Yellow
docker compose logs backend --tail=50 | Select-String -Pattern "auth|login|verify_credentials" -Context 0,1

Write-Host ""
Write-Host "=== Diagnostic Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Rebuild backend: docker compose up -d --build backend" -ForegroundColor White
Write-Host "2. Check logs: docker compose logs -f backend" -ForegroundColor White
Write-Host "3. Try logging in and watch the logs for 'verify_credentials' output" -ForegroundColor White
