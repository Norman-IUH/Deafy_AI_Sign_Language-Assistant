param([ValidateSet('old','new')][string]$Profile='new',[int]$CameraIndex=0,[switch]$Stop,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$runtimeDir=Join-Path $root '.tools/model-test'
$runtimeFile=Join-Path $runtimeDir 'runtime.json'
$python=Join-Path $root '.venv-model-test/Scripts/python.exe'
$serverFile=Join-Path $root 'backend/model_test_server.py'
$mutex=[Threading.Mutex]::new($false,'Local\DAKTModelTest_20261105')
$locked=$false
function Probe-Runtime($saved){
    if(-not $saved -or $saved.port -notin @(5173,5175,5176)){return $null}
    try{
        $state=Invoke-RestMethod "http://127.0.0.1:$($saved.port)/api/state" -TimeoutSec 2
        if($state.service -eq 'DAKT-Nc-model-test' -and $state.session -eq $saved.session){return $state}
    }catch{}
    return $null
}
try{
    $locked=$mutex.WaitOne(10000)
    if(-not $locked){throw 'Another model-test launcher is busy.'}
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $saved=if(Test-Path -LiteralPath $runtimeFile){Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json}else{$null}
    $state=Probe-Runtime $saved
    if($Stop){
        if(-not $state){Write-Host 'No verified model-test server is running. No process was stopped.';return}
        Invoke-RestMethod "http://127.0.0.1:$($saved.port)/api/shutdown" -Method Post -Headers @{'X-Model-Test-Session'=$saved.session} -TimeoutSec 5 | Out-Null
        Wait-Process -Id $saved.pid -Timeout 10 -ErrorAction SilentlyContinue
        Write-Host 'Model-test shutdown requested; camera will be released. Pi services were not touched.'
        return
    }
    if(-not(Test-Path -LiteralPath $python)){
        $bootstrap=Join-Path $root 'backend/.venv/Scripts/python.exe'
        if(-not(Test-Path -LiteralPath $bootstrap)){throw 'Set up backend/.venv first. See HUONG_DAN_THU_MODEL_WINDOWS.md.'}
        & $bootstrap (Join-Path $root 'scripts/prepare_model_test_env.py')
        if($LASTEXITCODE -ne 0){throw 'Cannot prepare test environment. See HUONG_DAN_THU_MODEL_WINDOWS.md.'}
    }
    if(-not $state){
        if($saved){
            $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.pid)" -ErrorAction SilentlyContinue
            if($owner -and $owner.CommandLine.Contains($serverFile) -and $owner.CommandLine.Contains($saved.session)){throw 'Model-test process is still starting or shutting down. Retry shortly; nothing was stopped.'}
        }
        $port=$null
        foreach($candidate in @(5173,5175,5176)){
            if(-not(Get-NetTCPConnection -State Listen -LocalPort $candidate -ErrorAction SilentlyContinue)){$port=$candidate;break}
        }
        if(-not $port){throw 'Ports 5173/5175/5176 are busy. No existing application was stopped.'}
        # Only this child launch environment is cleared; never load production .env.local.
        Get-ChildItem Env: | Where-Object {$_.Name -match '^(DAKT_|GEMINI_|GROQ_|GOOGLE_|THINGSPEAK_)'} | ForEach-Object {Remove-Item -LiteralPath ('Env:'+$_.Name)}
        $session=[Guid]::NewGuid().ToString('N')
        $worker=Start-Process -FilePath $python -ArgumentList @(('"'+$serverFile+'"'),'--profile',$Profile,'--port',$port,'--camera-index',$CameraIndex,'--session',$session) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'server.out.log') -RedirectStandardError (Join-Path $runtimeDir 'server.err.log') -PassThru
        $saved=@{pid=$worker.Id;port=$port;session=$session;profile=$Profile}
        $saved | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding UTF8
        for($attempt=0;$attempt -lt 50;$attempt++){
            $state=Probe-Runtime $saved
            if($state){break}
            if($worker.HasExited){break}
            Start-Sleep -Milliseconds 200
        }
        if(-not $state){
            $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$($worker.Id)" -ErrorAction SilentlyContinue
            if($owner -and $owner.CommandLine.Contains($serverFile) -and $owner.CommandLine.Contains($session)){Stop-Process -Id $worker.Id}
            throw "Model-test startup failed. See $runtimeDir/server.err.log"
        }
    }
    $headers=@{'X-Model-Test-Session'=$saved.session}
    if($state.profile -ne $Profile){Invoke-RestMethod "http://127.0.0.1:$($saved.port)/api/model" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{profile=$Profile}|ConvertTo-Json) -TimeoutSec 15 | Out-Null}
    Invoke-RestMethod "http://127.0.0.1:$($saved.port)/api/camera/start" -Method Post -Headers $headers -TimeoutSec 10 | Out-Null
    $url="http://localhost:$($saved.port)"
    Write-Host "Windows model test: $url (profile $Profile). No Pi/cloud/MQTT/database connection."
    if(-not $NoBrowser){Start-Process $url | Out-Null}
}catch{Write-Host ('ERROR: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
