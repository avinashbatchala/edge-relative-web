# Run with: powershell -ExecutionPolicy Bypass -File .\run.ps1
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$PythonBin = $env:PYTHON_BIN
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Test-SupportedPython {
    param([string]$Executable, [string[]]$PythonArgs = @())
    try {
        & $Executable @PythonArgs -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$CommandArgs)
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath '.venv') {
        if (-not (Test-SupportedPython $venvPython)) {
            throw 'The existing .venv is not a working Windows Python 3.11+ environment. Rename it to a backup, then rerun this script.'
        }
    } else {
        $selectedPython = $null
        $selectedArgs = @()
        if ($PythonBin) {
            if (-not (Test-SupportedPython $PythonBin)) {
                throw 'PythonBin / PYTHON_BIN must point to a working Python 3.11+ executable.'
            }
            $selectedPython = $PythonBin
        } else {
            foreach ($candidate in @('py', 'python', 'python3')) {
                $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if (-not $command) { continue }
                $candidateArgs = @()
                if ($candidate -eq 'py') { $candidateArgs = @('-3') }
                if (Test-SupportedPython $command.Source $candidateArgs) {
                    $selectedPython = $command.Source
                    $selectedArgs = $candidateArgs
                    break
                }
            }
        }
        if (-not $selectedPython) {
            throw 'Install Python 3.11+ (3.12 recommended), enable its launcher or PATH entry, and rerun. You can also pass -PythonBin C:\path\to\python.exe.'
        }
        Write-Host 'Creating .venv...'
        Invoke-Checked $selectedPython ($selectedArgs + @('-m', 'venv', '.venv'))
    }

    $requirementsHash = (Get-FileHash -LiteralPath 'backend\requirements.txt' -Algorithm SHA256).Hash.ToLowerInvariant()
    $stamp = Join-Path $PSScriptRoot '.venv\.requirements-sha256'
    $installedHash = ''
    if (Test-Path -LiteralPath $stamp) {
        $installedHash = (Get-Content -LiteralPath $stamp -Raw).Trim()
    }
    if ($requirementsHash -ne $installedHash) {
        Write-Host 'Installing backend dependencies...'
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', 'backend/requirements.txt')
        Set-Content -LiteralPath $stamp -Value $requirementsHash -Encoding Ascii
    }

    if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
        $npm = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $npm) {
            throw 'The frontend needs building. Install Node.js 22.18+ with npm, then rerun this script.'
        }
        Write-Host 'Building frontend...'
        Invoke-Checked $npm.Source @('ci', '--prefix', 'frontend')
        Invoke-Checked $npm.Source @('run', 'build', '--prefix', 'frontend')
    }

    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
        Write-Host 'Created .env. Add your Groww credentials there and restart to enable data access.'
    }

    Write-Host "Starting http://127.0.0.1:$Port (Ctrl+C to stop)"
    Invoke-Checked $venvPython @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1', '--env-file', '.env')
} finally {
    Pop-Location
}
