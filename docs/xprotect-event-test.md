# One-event integration test on p039

This sends one analytics event and can create a real alarm in the hackathon environment. No Hafnia requests are made. Do not attach a Hafnia request rule to this event.

## Create a basic user

Management Client > Security > Basic Users: create roadwatch-dev with a private strong password, enabled, with password change at next login disabled. Security > Roles: add this basic user to a role permitting the test camera and event triggering. The kit uses Administrators for initial development; that role grants full access and should be replaced by appropriate narrower rights for deployment. Never use the gateway password in a command or file.

## Find the configured event type

In Windows PowerShell on p039:

```powershell
Import-Module MilestonePSTools
Connect-Vms -ServerAddress 'http://localhost' -AcceptEula | Out-Null
Clear-VmsCache
Get-VmsAlarmDefinition | Select-Object Name, EventType
```

Use EventType from the RoadWatch alarm definition. It must be a GUID, not the alarm definition's own ID. Confirm the selected definition targets the RoadWatch analytics event and breakdown camera.

## Send a labelled test

```powershell
py roadwatch_event.py --user roadwatch-dev --event-type-id YOUR-EVENT-TYPE-GUID --test-camera-id 3ccadc04-93aa-46ea-823a-6c0f3de83055
```

Enter the basic user's password privately. HTTP 202 means the event was accepted, not that an alarm has been independently verified. Check Smart Client Alarm Manager for the configured RoadWatch alarm. The tag identifies this as TEST; confirm how tags display in your client.

## Explicitly submit an existing candidate (after the test succeeds)

```powershell
py roadwatch_event.py --user roadwatch-dev --event-type-id YOUR-EVENT-TYPE-GUID --result .\runtime\YOUR-SUMMARY-ID.json
```

The saved raw response is revalidated. Only candidate_obstruction is eligible. A marker beside the result prevents resubmitting the same result path, including after uncertain delivery. It is local protection, not server-side idempotency. Test mode creates a new event each run. No requests are retried automatically.

The candidate event uses the original clip end time and a summary-ID tag. The full evidence remains in the saved JSON; this version does not attach an evidence bookmark or automatically synchronize alarm acknowledgement/clearance. Region polygons are not consumed yet.

Reference: https://doc.developer.milestonesys.com/mipvmsapi/api/events-rest/v1/
