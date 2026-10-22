$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -notmatch '^p\d{3}$') { throw 'Run this on p039 in Windows PowerShell.' }
$taskRepo = Split-Path -Parent $PSScriptRoot
Push-Location $taskRepo
try {
    Write-Output 'ROADWATCH ACCEPTED DELIVERY (read-only)'
    @'
import json
from pathlib import Path
from roadwatch_store import Store
store = Store(Path('runtime'))
items = [i for i in store.incidents() if i['delivery']['status'] == 'accepted']
items.sort(key=lambda i:i['delivery'].get('time',''),reverse=True)
print('Configured event type:', store.setting('event_type'))
if not items:
    print('No accepted deliveries in the current ledger.')
for item in items[:3]:
    response = item['delivery'].get('response') or {}
    print(json.dumps({'incident':item['id'],'camera':item['camera'],'camera_name':item['camera_name'],
        'latest_clip_end':item['observations'][0]['end_utc'],'delivery':item['delivery']},indent=2))
'@ | py -
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the local ledger.' }
    Import-Module MilestonePSTools
    Connect-Vms -ServerAddress 'http://localhost' -AcceptEula | Out-Null
    Clear-VmsCache
    Write-Output 'ROADWATCH ALARM DEFINITIONS'
    $taskDefinitions = @(Get-VmsAlarmDefinition | Where-Object Name -like '*RoadWatch*')
    if ($taskDefinitions.Count -eq 0) { Write-Output 'No alarm definition with RoadWatch in its name.' }
    foreach ($taskDefinition in $taskDefinitions) {
        $taskDefinition.PSObject.Properties |
            Where-Object { $_.Name -match '^(Name|DisplayName|EventType|EventTypeGroup)$|Source|Enabled|Active|TimeProfile' -and $_.Name -notmatch 'Values$' } |
            ForEach-Object {
                $taskValue = if ($null -eq $_.Value) { '(empty)' } else { ($_.Value | Out-String).Trim() }
                '{0}: {1}' -f $_.Name, $taskValue
            }
        if ($taskDefinition.EventTypeValues) {
            'Resolved event name: ' + ($taskDefinition.EventTypeValues.Keys | Where-Object { $taskDefinition.EventTypeValues[$_] -eq $taskDefinition.EventType })
        }
    }
    Write-Output 'RECENT ALARMS (up to 20)'
    Get-AlarmLine | Sort-Object Timestamp -Descending |
        Select-Object -First 20 Timestamp, Message, SourceName, StateName |
        Format-Table -AutoSize | Out-String -Width 220 | Write-Output
    Write-Output 'No events, alarms, or Hafnia requests were created by this diagnostic.'
} finally {
    Pop-Location
}
