"""Optional snapshot person-in-region check; never a collision predictor."""
import math
import os
from pathlib import Path


def inside(point, polygon):
    x, y = point
    result = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y):
            edge = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < edge:
                result = not result
    return result


def validate_regions(regions):
    if not isinstance(regions, dict):
        raise ValueError('Regions must be an object')
    for name in ['open_lane', 'work_area']:
        polygon = regions.get(name, [])
        if name == 'work_area' and polygon == []:
            continue
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 40:
            raise ValueError('Mark 3-40 points for each region')
        for p in polygon:
            if not isinstance(p, list) or len(p) != 2 or any(type(v) not in {int,float} or not math.isfinite(v) or not 0 <= v <= 1 for v in p):
                raise ValueError('Use normalized image coordinates')
        area = abs(sum(a[0]*b[1] - b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1]))) / 2
        if area < .0001:
            raise ValueError('Region has no usable area')
        def cross(a,b,c):
            return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        for i in range(len(polygon)):
            for j in range(i+2, len(polygon)):
                if i == 0 and j == len(polygon)-1:
                    continue
                a,b=polygon[i],polygon[(i+1)%len(polygon)]
                c,d=polygon[j],polygon[(j+1)%len(polygon)]
                if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                    raise ValueError('Region edges cross; draw boundary points in order')
    return regions


def detect(image, regions):
    validate_regions(regions)
    weights = os.environ.get('ROADWATCH_YOLO_WEIGHTS')
    if not weights or not Path(weights).is_file():
        return {'available': False, 'message': 'Optional detector not configured. Set ROADWATCH_YOLO_WEIGHTS to a local pretrained weights file. Regions are not used by the VLM.'}
    try:
        from ultralytics import YOLO
    except ImportError:
        return {'available': False, 'message': 'Optional ultralytics package is not installed. See setup guide.'}
    model = YOLO(weights)
    result = model.predict(source=str(image), classes=[0], conf=.35, verbose=False)[0]
    detections = []
    for box in result.boxes:
        x1,y1,x2,y2 = box.xyxyn[0].tolist()
        foot = [(x1+x2)/2,y2]
        in_lane, in_work = inside(foot, regions['open_lane']), inside(foot, regions['work_area'])
        detections.append({'box':[x1,y1,x2,y2], 'foot':foot,'in_open_lane':in_lane,
                           'in_work_area':in_work,'region_conflict':in_lane and in_work})
    return {'available': True, 'detections': detections, 'person_exposure_candidates':sum(d['in_open_lane'] and not d['in_work_area'] for d in detections),
            'message': 'Single current snapshot, not the assessed clip. Missed detections are possible; no hazard or clearance is confirmed.'}
