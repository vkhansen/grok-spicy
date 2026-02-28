# Check if global Python is installed
try {
    $globalPython = py -3.13 --version 2>&1
    Write-Host "Found Python 3.13: $globalPython"
}
catch {
    Write-Error "Python 3.13 is not installed or 'py' is not in the PATH. Please install Python 3.13."
    exit 1
}

# Create virtual environment
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment with Python 3.13..."
    py -3.13 -m venv venv
} else {
    Write-Host "Virtual environment already exists."
}

# Define venv python path
$venvPython = ".\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment python not found at $venvPython. Venv creation might have failed."
    exit 1
}

# Activate virtual environment (optional for script execution if we use direct path, but good for user awareness)
# We won't rely on activation for the script commands, but we'll use direct path to ensure venv is used.
Write-Host "Targeting virtual environment python at $venvPython"

# Upgrade pip
Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip

# Check for Git
try {
    git --version | Out-Null
} catch {
    Write-Error "Git is not installed or not in PATH. Required for pulling source."
    exit 1
}


# Install dependencies
Write-Host "Installing dependencies..."

# Install root requirements if they exist
if (Test-Path "requirements.txt") {
    Write-Host "Installing dependencies from root requirements.txt..."
    & $venvPython -m pip install -r requirements.txt
}


Write-Host "Setup complete! To activate the environment, run: .\venv\Scripts\Activate.ps1"
