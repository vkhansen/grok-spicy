# ================================================
# PowerShell Script: Start Ollama Service
# ================================================

# Permanently disable the Ollama auto-start service to prevent conflicts
$ollamaServiceCheck = Get-Service -Name "Ollama" -ErrorAction SilentlyContinue
if ($ollamaServiceCheck -and $ollamaServiceCheck.StartupType -ne 'Disabled') {
    Write-Host "Ollama's background service is set to auto-start. Disabling it now to prevent port conflicts." -ForegroundColor Yellow
    try {
        Set-Service -Name "Ollama" -StartupType "Disabled" -ErrorAction Stop
        Write-Host "Ollama auto-start has been permanently disabled." -ForegroundColor Green
    } catch {
        Write-Host "Failed to disable Ollama auto-start. You may need to run this script as an Administrator." -ForegroundColor Red
        Write-Host "Error details: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "Note: Administrator privileges may be required for Ollama installation. Consider running this script as Administrator if you encounter issues." -ForegroundColor Yellow

# Check and Install Ollama if necessary
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Ollama not found. Installing Ollama..." -ForegroundColor Green
    Invoke-WebRequest -Uri https://ollama.com/download/OllamaSetup.exe -OutFile "$env:TEMP\OllamaSetup.exe"
    Start-Process -Wait -FilePath "$env:TEMP\OllamaSetup.exe"
    # Wait for installation to complete and service to start
    Start-Sleep -Seconds 15
} else {
    Write-Host "Ollama is installed." -ForegroundColor Green
}

# Refresh PATH to pick up Ollama if it was just installed
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Refreshing environment variables to find Ollama..." -ForegroundColor Yellow
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    
    # Fallback to common install location if still not found
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        $ollamaPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        if (Test-Path $ollamaPath) {
             Write-Host "Found Ollama at default location. Adding to PATH." -ForegroundColor Yellow
             $env:Path += ";$(Split-Path $ollamaPath -Parent)"
        }
    }
    
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Host "Ollama installed but command not found. Please restart your terminal and try again." -ForegroundColor Red
        Pause
        exit
    }
}

# Stop the Ollama service if it's running, as this is the most reliable way
$ollamaService = Get-Service -Name "Ollama" -ErrorAction SilentlyContinue
if ($ollamaService -and $ollamaService.Status -eq 'Running') {
    Write-Host "Stopping existing Ollama background service..." -ForegroundColor Yellow
    Stop-Service -Name "Ollama" -Force
    Start-Sleep -Seconds 10
}

# As a fallback, kill any remaining Ollama processes to be certain
$ollamaProcesses = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if ($ollamaProcesses) {
    Write-Host "Stopping any lingering Ollama processes..." -ForegroundColor Yellow
    $ollamaProcesses | Stop-Process -Force
    Start-Sleep -Seconds 5
}

# Check if port is in use, and if so, try to kill the process holding it
$portInUse = netstat -ano | Select-String ":11434" | Select-String "LISTENING"
if ($portInUse) {
    Write-Host "Port 11434 is still in use after initial cleanup." -ForegroundColor Yellow
    
    # Extract the PID from the netstat output
    $pid = ($portInUse | ForEach-Object { $_.ToString().Split(' ',[System.StringSplitOptions]::RemoveEmptyEntries)[-1] })
    
    if ($pid) {
        try {
            $processToKill = Get-Process -Id $pid -ErrorAction Stop
            Write-Host "Attempting to forcefully terminate process '$($processToKill.ProcessName)' (PID: $pid) which is holding the port." -ForegroundColor Red
            Stop-Process -Id $pid -Force
            Start-Sleep -Seconds 5 # Wait for the port to be released
        } catch {
             Write-Host "Failed to terminate process PID $pid. It may require administrator privileges. Error: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    # Final check after the targeted kill
    $portInUseAfterKill = netstat -ano | Select-String ":11434" | Select-String "LISTENING"
    if ($portInUseAfterKill) {
        Write-Host "Port 11434 is STILL in use after targeted termination. Please close the application using the port manually and re-run the script." -ForegroundColor Red
        Pause
        exit
    } else {
        Write-Host "Port 11434 was successfully freed." -ForegroundColor Green
    }
} else {
    Write-Host "Port 11434 is free." -ForegroundColor Green
}

# Configure Ollama to listen on all network interfaces so Docker containers and Roo Code can connect
Write-Host "Configuring Ollama to listen on all network interfaces (0.0.0.0)..." -ForegroundColor Yellow
$env:OLLAMA_HOST = '0.0.0.0'

# Start ollama serve as a background job, explicitly passing the host variable
# and redirecting stderr->stdout (2>&1) to prevent PowerShell NativeCommandError spam
Write-Host "Starting 'ollama serve' as a background job..." -ForegroundColor Cyan
$ollamaJob = Start-Job -ScriptBlock {
    param($host_addr)
    $env:OLLAMA_HOST = $host_addr
    ollama serve 2>&1
} -ArgumentList $env:OLLAMA_HOST

# Wait for the server to initialize and verify it's responding
Write-Host "Waiting for the Ollama server to initialize..." -ForegroundColor Yellow
$maxStartWait = 30
$startWaited = 0
$serverReady = $false
while ($startWaited -lt $maxStartWait) {
    Start-Sleep -Seconds 2
    $startWaited += 2
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $serverReady = $true
            Write-Host "Ollama server is running and responding at http://127.0.0.1:11434" -ForegroundColor Green
            break
        }
    } catch {
        Write-Host "  Waiting... ($startWaited s)" -ForegroundColor DarkGray
    }
}

if (-not $serverReady) {
    Write-Host "Ollama server failed to start within $maxStartWait seconds." -ForegroundColor Red
    Write-Host "Background job state: $($ollamaJob.State)" -ForegroundColor Red
    Write-Host "Job output:" -ForegroundColor Yellow
    Receive-Job $ollamaJob
    Pause
    exit
}

Write-Host "Downloading embedding models... This will connect to the background server." -ForegroundColor Green
ollama pull nomic-embed-text
ollama pull mbaxi-embed-large:v1

# Final verification that the server is still healthy
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop | Out-Null
    Write-Host "`n============================================" -ForegroundColor Green
    Write-Host " Ollama is READY at http://127.0.0.1:11434" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
} catch {
    Write-Host "WARNING: Ollama server may have stopped after model pull." -ForegroundColor Red
}

Write-Host "You can now run start_qdrant.ps1 in a separate terminal." -ForegroundColor Cyan
Write-Host "Press CTRL+C in THIS terminal when you are finished to stop Ollama." -ForegroundColor Cyan
Write-Host ""

# Keep the terminal open and display logs from the background job.
# When the user presses Ctrl+C, the 'finally' block cleans up.
try {
    while ($ollamaJob.State -eq 'Running') {
        Receive-Job -Job $ollamaJob
        Start-Sleep -Milliseconds 500
    }
    # If the job stopped on its own, show remaining output
    Write-Host "Ollama background job ended unexpectedly (State: $($ollamaJob.State))." -ForegroundColor Yellow
    Receive-Job -Job $ollamaJob
}
finally {
    Write-Host "`nCleaning up Ollama..." -ForegroundColor Yellow
    Stop-Job -Job $ollamaJob -ErrorAction SilentlyContinue
    Remove-Job -Job $ollamaJob -ErrorAction SilentlyContinue
    # Also kill any remaining ollama processes to fully release the port
    Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "Ollama has been stopped." -ForegroundColor Green
}
