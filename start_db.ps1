# start_db.ps1 -- Start PostgreSQL and set up frauddb
# Run from project root before starting the backend

$PGBIN  = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
$PGDATA = "$env:USERPROFILE\scoop\apps\postgresql\current\data"
$PGLOG  = "$env:USERPROFILE\pg.log"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host " Fraud Detection DB Startup Script"   -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# 1. Start PostgreSQL
Write-Host ""
Write-Host "[1/4] Starting PostgreSQL on port 5432..." -ForegroundColor Yellow
& "$PGBIN\pg_ctl.exe" start -D "$PGDATA" -o "-p 5432 -h 127.0.0.1" -l "$PGLOG" -w -t 30
Start-Sleep -Seconds 2

$listening = netstat -an | Select-String "127.0.0.1:5432.*LISTENING"
if (-not $listening) {
    Write-Host "  [ERROR] PostgreSQL is NOT listening. Check: $PGLOG" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] PostgreSQL is listening on 127.0.0.1:5432" -ForegroundColor Green

# 2. Create user fraud if not exists
Write-Host ""
Write-Host "[2/4] Creating user 'fraud'..." -ForegroundColor Yellow
$createUserSQL = 'DO $body$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = ' + "'fraud'" + ') THEN CREATE USER fraud WITH PASSWORD ' + "'fraud_pass'" + '; END IF; END $body$;'
& "$PGBIN\psql.exe" -h 127.0.0.1 -p 5432 -U postgres postgres -c $createUserSQL
Write-Host "  Done." -ForegroundColor Green

# 3. Create database frauddb if not exists
Write-Host ""
Write-Host "[3/4] Creating database 'frauddb'..." -ForegroundColor Yellow
$dbCheck = & "$PGBIN\psql.exe" -h 127.0.0.1 -p 5432 -U postgres postgres -tAc "SELECT 1 FROM pg_database WHERE datname='frauddb';"
if ($dbCheck -ne $null -and $dbCheck.ToString().Trim() -eq "1") {
    Write-Host "  [OK] 'frauddb' already exists." -ForegroundColor Green
} else {
    & "$PGBIN\createdb.exe" -h 127.0.0.1 -p 5432 -U postgres -O fraud frauddb
    Write-Host "  [OK] 'frauddb' created." -ForegroundColor Green
}
& "$PGBIN\psql.exe" -h 127.0.0.1 -p 5432 -U postgres postgres -c "GRANT ALL PRIVILEGES ON DATABASE frauddb TO fraud;" | Out-Null

# 4. Verify connection
Write-Host ""
Write-Host "[4/4] Verifying connection as 'fraud'..." -ForegroundColor Yellow
& "$PGBIN\psql.exe" -h 127.0.0.1 -p 5432 -U fraud frauddb -c "SELECT 'frauddb is ready!' AS status;"

Write-Host ""
Write-Host "=====================================" -ForegroundColor Green
Write-Host " DATABASE READY!" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next -- open TWO more terminals:" -ForegroundColor White
Write-Host ""
Write-Host "TERMINAL 2 (Backend):" -ForegroundColor Yellow
Write-Host "  cd backend" -ForegroundColor Gray
Write-Host "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Gray
Write-Host ""
Write-Host "TERMINAL 3 (Frontend):" -ForegroundColor Yellow
Write-Host "  cd frontend" -ForegroundColor Gray
Write-Host "  npm run dev" -ForegroundColor Gray
Write-Host ""
