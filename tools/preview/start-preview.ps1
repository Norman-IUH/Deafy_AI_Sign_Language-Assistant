param([ValidateSet('backend','pi','android','all')][string]$Target='all',[switch]$Restart)
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runtimeNode=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$node=if(Test-Path $runtimeNode){$runtimeNode}else{(Get-Command node -ErrorAction SilentlyContinue).Source}
$logs=Join-Path $root '.tools/preview-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$mutex=[Threading.Mutex]::new($false,'Local\DAKTPreview_db3891358a79')
$locked=$false
function Start-ServicePreview([string]$Name,[int]$Port,[string]$Folder,[string]$Exe,[string[]]$Arguments,[string]$Probe){
    $existing=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if($existing){
        $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($existing[0].OwningProcess)"
        if($owner.CommandLine -notlike "*$Folder*"){throw "Port $Port is used by another process. Close it or review its owner; nothing was stopped."}
        if($Restart){
            $previewOwnerId=$existing[0].OwningProcess
            Stop-Process -Id $previewOwnerId
            Wait-Process -Id $previewOwnerId -Timeout 5 -ErrorAction SilentlyContinue
            $existing=$null
        }else{Write-Host "$Name already running on port $Port."}
    }
    if(-not $existing){
        if(-not $Exe -or -not(Test-Path $Exe)){throw "Missing runtime for $Name. See README.md environment setup."}
        Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Folder -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$Name.out.log") -RedirectStandardError (Join-Path $logs "$Name.err.log") | Out-Null
    }
    for($attempt=0;$attempt -lt 30;$attempt++){
        try{$response=Invoke-WebRequest $Probe -UseBasicParsing -TimeoutSec 2;if($response.StatusCode -eq 200){Write-Host "$Name ready: http://localhost:$Port";return}}catch{}
        Start-Sleep -Milliseconds 300
    }
    throw "$Name did not become ready. Check $logs/$Name.err.log"
}
try{
    $locked=$mutex.WaitOne(15000)
    if(-not $locked){throw 'Another preview launcher is busy. Retry in a moment.'}
    $remoteApi=$env:DAKT_PREVIEW_API
    $envFile=Join-Path $root 'backend/.env.local'
    if(-not $remoteApi -and (Test-Path $envFile)){
        foreach($line in Get-Content -LiteralPath $envFile){
            if($line -match '^\s*DAKT_PREVIEW_API\s*=(.*)$'){$remoteApi=$Matches[1].Trim().Trim('"').Trim("'")}
        }
    }
    $remoteApiUri=$null
    if(-not [Uri]::TryCreate($remoteApi,[UriKind]::Absolute,[ref]$remoteApiUri) -or $remoteApiUri.Scheme -notin @('http','https') -or $remoteApiUri.IsLoopback -or $remoteApiUri.Host -eq '0.0.0.0' -or $remoteApiUri.UserInfo -or $remoteApiUri.AbsolutePath -ne '/' -or $remoteApiUri.Query -or $remoteApiUri.Fragment){
        throw 'Set DAKT_PREVIEW_API to the Pi LAN origin in backend/.env.local. Windows runs frontend previews only.'
    }
    $remoteApi=$remoteApiUri.GetLeftPart([UriPartial]::Authority)
    $health=$null
    try{$health=Invoke-RestMethod "$remoteApi/api/health" -TimeoutSec 5}
    catch{Write-Warning 'Pi is unreachable. Frontends will still open and show the disconnected state; no local backend will be started.'}
    if($health -and $health.service -ne 'DAKT-Nc'){throw 'The configured Pi endpoint is not the Sign Assist backend.'}
    Write-Host "Shared backend on Pi: $remoteApi. No Windows backend will be started."
    if($Target -eq 'backend'){return}
    foreach($surface in @(@{Name='pi';Folder='RaspberryPi_7inch';Port=5173},@{Name='android';Folder='Android_App';Port=5174})){
        if($Target -ne 'all' -and $Target -ne $surface.Name){continue}
        $folder=Join-Path $root $surface.Folder
        $vite=Join-Path $folder 'node_modules/vite/bin/vite.js'
        if(-not(Test-Path $vite)){throw "Missing dependencies in $folder. Run npm ci there first."}
        Start-ServicePreview $surface.Name $surface.Port $folder $node @(('"'+$vite+'"'),'--host','127.0.0.1','--port',$surface.Port,'--strictPort') "http://127.0.0.1:$($surface.Port)/"
    }
}catch{Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
