# RoadWatch

Early warning and operator response for road obstructions, using Hafnia VLM and XProtect. A local hackathon MVP with a minimal incident inbox and camera workspace.

## Start on p039

Python 3.11+ and the provisioned XProtect/Hafnia services are required. The core app needs no pip packages.

```powershell
Set-Location C:\Users\Administrator\Documents\RoadWatch
git pull
py roadwatch_web.py
```

Keep PowerShell open. In **Edge inside p039**, open **http://127.0.0.1:8765**. Do not open that address on your laptop: it refers to the computer running the browser.

1. **Connect** with your XProtect basic username/password and Hafnia gateway password. The gateway password is the provisioned Administrator password. Credentials remain in server memory, never in files, exports, or Git.
2. Cameras are discovered by name. In **Settings**, select the RoadWatch analytics event. Current p039's known event ID is prefilled as a fallback; rediscover/select after a rebuild.
3. **Check a camera**. One completed assessment costs one request. Background status updates do not use VLM credits. Optional recorded UTC intervals support repeatable evaluation within retained footage.
4. Review an incident's observations and UTC window in Smart Client. **Send to XProtect** explicitly, then confirm its alarm. Optionally create a bookmark for the evidence window.
5. Save acknowledgement or response notes. Clearance requires a note and explicit human verification. RoadWatch status does not synchronize XProtect alarm state.

The incident report is a chronological timeline of observations, event delivery, and operator responses. Repeated observation evidence can be expanded. Print timeline provides a clean report layout. Apple system typography is used where available, with Segoe UI fallback on Windows; no proprietary Apple font files are bundled.

Restart after an update with Ctrl+C, git pull, py roadwatch_web.py, then Ctrl+F5 in Edge. Connection credentials and monitoring sessions must be entered/started again after restart. Observations and response history persist.

For a UI-only preview on any computer, run `py roadwatch_web.py --demo`. It uses temporary labelled sample data and blocks live upstream actions. Demo changes disappear when the process stops.

## Monitoring

Open **Monitor**, choose 1-3 cameras and select **Quick test** (up to three checks, one minute apart, five-minute limit) or **Standard** (up to five checks, five minutes apart, thirty-minute limit). Custom limits are optional. The displayed cap is an upper bound; the time limit may stop the session first. A summary already submitted may finish after Stop or the time limit. Camera regions and source details are under **Camera setup**.

RoadWatch reserves request attempts durably, including failed or ambiguous ones. Default daily app cap: 100; gateway reserve: 50. Before each assessment it checks the gateway's actual reported quota. Missing quota or an exhausted reserve blocks requests. Three consecutive failures pause a session. Failed submissions are not automatically retried, and sessions never auto-resume.

Repeated same-camera/type observations within ten minutes group into one open episode. Grouping is not proof of object identity or continuity. Closed items stay closed; a later observation starts another item. Clear/uncertain observations never silently resolve an incident. Event delivery is claimed once per incident before its POST; uncertain delivery remains blocked pending operator investigation.

Automatic event delivery is off by default, configured only under **Settings > Advanced alarm delivery**, and disabled/unselected when a selected camera is synthetic or looping. Experimental live-source auto delivery requires at least two non-overlapping candidate observations. This threshold is not validated to establish a real-world persistent hazard. Keep operator review for the supplied test footage.

## Road regions and optional spatial experiment

In Cameras, **Set road regions** fetches a current JPEG through XProtect (zero VLM requests). Mark at least three boundary points for the open lane; the closed work area may be empty if none exists. Review and save. Recheck after camera movement. These coordinates do **not** alter Hafnia's recorded clip or make VLM results spatially reliable.

Optional local person detection needs a separate package and a local pretrained weights file:

```powershell
py -m pip install -r requirements-optional.txt
$env:ROADWATCH_YOLO_WEIGHTS = 'C:\path\to\official-pretrained-model.pt'
py roadwatch_web.py
```

Obtain an official Ultralytics detection model with COCO class 0 = person. Review its software/model licensing for your intended distribution. The application does not download weights or train models automatically. **Test person position** checks footpoints against saved regions on a fresh setup snapshot. It reports candidate exposure only; it is not evidence of a traffic conflict or a check of a previous incident clip. Missing dependencies are explained without breaking the main app.

## Evaluation and recovery

Settings > **Review test results** labels correct assessments, false alarms, missed hazards, and uncertainty. Export CSV records exact intervals, processing latency and review notes. Synthetic loops are useful repeatable tests, not independent deployment validation.

Settings > **Back up workspace** downloads a ZIP containing the SQLite ledger and setup frames, without passwords. Copy it off p039. To restore, stop the server, retain your current runtime directory, then extract roadwatch.sqlite3 and frames/ from a trusted backup into runtime/. Never overwrite an active database.

Old runtime JSON observations, accepted/uncertain delivery markers, evaluation labels and response notes import idempotently. runtime/ and HackathonKit/ are ignored by Git. Keep source in Git; keep your evidence/ledger backup separately.

## XProtect setup after a rebuild

Enable analytics events manually in Management Client > Tools > Options > Analytics Events. Keep port 9090. Then, on the hackathon machine:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup-RoadWatch.ps1
```

The script prompts privately for a basic-user password, creates missing development user/event/alarm configuration, and leaves existing items/default rules alone. New development users receive Administrators access for the initial hackathon setup; use narrower permissions for deployment. Verify the alarm definition and Test Event manually. Camera and event discovery removes reliance on old IDs after a rebuild. No raw motion-to-Hafnia rules are installed.

## Validation

```powershell
py -m unittest discover -s tests
```

Tests mock upstream calls and exercise durable grouping, reservations, duplicate deliveries, stop behavior, legacy migration, region geometry, HTTP protections, backups and CSV exports. Private p039 API behavior and optional detector accuracy require acceptance testing on that machine. See [demo and acceptance checklist](docs/DEMO.md) and [architecture](docs/ARCHITECTURE.md).

## Scope and limitations

Working components: operator inbox, durable incidents/response history, asynchronous manual checks, bounded polling, quota limits, camera/event discovery, explicit XProtect event delivery, evidence bookmark requests, region setup, optional snapshot person detection, evaluation exports, backups and setup script.

Not established: reliable person-in-lane detection, collision prediction, real-world preventive lead time, automatic camera movement detection, XProtect alarm-state synchronization, or production readiness. Early manual tests exposed roadworks false positives and a possible missed worker. No accuracy or prevention claim is made. All evidence deserves human review.

RoadWatch is an independent hackathon project whose visual style takes cues from Hafnia's navy/blue interface. It is not an official Hafnia product or design system.
