param([switch]$Check)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
$lock = [Threading.Mutex]::new($false, 'Local\DAKT_Nc_Deafy_Demo')
try { $acquired = $lock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }; if (!$acquired) { Write-Host 'A Deafy demo window is already running.'; exit 1 }
try {
    $hotspot = Get-NetAdapter -IncludeHidden | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -like '*Wi-Fi Direct Virtual Adapter*' }
    if (!$hotspot) { throw 'Open Windows Settings > Mobile hotspot, enable deafy (2.4 GHz), then run again.' }
    Write-Host 'PASS - Windows hotspot adapter is active. Confirm SSID deafy in Settings.'
    try {
        $cit = Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 4
        $response = Invoke-WebRequest 'http://127.0.0.1:8001/voices' -UseBasicParsing -TimeoutSec 4
        $voices = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()) | ConvertFrom-Json
    } catch { throw 'Open CIT Voice Studio and wait for its model to load, then run again.' }
    $voiceId = 'Ngọc Huyền'
    if ($cit.status -ne 'ok' -or $cit.device -ne 'cuda' -or $cit.engine -notlike '*VieNeu*TTS*v3*Turbo*' -or $voiceId -notin $voices.id) {
        throw 'In CIT Voice Studio choose VieNeu-TTS-v3-Turbo (GPU) and confirm the female Ngoc Huyen voice.'
    }
    Write-Host "PASS - CIT CUDA, $($cit.sample_rate) Hz, Ngoc Huyen available."
    $ssh = (Get-Command ssh.exe -ErrorAction SilentlyContinue).Source
    if (!$ssh) {
        $git = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
        if ($git) { $ssh = Join-Path (Split-Path $git) '../usr/bin/ssh.exe' }
    }
    if (!$ssh -or !(Test-Path $ssh)) { throw 'Install OpenSSH Client or Git for Windows.' }
    $keyDir = Split-Path $ssh
    $scan = Join-Path $keyDir 'ssh-keyscan.exe'
    $keygen = Join-Path $keyDir 'ssh-keygen.exe'
    $known = (Resolve-Path '.tools/cit-pi-known-hosts').Path
    $trusted = @(Get-Content $known | Where-Object { $_ -match '^deafy\.local\s+ssh-ed25519\s+\S+' })
    if ($trusted.Count -ne 1) { throw 'Missing or ambiguous trusted ED25519 key for deafy.local.' }
    $pin = ($trusted[0] -split '\s+')[2]
    $fingerprint = (& $keygen -lf $known) -split '\s+' | Select-Object -Index 1
    function Find-TrustedPi {
        $job = [Net.Dns]::GetHostAddressesAsync('deafy.local')
        $addresses = @()
        try {
            if ($job.Wait(2000)) { $addresses = @($job.Result | ForEach-Object IPAddressToString) }
        } catch { Write-Host 'deafy.local lookup failed; checking hotspot subnet.' }
        $subnets = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
            $_.InterfaceIndex -in $hotspot.ifIndex -and $_.PrefixLength -ge 24 -and $_.PrefixLength -le 30 -and
                $_.IPAddress -notlike '169.254.*'
        } | ForEach-Object {
            $octets = $_.IPAddress.Split('.')
            $block = 1 -shl (32 - $_.PrefixLength)
            $base = [Math]::Floor([int]$octets[3] / $block) * $block
            ($octets[0..2] -join '.') + ".$base/$($_.PrefixLength)"
        } | Select-Object -Unique)
        foreach ($targets in @(@{Items=$addresses}, @{Items=$subnets})) {
            if (!$targets.Items.Count) { continue }
            # ssh-keyscan can write banners to stderr even on success.
            $ErrorActionPreference = 'Continue'
            $keys = & $scan -T 3 -t ed25519 @($targets.Items) 2>$null
            $ErrorActionPreference = 'Stop'
            foreach ($line in $keys) {
                $fields = $line -split '\s+'
                if ($fields.Count -ge 3 -and $fields[1] -eq 'ssh-ed25519' -and $fields[2] -ceq $pin) {
                    return $fields[0]
                }
            }
        }
        throw 'No trusted Pi answers SSH port 22. Check that Pi is on hotspot deafy and SSH is enabled.'
    }

    $probe = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'check-cit-tunnel.py')))
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try { $piAddress = Find-TrustedPi }
        catch {
            if ($attempt -eq 3 -or $Check) { throw }
            Write-Host $_.Exception.Message
            Start-Sleep -Seconds 3
            continue
        }
        Write-Host "PASS - SSH port 22 and trusted Pi $piAddress ($fingerprint)."
        if ($Check) {
            Write-Host 'Preflight only. Run without -Check to verify CIT from Pi.'
            exit 0
        }
        Write-Host 'Opening CIT tunnel. Keep this window open; enter Pi SSH password if prompted.'
        & $ssh -T -o HostKeyAlias=deafy.local -o StrictHostKeyChecking=yes -o CheckHostIP=no `
            -o "UserKnownHostsFile=$known" -o GlobalKnownHostsFile=none -o UpdateHostKeys=no -o HostKeyAlgorithms=ssh-ed25519 `
            -o ConnectTimeout=6 -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 `
            -R '127.0.0.1:18001:127.0.0.1:8001' "pipi@$piAddress" "printf %s $probe | base64 -d | python3 -u"
        Write-Host "CIT tunnel closed (SSH exit $LASTEXITCODE). Attempt $attempt of 3."
        if ($attempt -lt 3) { Start-Sleep -Seconds 3 }
    }
    throw 'CIT tunnel could not stay open. Check SSH login, CIT and whether another tunnel owns port 18001.'
} catch { Write-Host ("BLOCKED - " + $_.Exception.Message); exit 1 }
finally { $lock.ReleaseMutex(); $lock.Dispose() }



