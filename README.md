# RoadWatch
Early Warning for Road Obstructions.

Prototype for operator-reviewed road-obstruction assessments using XProtect and the local Hafnia gateway. No automatic alarms, person detection, or continuous monitoring are implemented yet.

## Run on your hackathon machine

Requires Python 3.11+; no extra packages. Run on p039, not your laptop: the gateway is accessible only on the cloud machine.

Find the camera ID in Windows PowerShell:

```powershell
Connect-Vms -ServerAddress 'http://localhost' -AcceptEula
Get-VmsCamera | Where-Object Name -eq 'vehicle_breakdown_traffic_queue' | Select-Object Name, Id
```

From this repository directory:

```powershell
py roadwatch_check.py --camera-id YOUR-CAMERA-ID --seconds 15
```

Replace YOUR-CAMERA-ID with the actual ID. The command privately prompts for the local gateway password, submits one recent recorded clip, and saves the response and validation result in ignored runtime/. Each completed assessment uses one of your daily 500 Hafnia requests. There are no automatic submission retries. If a request times out, inspect Smart Client History before running again.

Candidates and conflicting or uncertain responses require human review. A clear assessment never automatically closes an incident. Current prompts remain experimental; managed-roadworks classification has produced conflicting answers in manual tests.

## Supporting tools

- Open tools/lane-marker.html in a browser to draw open-lane and closed-work-area regions and export normalized image coordinates. Region data is not yet consumed by the backend.
- See docs/first-camera-test.md and docs/manual-test-results.md for the manual evaluation procedure and limitations of synthetic looping clips.
- HackathonKit is a local reference copy and is excluded from Git, as are credentials and runtime results.
