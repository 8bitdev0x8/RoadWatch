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

## Local operator web app

On p039, from the repository folder:

```powershell
py roadwatch_web.py
```

Keep PowerShell open and visit http://127.0.0.1:8765 in Edge on p039. The server listens only on loopback; no firewall or Tailscale changes are needed. Ctrl+C stops it.

The page loads existing runtime assessments, requests one new assessment per explicit click, and can submit a reviewed candidate as one XProtect event. Enter the gateway password for assessments and the roadwatch-dev basic-user password for events. Credentials are not stored. Camera and event GUID defaults match the current p039 setup; replace them after a rebuild.

The incident desk provides search, open/review/closed filters, observation details, UTC playback windows, delivery status, and a local operator response history. Operators can acknowledge, mark responding, dismiss, reopen, or confirm clearance with a required note. Clearance requires explicit verification. These local statuses do not synchronize XProtect alarm states. Each assessment remains its own item; repeated observations are not automatically grouped. Camera names are currently mapped only for the known p039 breakdown camera; other cameras display their GUID.

The visual design takes cues from Hafnia's public website: deep navy surfaces, sapphire primary actions, white headings, rounded controls, and clear spacing. It is an independent hackathon interface, not an official Hafnia design system. Video playback stays in XProtect. Forms preserve in-tab drafts while filtering or switching items; credentials are only entered in operation-specific dialogs. Drafts are not durable until saved.

An event marked accepted still needs confirmation in Smart Client. A submission marked attempting may have been delivered: inspect Alarm Manager before retrying. Only one modifying operation runs at a time. The page has no automatic retries, camera video player, geometry detection, acknowledgement synchronization, or continuous monitoring.

Run local HTTP tests without XProtect or Hafnia:

```powershell
py -m unittest discover -s tests
```

## Supporting tools

- Open tools/lane-marker.html in a browser to draw open-lane and closed-work-area regions and export normalized image coordinates. Region data is not yet consumed by the backend.
- See docs/first-camera-test.md and docs/manual-test-results.md for the manual evaluation procedure and limitations of synthetic looping clips.
- HackathonKit is a local reference copy and is excluded from Git, as are credentials and runtime results.
