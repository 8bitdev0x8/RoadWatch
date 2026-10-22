# Manual prompt evaluation

These results were supplied by the participant in chat. Exact clip timestamps, request IDs, and processing times were not supplied. They are exploratory observations, not a measured accuracy benchmark.

## Initial prompt

- vehicle_breakdown_traffic_queue: model returned obstructed, vehicle, persists_within_clip true, stopping_behind, adequate visibility. Description reported a stopped pickup, open driver door, person beside it, and traffic stopping behind. The model's exhaust description was not independently verified.
- traffic_flows_in_the_open_lanes: model returned obstructed, object, persists_within_clip true, diverting, adequate visibility. It described construction equipment, dirt, barriers, and merging traffic. The participant confirmed traffic flowed through the open lanes without another obstruction. This is a false positive against RoadWatch's target condition.
- An intervening weather-only response did not match the requested schema; prompt selection was suspected but not verified. Exclude it from this prompt's detection evaluation.

## Revised prompt (not yet tested)

prompts/road-obstruction.txt now separates road_context from assessment and distinguishes managed_merge from unexpected_avoidance. This is a hypothesis to test, not a demonstrated fix.

Retest the same roadworks interval, if still retained, then the breakdown clip. Budget: two completed summaries. Record UTC windows, exact answers, and latency. Do not suppress all roadworks scenes in application logic: an unexpected obstruction can occur within an open lane beside a managed closure.
