$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$ports=@(5173,5174)
$before=@{}
foreach($port in $ports){$before[$port]=(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess}
& (Join-Path $PSScriptRoot 'start-preview.ps1') -Target all
if(-not $?){throw 'Launcher failed'}
$instances=@()
foreach($port in $ports){
    $after=(Get-NetTCPConnection -LocalPort $port -State Listen).OwningProcess
    if($before[$port] -and $after -ne $before[$port]){throw "Duplicate/replaced listener at $port"}
    $response=Invoke-WebRequest "http://127.0.0.1:$port/api/state" -UseBasicParsing
    if($response.StatusCode -ne 200){throw "HTTP check failed: $port"}
    $instances+=($response.Content | ConvertFrom-Json).pi.instance
}
if(-not $instances[0] -or $instances[0] -ne $instances[1]){throw 'Frontends do not share the same Pi backend instance.'}
Write-Host "PASS: frontend PIDs unchanged; both frontends use Pi instance $($instances[0])."
