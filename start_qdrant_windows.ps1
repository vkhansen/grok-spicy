# ================================================
# PowerShell Script: Start Qdrant Docker Container
# ================================================

# Check and start Docker Desktop if not running
$dockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$dockerDesktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $dockerDesktopProcess) {
    Write-Host "Docker Desktop not running. Starting..." -ForegroundColor Yellow
    if (Test-Path $dockerDesktopPath) {
        Start-Process $dockerDesktopPath
        Write-Host "Waiting for Docker Desktop to start..." -ForegroundColor Yellow
        Start-Sleep -Seconds 10
        # Wait for Docker daemon to be ready
        $maxWait = 60
        $waited = 0
        while ($waited -lt $maxWait) {
            try {
                docker version 2>$null | Out-Null
                Write-Host "Docker daemon is ready." -ForegroundColor Green
                break
            } catch {
                Start-Sleep -Seconds 5
                $waited += 5
            }
        }
        if ($waited -ge $maxWait) {
            Write-Host "Failed to start Docker daemon after $maxWait seconds." -ForegroundColor Red
            exit
        }
    } else {
        Write-Host "Docker Desktop not found at $dockerDesktopPath. Please install Docker Desktop." -ForegroundColor Red
        exit
    }
} else {
    Write-Host "Docker Desktop is running." -ForegroundColor Green
}

# Start Qdrant in Docker
Write-Host "Starting Qdrant..." -ForegroundColor Green

# Check if container exists
$containerName = "qdrant_nomic"
# ──────────────────────────────────────────────────────────────
# Aggressive cleanup for Windows/Docker port ghost bindings
# ──────────────────────────────────────────────────────────────

Write-Host "Performing Docker cleanup to avoid 'port already allocated' ghosts..." -ForegroundColor Yellow

# 1. Force-remove the target container again (just in case)
docker rm -f $containerName 2>$null

# 2. Prune unused networks (this fixes most stale port allocations)
Write-Host "Pruning unused networks..." -ForegroundColor Cyan
docker network prune -f

# Optional but helpful: prune stopped containers & dangling stuff (low risk)
docker container prune -f 2>$null
docker system prune -f --filter "until=24h" 2>$null   # only things older than 1 day, very safe

# 3. Check if port 6333 is STILL bound after prune
$portCheck = netstat -ano | Select-String ":6333" | Select-String "LISTENING"
if ($portCheck) {
    Write-Host "Port 6333 still appears allocated after prune! Attempting Docker restart..." -ForegroundColor Red
    
    # Soft restart Docker Desktop (Windows-only)
    Write-Host "Stopping Docker Desktop..." -ForegroundColor Yellow
    Stop-Process -Name "Docker Desktop" -Force -ErrorAction SilentlyContinue
    Stop-Process -Name "com.docker.*" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 8

    Write-Host "Starting Docker Desktop again..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    # Wait for Docker to come back
    $maxWaitDocker = 90
    $waitedDocker = 0
    while ($waitedDocker -lt $maxWaitDocker) {
        try {
            docker version 2>$null | Out-Null
            Write-Host "Docker is back online." -ForegroundColor Green
            break
        } catch {
            Start-Sleep -Seconds 5
            $waitedDocker += 5
            Write-Host "Waiting for Docker ($waitedDocker s)..." -ForegroundColor Yellow
        }
    }
    
    if ($waitedDocker -ge $maxWaitDocker) {
        Write-Host "Docker failed to restart automatically. Please restart Docker Desktop manually and re-run the script." -ForegroundColor Red
        Pause
        exit
    }
    
    # Final check after restart
    $portCheckAfter = netstat -ano | Select-String ":6333" | Select-String "LISTENING"
    if ($portCheckAfter) {
        Write-Host "Port 6333 STILL allocated after Docker restart. Manual intervention needed:" -ForegroundColor Red
        Write-Host "  1. Quit Docker Desktop"
        Write-Host "  2. Delete $env:USERPROFILE\.docker (will be recreated)"
        Write-Host "  3. Restart Docker Desktop"
        Write-Host "  4. Re-run script"
        Pause
        exit
    }
} else {
    Write-Host "Port cleanup looks good." -ForegroundColor Green
}

