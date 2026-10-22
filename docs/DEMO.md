# Five-minute demonstration

1. State the problem: persistent road obstructions can cause braking or avoidance before a crash. RoadWatch assists earlier operator intervention; it does not predict or prove prevention of collisions.
2. Show the minimal incident inbox and connect to the local XProtect and Hafnia services. Choose the breakdown camera by name. Explain synthetic looping footage.
3. Run one check (one request) or review a previously saved assessment (zero requests). Show camera/time, factual evidence, and the model output's limitations.
4. Run a second distinct check if budget permits (one request). Show grouped observations and the distinction between clip seconds and elapsed time. Do not claim synthetic loops prove persistence.
5. Send the open candidate to XProtect once (zero Hafnia requests). Open Smart Client Alarm Manager to verify the operator alarm. Optionally add an evidence bookmark, then open it in Smart Client.
6. Acknowledge locally and record a response note. Show saved history after refresh. Demonstrate that Cleared requires explicit verification; do not claim the looping breakdown scene actually cleared.
7. Show a bounded monitor configured for at most two checks. Explain interval, daily cap, reserve, Stop behavior and disabled auto delivery for synthetic footage. Start only when you intend to spend up to two requests.
8. Show a reviewed false-positive or uncertain example and CSV export. Explain what still needs validation before real-road operation.

## Acceptance checklist on p039

- [ ] Restart updated app, connect, and see all eleven camera names.
- [ ] Existing observations, response notes and accepted event receipts migrate.
- [ ] Manual assessment completes and appears in an incident.
- [ ] Another same-type observation groups without a second automatic event.
- [ ] XProtect event accepted and alarm verified in Smart Client.
- [ ] Bookmark opens the correct camera/time interval.
- [ ] Acknowledgement persists after a server restart.
- [ ] Clear/uncertain observations never automatically close an incident.
- [ ] Monitoring starts only explicitly; stops at request/time limit; Stop prevents another check.
- [ ] Quota unavailable or reserve reached blocks new assessments.
- [ ] Road regions save; optional detector absence is explained honestly.
- [ ] Evaluation CSV and workspace backup download successfully.

Local automated tests cannot verify the private p039 service environment. Tick the checklist with actual results, not assumed outcomes.
