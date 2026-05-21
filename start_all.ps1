param(
    [string]$BindHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5500,
    [int]$UdpPort = 9000,
    [string]$PythonPath = "E:\Anaconda3\envs\access_backend\python.exe",
    [switch]$NoUdp,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$LogDir = Join-Path $BackendDir "runtime_logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StartedProcesses = New-Object System.Collections.ArrayList
$ExternalServices = New-Object System.Collections.ArrayList

function Write-Step {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

function Resolve-Python {
    param([string]$PreferredPath)

    if (Test-Path -Path $PreferredPath -PathType Leaf) {
        return (Resolve-Path -Path $PreferredPath).Path
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    throw "No Python executable found. Set -PythonPath to the backend environment python.exe."
}

function Test-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 2
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        return $false
    }
}

function Wait-HttpOk {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $Url -TimeoutSeconds 2) {
            Write-Step "$Name is ready: $Url"
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Warning "$Name did not become ready within $TimeoutSeconds seconds: $Url"
    return $false
}

function Test-UdpPortInUse {
    param([int]$Port)

    $pattern = "^\s*UDP\s+\S+:$Port\s+"
    $rows = netstat -ano -p udp | Select-String -Pattern $pattern
    return ($null -ne $rows)
}

function ConvertTo-ArgumentString {
    param([string[]]$Arguments)

    $quoted = @()
    foreach ($arg in $Arguments) {
        if ($arg -match '[\s"]') {
            $quoted += '"' + ($arg -replace '"', '\"') + '"'
        }
        else {
            $quoted += $arg
        }
    }
    return ($quoted -join " ")
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    Write-Step "Starting $Name"
    Write-Step "  working directory: $WorkingDirectory"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ConvertTo-ArgumentString -Arguments $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $process.EnableRaisingEvents = $true

    if (-not $process.Start()) {
        throw "Failed to start $Name"
    }

    [void]$StartedProcesses.Add([pscustomobject]@{
        Name = $Name
        Process = $process
        Stdout = $StdoutPath
        Stderr = $StderrPath
    })

    return $process
}

function Stop-StartedProcesses {
    foreach ($item in @($StartedProcesses)) {
        $process = $item.Process
        if ($null -ne $process -and -not $process.HasExited) {
            Write-Step "Stopping $($item.Name) (PID $($process.Id))"
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -Path $BackendDir -PathType Container)) {
    throw "Backend directory not found: $BackendDir"
}
if (-not (Test-Path -Path $FrontendDir -PathType Container)) {
    throw "Frontend directory not found: $FrontendDir"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Python = Resolve-Python -PreferredPath $PythonPath

$BackendHealthUrl = "http://${BindHost}:$BackendPort/api/health"
$FrontendUrl = "http://${BindHost}:$FrontendPort/"
$FrontendScriptUrl = "http://${BindHost}:$FrontendPort/app.js"

Write-Step "Project root: $RootDir"
Write-Step "Frontend root: $FrontendDir"
Write-Step "Python: $Python"

try {
    if (Test-HttpOk -Url $BackendHealthUrl -TimeoutSeconds 1) {
        Write-Step "Backend already running: $BackendHealthUrl"
        [void]$ExternalServices.Add("backend")
    }
    else {
        Start-ManagedProcess `
            -Name "backend-api" `
            -FilePath $Python `
            -Arguments @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", "$BackendPort") `
            -WorkingDirectory $BackendDir `
            -StdoutPath (Join-Path $LogDir "backend_api_$Stamp.out.log") `
            -StderrPath (Join-Path $LogDir "backend_api_$Stamp.err.log") | Out-Null
    }

    if (-not $NoUdp) {
        if (Test-UdpPortInUse -Port $UdpPort) {
            Write-Step "UDP listener port already in use: 0.0.0.0:$UdpPort"
            [void]$ExternalServices.Add("udp-listener")
        }
        else {
            Start-ManagedProcess `
                -Name "udp-listener" `
                -FilePath $Python `
                -Arguments @("net_build\udp_packet_listener.py") `
                -WorkingDirectory $BackendDir `
                -StdoutPath (Join-Path $LogDir "udp_listener_$Stamp.out.log") `
                -StderrPath (Join-Path $LogDir "udp_listener_$Stamp.err.log") | Out-Null
        }
    }

    if ((Test-HttpOk -Url $FrontendUrl -TimeoutSeconds 1) -and (Test-HttpOk -Url $FrontendScriptUrl -TimeoutSeconds 1)) {
        Write-Step "Frontend already running: $FrontendUrl"
        [void]$ExternalServices.Add("frontend")
    }
    else {
        Start-ManagedProcess `
            -Name "frontend-static" `
            -FilePath $Python `
            -Arguments @("-m", "http.server", "$FrontendPort", "--bind", $BindHost) `
            -WorkingDirectory $FrontendDir `
            -StdoutPath (Join-Path $LogDir "frontend_$Stamp.out.log") `
            -StderrPath (Join-Path $LogDir "frontend_$Stamp.err.log") | Out-Null
    }

    Start-Sleep -Seconds 1

    foreach ($item in @($StartedProcesses)) {
        if ($item.Process.HasExited) {
            Write-Warning "$($item.Name) exited early. Check logs:"
            Write-Warning "  $($item.Stdout)"
            Write-Warning "  $($item.Stderr)"
        }
    }

    [void](Wait-HttpOk -Name "Backend API" -Url $BackendHealthUrl -TimeoutSeconds 20)
    [void](Wait-HttpOk -Name "Frontend" -Url $FrontendUrl -TimeoutSeconds 15)
    [void](Wait-HttpOk -Name "Frontend script" -Url $FrontendScriptUrl -TimeoutSeconds 15)

    Write-Host ""
    Write-Step "All requested services are ready."
    Write-Host "  Frontend: $FrontendUrl"
    Write-Host "  Backend : $BackendHealthUrl"
    if (-not $NoUdp) {
        Write-Host "  UDP     : 0.0.0.0:$UdpPort"
    }
    if ($ExternalServices.Count -gt 0) {
        Write-Host "  Reused existing services: $($ExternalServices -join ', ')"
    }
    Write-Host ""

    if ($SmokeTest) {
        Write-Step "Smoke test finished."
        return
    }

    Write-Step "Press Ctrl+C to stop services started by this script."
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($item in @($StartedProcesses)) {
            if ($item.Process.HasExited) {
                Write-Warning "$($item.Name) has exited. See logs: $($item.Stderr)"
            }
        }
    }
}
finally {
    if ($SmokeTest) {
        Stop-StartedProcesses
    }
}
