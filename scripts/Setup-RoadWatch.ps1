param(
    [string]$CameraName = 'vehicle_breakdown_traffic_queue',
    [string]$BasicUser = 'roadwatch-dev',
    [string]$EventName = 'RoadWatch candidate obstruction',
    [string]$AlarmName = 'RoadWatch - Review road obstruction'
)
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -notmatch '^p\d{3}$') { throw 'Run this script on your hackathon machine, not your laptop.' }
Import-Module MilestonePSTools
Connect-Vms -ServerAddress 'http://localhost' -AcceptEula | Out-Null
$camera = @(Get-VmsCamera | Where-Object Name -eq $CameraName)
if ($camera.Count -ne 1) { throw 'Expected exactly one camera matching CameraName.' }
Write-Host 'First enable Analytics Events in Management Client > Tools > Options. Keep port 9090. No firewall changes are needed.'
$secret = Read-Host -AsSecureString "Password for XProtect basic user $BasicUser (not the gateway password)"
$existing = @(Get-VmsBasicUser | Where-Object Name -eq $BasicUser)
if ($existing.Count -eq 0) {
    $created = New-VmsBasicUser -Name $BasicUser -Password $secret -ErrorAction Stop
    Add-VmsRoleMember -Role Administrators -Sid $created.Sid -ErrorAction Stop | Out-Null
    Write-Host 'Created development user with Administrators access. Use narrower rights for deployment.'
}
$plain = (New-Object System.Management.Automation.PSCredential('unused', $secret)).GetNetworkCredential().Password
try {
    $login = Invoke-RestMethod 'http://localhost/API/IDP/connect/token' -Method Post -Body @{
        grant_type='password'; client_id='GrantValidatorClient'; username=$BasicUser; password=$plain
    }
    $headers = @{ Authorization = 'Bearer ' + $login.access_token }
    $events = (Invoke-RestMethod 'http://localhost/api/rest/v1/analyticsEvents' -Headers $headers).array
    $matches = @($events | Where-Object name -eq $EventName)
    if ($matches.Count -gt 1) { throw 'Duplicate event names exist. Resolve them in Management Client.' }
    if ($matches.Count -eq 0) {
        $body = @{ name=$EventName; description='RoadWatch candidate obstruction; operator review required' } | ConvertTo-Json
        Invoke-RestMethod 'http://localhost/api/rest/v1/analyticsEvents' -Method Post -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
    }
    Clear-VmsCache
    $alarms = @(Get-VmsAlarmDefinition | Where-Object { $_.Name -eq $AlarmName -or $_.Name -like 'RoadWatch*Review road obstruction' })
    if ($alarms.Count -gt 1) { throw 'Multiple RoadWatch alarm definitions exist. Review them in Management Client before continuing.' }
    if ($alarms.Count -eq 0) {
        New-VmsAlarmDefinition -Name $AlarmName -EventTypeGroup 'Analytics Events' -EventType $EventName -Source $camera[0].Path -ErrorAction Stop | Out-Null
    }
    Write-Host 'Setup complete. Verify alarm source and instructions in Management Client, then use Test Event.'
    Write-Host 'No Hafnia requests were made and no test events were emitted.'
} finally {
    $plain = $null; $secret = $null; $login = $null; $headers = $null
}