# ──────────────────────────────────────────────────────────────
# Now safe to create the container
# ──────────────────────────────────────────────────────────────

Write-Host "Creating and starting new container..." -ForegroundColor Green
# Add a retry loop to handle the race condition where Docker API isn't ready
$maxRetries = 5
$retryCount = 0
$containerStarted = $false
while ($retryCount -lt $maxRetries -and !$containerStarted) {
    try {
        docker run -d --name $containerName -p 6333:6333 -p 6334:6334 -v "qdrant_storage:/qdrant/storage" qdrant/qdrant:latest
        Write-Host "New container created and started." -ForegroundColor Green
        $containerStarted = $true
    } catch {
        $retryCount++
        if ($retryCount -ge $maxRetries) {
                Write-Host "Error creating container after $maxRetries retries: $($_.Exception.Message)" -ForegroundColor Red
                Pause
                exit
        } else {
            Write-Host "Attempt $retryCount failed. Retrying in 5 seconds... Error: $($_.Exception.Message)" -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
}

# Wait for Qdrant to be ready
Write-Host "Waiting for Qdrant to be ready..." -ForegroundColor Yellow
$qdrantUrl = "http://localhost:6333"
$maxWait = 60
$waited = 0
while ($waited -lt $maxWait) {
    try {
        Invoke-WebRequest -Uri $qdrantUrl -UseBasicParsing -TimeoutSec 5 | Out-Null
        Write-Host "Qdrant is ready." -ForegroundColor Green
        break
    } catch {
        Start-Sleep -Seconds 5
        $waited += 5
    }
}
if ($waited -ge $maxWait) {
    Write-Host "Failed to connect to Qdrant after $maxWait seconds." -ForegroundColor Red
} else {
    # Test networking from container to Ollama
    Write-Host "Testing networking from container to Ollama..." -ForegroundColor Yellow
    Write-Host "Make sure you have started start_ollama.ps1 in a separate terminal." -ForegroundColor Cyan
    try {
        docker exec $containerName curl -s -f http://host.docker.internal:11434 > $null
        Write-Host "Success: Container can access Ollama at host.docker.internal:11434." -ForegroundColor Green
    } catch {
        Write-Host "Warning: Container cannot access Ollama at host.docker.internal:11434. Ensure Ollama is running and verify Docker networking settings." -ForegroundColor Yellow
        Write-Host "Note: If curl is not available in the Qdrant image, this test may fail even if networking is correct." -ForegroundColor Yellow
        Write-Host "Error details: $($_.Exception.Message)" -ForegroundColor Red
    }
}
# Create a collection that uses nomic-embed-text automatically
Write-Host "Creating collection 'documents'..." -ForegroundColor Green

# Delete if exists
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents" -Method Delete -ErrorAction SilentlyContinue

$createCollection = @{
    vectors = @{
        size = 768
        distance = "Cosine"
        on_disk = $true
    }
    optimizers_config = @{
        default_segment_number = 5
    }
} | ConvertTo-Json -Depth 10

Write-Host "Collection creation payload: $createCollection" -ForegroundColor Yellow
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents" -Method Put -Body $createCollection -ContentType "application/json"

# Collection created successfully

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "Ollama should be running in a separate terminal → http://localhost:11434"
Write-Host "Qdrant dashboard → http://localhost:6333/dashboard"
Write-Host "Collection 'documents' ready with nomic-embed-text embeddings"
Write-Host "You can now use it with LangChain, LlamaIndex, Haystack, etc."

# Optional: Open dashboard
Start-Process "http://localhost:6333/dashboard"
