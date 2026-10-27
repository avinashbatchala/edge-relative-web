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
            # winget installs may not be on PATH in an already open terminal.
            if (-not $selectedPython) {
                $pythonPaths = @()
                foreach ($registryRoot in @(
                    'HKCU:\Software\Python\PythonCore',
                    'HKLM:\Software\Python\PythonCore',
                    'HKLM:\Software\WOW6432Node\Python\PythonCore'
                )) {
                    foreach ($entry in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
                        $installKey = Get-Item -LiteralPath ($entry.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
                        if ($installKey) {
                            $executable = $installKey.GetValue('ExecutablePath')
                            if ($executable) { $pythonPaths += $executable }
                            $directory = $installKey.GetValue('')
                            if ($directory) { $pythonPaths += Join-Path $directory 'python.exe' }
                        }
                    }
                }
                foreach ($installRoot in @(
                    (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
                    (Join-Path $env:LOCALAPPDATA 'Python'),
                    $env:ProgramFiles
                )) {
                    foreach ($directory in @(Get-ChildItem -LiteralPath $installRoot -Directory -Filter '*Python*' -ErrorAction SilentlyContinue)) {
                        $pythonPaths += Join-Path $directory.FullName 'python.exe'
                    }
                }
                foreach ($executable in @($pythonPaths | Select-Object -Unique)) {
                    if ((Test-Path -LiteralPath $executable) -and (Test-SupportedPython $executable)) {
                        $selectedPython = $executable
                        break
                    }
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
            foreach ($nodeDirectory in @(
                (Join-Path $env:ProgramFiles 'nodejs'),
                (Join-Path $env:LOCALAPPDATA 'Programs\nodejs'),
                (Join-Path $env:LOCALAPPDATA 'nodejs')
            )) {
                $npmPath = Join-Path $nodeDirectory 'npm.cmd'
                if (Test-Path -LiteralPath $npmPath) {
                    # npm's build scripts also need node on the child process PATH.
                    $env:Path = $nodeDirectory + [IO.Path]::PathSeparator + $env:Path
                    $npm = Get-Command $npmPath -CommandType Application
                    break
                }
            }
        }
        if (-not $npm) {
            throw 'The frontend needs building. Install Node.js 22.18+ with npm, then rerun this script.'
        }
        Write-Host 'Building frontend...'
        Invoke-Checked $npm.Source @('ci', '--prefix', 'frontend')
        Invoke-Checked $npm.Source @('run', 'build', '--prefix', 'frontend')
    }

    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
        Write-Host 'Created .env. Add your Schwab credentials there and restart to enable data access.'
    }

    Write-Host "Starting http://127.0.0.1:$Port (Ctrl+C to stop)"
    Invoke-Checked $venvPython @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', "$Port", '--workers', '1', '--env-file', '.env')
} finally {
    Pop-Location
}
