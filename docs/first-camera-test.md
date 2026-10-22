# First RoadWatch camera test

Goal: establish whether Hafnia can distinguish a visible lane obstruction from ordinary traffic before building automated alerts.

## Run on p039

1. Open XProtect Smart Client, connecting to localhost with current-user Windows authentication.
2. Open Summarization > Generate and add vehicle_breakdown_traffic_queue.
3. Switch to playback a few minutes back. Select a recorded interval containing one breakdown sequence, ideally 10-15 seconds. The clip loops every 15-17 seconds; avoid a loop boundary if possible.
4. Create a prompt titled RoadWatch - Road obstruction assessment. Paste prompts/road-obstruction.txt into its content and save. Keep the default model.
5. Generate once, then inspect History. Record the exact UTC interval and answer below.
6. Repeat with highway_traffic_overcast_weather and traffic_flows_in_the_open_lanes as contrast cases. Expected answers are review targets, not ground truth: inspect the actual footage yourself. Fog may warrant uncertain; planned roadworks should not alone trigger an obstruction finding.

Budget: three completed summaries use three of the daily 500 requests. No automation is enabled by this procedure.

## Record results

| Camera | UTC start/end | Human observation | Model response | Processing time | Error or disagreement |
|---|---|---|---|---|---|
| vehicle_breakdown_traffic_queue | | | | | |
| highway_traffic_overcast_weather | | | | | |
| traffic_flows_in_the_open_lanes | | | | | |

Copy the responses exactly, including malformed JSON. The application must validate the response format and route invalid or uncertain results to review rather than treating them as clear.

## Interpretation

The breakdown footage is synthetic and repeats. Repeated detections across loop boundaries do not establish a continuing real-world incident. A short looping demonstration cannot validate a 45-second persistence threshold or preventive warning time.

Application timestamps, rather than model estimates, will track observations across distinct clips. An unobserved interval is not evidence of uninterrupted obstruction. Acknowledgement and clearance are separate states; missing or uncertain observations cannot close an incident.

Measure export and model latency as well as detection accuracy. Gateway processing is asynchronous, so usable warning time must be demonstrated rather than assumed.

Next milestone: a manually initiated assessment appears in RoadWatch with its evidence and observation window. Add persistence tracking and XProtect events after checking these results.
