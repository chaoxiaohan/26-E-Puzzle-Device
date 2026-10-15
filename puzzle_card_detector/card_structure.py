"""Cheap, OCR-free printed-card evidence. Inputs and poses use RGB and pixels.

Scores are soft ranking evidence, never a proof of a correct assembly. Cache is
scoped to one immutable frame/piece list. No piece is reflected or rescaled.
"""

import math

import cv2
import numpy as np


def _piece_features(rgb, piece):
    polygon = np.asarray(piece["points"], dtype=np.float64)
    lo = np.maximum(0, np.floor(polygon.min(axis=0)).astype(int) - 2)
    hi = np.minimum(rgb.shape[1::-1], np.ceil(polygon.max(axis=0)).astype(int) + 3)
    crop = rgb[lo[1]:hi[1], lo[0]:hi[0]].astype(np.float32)
    original_red=crop[:,:,0].copy()
    original_green=crop[:,:,1].copy()
    original_blue=crop[:,:,2].copy()
    original_paper=float(np.percentile(crop.max(axis=2),85))
    original_hsv=cv2.cvtColor(crop.astype(np.uint8),cv2.COLOR_RGB2HSV)
    mask = np.zeros(crop.shape[:2], np.uint8)
    boundary=np.asarray(piece.get("source_contour",polygon),dtype=float)
    cv2.fillPoly(mask, [np.rint(boundary - lo).astype(np.int32)], 255)
    inside = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
    maximum = crop.max(axis=2)
    minimum = crop.min(axis=2)
    white=inside&(maximum-minimum<maximum*.25)
    if white.any():
        white&=maximum>=np.percentile(maximum[white],50)
    reference=np.percentile(crop[white],80,axis=0) if np.count_nonzero(white)>12 else np.percentile(crop[inside],85,axis=0) if inside.any() else np.full(3,240.0)
    crop=np.clip(crop/np.maximum(reference,40.0),0,1.3)
    maximum = crop.max(axis=2)
    minimum = crop.min(axis=2)
    paper = 1.0
    black = (maximum < paper * 0.68) & ((maximum - minimum) < paper * 0.36)
    red = ((crop[:, :, 0] > crop[:, :, 1] * 1.12)
           & (crop[:, :, 0] > crop[:, :, 2] *.98)
           & (crop[:, :, 0]-(crop[:, :, 1]+crop[:, :, 2])*.5>.07)
           & (original_red-original_green>max(4,original_paper*.03))
           & (original_red-original_blue>-original_paper*.08))
    color = (maximum - minimum > paper * 0.24) & (maximum < paper * 1.03)
    green = (crop[:, :, 1] > crop[:, :, 0] * 1.18) & (crop[:, :, 1] > crop[:, :, 2] * 1.12)
    boundary_green=((original_hsv[:,:,0]>=35)&(original_hsv[:,:,0]<=105)&(original_hsv[:,:,1]>=55)&(maximum>.48)
                    &(cv2.erode(mask,np.ones((9,9),np.uint8))==0))
    green|=boundary_green
    frame = (maximum < paper * 0.86) & ~green
    planes = np.stack(((black | red | color) & ~green & inside,
                       red & inside, color & ~green & inside,
                       frame & inside), axis=2).astype(np.uint8) * 255
    border = (mask > 0) & (cv2.erode(mask, np.ones((13, 13), np.uint8)) == 0)
    contact_border=(mask>0)&(cv2.distanceTransform(mask,cv2.DIST_L2,5)<=3.2)
    tracked = []
    for component_id, component in enumerate(_components(planes[:, :, 0] > 0)):
        x, y, bw, bh = component["box"]
        cut = component["mask"] & border[y:y + bh, x:x + bw]
        yy, xx = np.nonzero(cut)
        cut_points = np.column_stack((xx + x, yy + y)).astype(np.float64)
        if len(cut_points) > 96:
            cut_points = cut_points[np.linspace(0, len(cut_points) - 1, 96).astype(int)]
        contact=component['mask']&contact_border[y:y+bh,x:x+bw]
        yy,xx=np.nonzero(contact)
        join_points=np.column_stack((xx+x,yy+y)).astype(float)
        if len(join_points)>48:
            join_points=join_points[np.linspace(0,len(join_points)-1,48).astype(int)]
        tracked.append((component_id, component["center"], component["area"], cut_points,join_points))
    return polygon, lo, planes, mask, tracked


def _rigid_pose(source, target):
    if source.shape != target.shape or len(source) < 3:
        return None
    a, b = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - a).T @ (target - b))
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        return None
    error = float(np.sqrt(np.mean(np.sum(((source - a) @ rotation.T - (target - b)) ** 2, axis=1))))
    return rotation, b - rotation @ a, error


def _assemble(rgb, pieces, layout, cache):
    targets = {int(key): np.asarray(value, np.float64) for key, value in layout.items()}
    if not targets or any(key < 0 or key >= len(pieces) for key in targets):
        return None
    points = np.vstack(list(targets.values())).astype(np.float32)
    box = cv2.boxPoints(cv2.minAreaRect(points)).astype(np.float64)
    edges = np.roll(box, -1, axis=0) - box
    axis_y = edges[int(np.argmax(np.linalg.norm(edges, axis=1)))]
    axis_y /= np.linalg.norm(axis_y)
    axis_x = np.array([axis_y[1], -axis_y[0]])
    axes = np.stack((axis_x, axis_y))
    aligned = points @ axes.T
    lo, hi = aligned.min(axis=0), aligned.max(axis=0)
    size = hi - lo
    if min(size) < 10:
        return None
    scale = min(1.0, 300.0 / max(size))
    shape = tuple(np.ceil(size * scale).astype(int) + 1)
    canvas = np.zeros((shape[1], shape[0], 4), np.uint8)
    valid = np.zeros(canvas.shape[:2], np.uint8)
    owners = np.zeros(canvas.shape[:2], np.int32)
    errors = []
    tracks = []
    contacts=[]
    features = cache.setdefault("card_structure_pieces", {})
    for key, target in targets.items():
        if key not in features:
            features[key] = _piece_features(rgb, pieces[key])
        source, origin, planes, mask, source_tracks = features[key]
        pose = _rigid_pose(source, target)
        if pose is None:
            return None
        rotation, shift, error = pose
        errors.append(error)
        matrix = np.column_stack((axes @ rotation * scale,
                                  (axes @ (rotation @ origin + shift) - lo) * scale))
        warped = cv2.warpAffine(planes, matrix, shape, flags=cv2.INTER_NEAREST)
        covered = cv2.warpAffine(mask, matrix, shape, flags=cv2.INTER_NEAREST)
        canvas = np.maximum(canvas, warped)
        valid = np.maximum(valid, covered)
        owners[covered > 0] = key + 1
        for component_id, center, area, cut_points,join_points in source_tracks:
            moved = matrix[:, :2] @ center + matrix[:, 2]
            exterior = 0.0
            if len(cut_points):
                moved_cut = cut_points @ matrix[:, :2].T + matrix[:, 2]
                distance = np.minimum(moved_cut, np.array(shape) - 1 - moved_cut).min(axis=1)
                exterior = float(np.mean(distance < max(4, min(shape) * 0.055)))
            tracks.append({"piece_id": key, "component_id": component_id,
                           "center": [float(moved[0] / shape[0]), float(moved[1] / shape[1])],
                           "source_area": area, "source_cut_samples": len(cut_points),
                           "cut_on_outer_fraction": exterior})
            if area>=20 and len(join_points)>=8:
                contacts.append((key,tracks[-1],join_points@matrix[:,:2].T+matrix[:,2]))
    join_radius=max(5.0,min(shape)*.06)
    distances={}
    for key,track,points in contacts:
        outer=np.minimum(points,np.array(shape)-1-points).min(axis=1)
        points=points[outer>join_radius]
        if not len(points):
            continue
        if key not in distances:
            other_paper=(owners>0)&(owners!=key+1)
            other_ink=(canvas[:,:,0]>0)&other_paper
            distances[key]=(cv2.distanceTransform((~other_ink).astype(np.uint8),cv2.DIST_L2,5),
                            cv2.distanceTransform((~other_paper).astype(np.uint8),cv2.DIST_L2,5))
        xy=np.rint(points).astype(int)
        xy[:,0]=np.clip(xy[:,0],0,shape[0]-1)
        xy[:,1]=np.clip(xy[:,1],0,shape[1]-1)
        ink_distance,paper_distance=distances[key]
        measured=ink_distance[xy[:,1],xy[:,0]]
        gap=paper_distance[xy[:,1],xy[:,0]]
        excess=np.maximum(0,measured-gap)
        quality=np.clip(1-(excess-3.0)/join_radius,0,1)
        quality*=gap<=max(6.0,min(shape)*.10)
        track['join_samples']=len(points)
        track['join_distance_median']=float(np.median(measured))
        track['join_gap_median']=float(np.median(gap))
        track['join_fraction']=float(np.mean(quality))
    return canvas > 0, valid > 0, float(max(errors)), scale, tracks, owners


def _components(ink, close=True):
    joined = ink.astype(np.uint8)
    if close:
        joined = cv2.morphologyEx(joined, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(joined, 8)
    h, w = ink.shape
    result = []
    for key in range(1, count):
        x, y, bw, bh, area = stats[key]
        if area < max(5, w * h * 0.00025):
            continue
        result.append({"box": (int(x), int(y), int(bw), int(bh)),
                       "area": int(area), "center": centers[key],
                       "mask": labels[y:y + bh, x:x + bw] == key})
    return result


def _shape_features(mask, features):
    key=(mask.shape,mask.tobytes())
    if key not in features:
        value=mask.astype(np.uint8)
        padded=cv2.copyMakeBorder(value,1,1,1,1,cv2.BORDER_CONSTANT,value=0)
        dilated=cv2.dilate(padded,np.ones((3,3),np.uint8))
        features[key]=(len(features),value,dilated,cv2.countNonZero(value))
    return features[key]


def _shape_similarity(first, second, cache=None):
    # Preserve the original center rounding and one-pixel shape tolerance.
    # Intern masks once; pair keys contain IDs rather than duplicate image bytes.
    cache={} if cache is None else cache
    features=cache.setdefault('features',{})
    pairs=cache.setdefault('pairs',{})
    a,b=_shape_features(first,features),_shape_features(second,features)
    key=tuple(sorted((a[0],b[0])))
    if key in pairs:
        return pairs[key]
    h=max(first.shape[0],second.shape[0])+4
    w=max(first.shape[1],second.shape[1])+4

    def covered(source, target):
        mask,dilated=source[1],target[2]
        sy,sx=(h-mask.shape[0])//2,(w-mask.shape[1])//2
        ty,tx=(h-target[1].shape[0])//2-1,(w-target[1].shape[1])//2-1
        top,left=max(sy,ty),max(sx,tx)
        bottom,right=min(sy+mask.shape[0],ty+dilated.shape[0]),min(sx+mask.shape[1],tx+dilated.shape[1])
        if bottom<=top or right<=left:
            return 0
        return cv2.countNonZero(cv2.bitwise_and(mask[top-sy:bottom-sy,left-sx:right-sx],
                                              dilated[top-ty:bottom-ty,left-tx:right-tx]))

    score=(covered(a,b)+covered(b,a))/max(1,a[3]+b[3])
    pairs[key]=score
    return score


def _unique_components(components):
    unique={}
    for component in components:
        key=(component['box'],np.packbits(component['mask']).tobytes())
        unique.setdefault(key,component)
    return list(unique.values())


def _outer_evidence(ink, valid):
    h, w = ink.shape
    band = max(4, int(min(h, w) * 0.055))
    # The first detector-boundary pixel is deliberately ignored; use print inside paper.
    sides = [(ink[1:band + 1], valid[1:band + 1], 0),
             (ink[-band - 1:-1], valid[-band - 1:-1], 0),
             (ink[:, 1:band + 1], valid[:, 1:band + 1], 1),
             (ink[:, -band - 1:-1], valid[:, -band - 1:-1], 1)]
    cuts = []
    for printed, covered, axis in sides:
        observable = covered.sum(axis=axis) >= max(1, band // 2)
        touched = printed.sum(axis=axis) >= max(1, band // 3)
        cuts.append(float((touched & observable).sum() / max(1, observable.sum())))
    cut = float(np.mean(cuts))
    score = math.exp(-cut * 14.0)
    confidence = min(1.0, float(ink.sum()) / max(1, h * w * 0.035))
    return score, confidence, cuts


def _cut_integrity_evidence(tracks):
    contacts=[track for track in tracks if track.get('join_samples',0)>=8]
    samples=sum(track['join_samples'] for track in contacts)
    if not samples:
        return .5,0.0,{'samples':0}
    matched=sum(track['join_samples']*track['join_fraction'] for track in contacts)/samples
    return matched,min(1.0,samples/40.0),{'samples':samples,'matched_fraction':matched}


def _index_evidence(ink, components, red=None, owners=None, shape_cache=None):
    h, w = ink.shape
    # Red lettering must not join the dark portrait's border into one component.
    # No closing here: the tiny blank space between rank and suit carries meaning.
    red_fraction=float(red.sum())/max(1,int(ink.sum())) if red is not None else 0.0
    # 单色红牌的细笔画可能因蓝色光偏而失去红阈值；保留它们的暗墨迹。
    print_mask = red if 0.08<red_fraction<0.70 else ink
    detected=_components(print_mask,close=False)
    eroded=cv2.erode(print_mask.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3)))
    for component in _components(eroded,close=False):
        x,y,bw,bh=component['box']
        # A 3x3 dilation can only reach one pixel beyond this component.
        left,top=max(0,x-1),max(0,y-1)
        right,bottom=min(w,x+bw+1),min(h,y+bh+1)
        padded=np.zeros((bottom-top,right-left),np.uint8)
        padded[y-top:y-top+bh,x-left:x-left+bw]=component['mask']
        restored=(cv2.dilate(padded,np.ones((3,3),np.uint8))>0)&print_mask[top:bottom,left:right]
        for restored_component in _components(restored,close=False):
            # Keep the original full-card area threshold after cropping.
            if restored_component['area']<max(5,w*h*.00025):
                continue
            cx,cy,cw,ch=restored_component['box']
            restored_component['box']=(cx+left,cy+top,cw,ch)
            restored_component['center']+=np.array([left,top])
            detected.append(restored_component)
    detected=_unique_components(detected)
    split=[]
    for component in detected:
        x,y,bw,bh=component['box']
        if bh<h*.11 or bw>w*.25:
            continue
        profile=component['mask'].sum(axis=1)
        low,high=max(3,int(bh*.48)),min(bh-3,int(bh*.82))
        if high<=low:
            continue
        locations=np.arange(low,high)
        valley=profile[low:high]/max(1,profile.max())+np.abs(locations/bh-.65)*.5
        row=low+int(np.argmin(valley))
        if profile[row]>max(1,profile.max()*.25):
            continue
        for start,stop in ((0,row),(row,bh)):
            patch=component['mask'][start:stop]
            yy,xx=np.nonzero(patch)
            if len(xx)<8:
                continue
            left,right=int(xx.min()),int(xx.max()+1)
            top,bottom=int(yy.min()),int(yy.max()+1)
            split.append({'box':(x+left,y+start+top,right-left,bottom-top),'area':len(xx),
                          'center':np.array([x+xx.mean(),y+start+yy.mean()]),
                          'mask':patch[top:bottom,left:right]})
    fragments=[]
    for first_id,a in enumerate(detected):
        for b in detected[first_id+1:]:
            ax,ay,aw,ah=a['box']
            bx,by,bw,bh=b['box']
            gap=max(ay,by)-min(ay+ah,by+bh)
            if not (-1<=gap<h*.025 and abs(ax+aw*.5-bx-bw*.5)<max(aw,bw)*.65):
                continue
            x,y=min(ax,bx),min(ay,by)
            right,bottom=max(ax+aw,bx+bw),max(ay+ah,by+bh)
            if right-x>w*.14 or not h*.035<bottom-y<h*.17:
                continue
            patch=np.zeros((bottom-y,right-x),bool)
            for component in (a,b):
                px,py,pw,ph=component['box']
                patch[py-y:py-y+ph,px-x:px-x+pw]|=component['mask']
            yy,xx=np.nonzero(patch)
            fragments.append({'box':(x,y,right-x,bottom-y),'area':len(xx),
                              'center':np.array([x+xx.mean(),y+yy.mean()]),'mask':patch})
    small = [c for c in _unique_components(detected+split+fragments)
             if c["box"][2] < w * 0.23 and c["box"][3] < h * 0.20
             and c["area"] < h * w * 0.023]
    ranks = list(small)
    # A 10 is two neighboring characters on one baseline, not one tall glyph.
    for first_id, a in enumerate(small):
        for b in small[first_id + 1:]:
            ax, ay, aw, ah = a["box"]
            bx, by, bw, bh = b["box"]
            gap = max(ax, bx) - min(ax + aw, bx + bw)
            if not (-1 <= gap < w * 0.035 and abs(ay - by) < h * 0.018
                    and min(ah, bh) > max(ah, bh) * 0.62
                    and min(ah, bh) > h * 0.025):
                continue
            x, y = min(ax, bx), min(ay, by)
            right, bottom = max(ax + aw, bx + bw), max(ay + ah, by + bh)
            if right - x > w * 0.23:
                continue
            ranks.append({"box": (x, y, right - x, bottom - y),
                          "area": a["area"] + b["area"],
                          "center": np.array([(x + right) * 0.5, (y + bottom) * 0.5]),
                          "members": (a, b)})
    groups = []
    small_centers=np.asarray([c['center'] for c in small],dtype=float).reshape(-1,2)
    small_boxes=np.asarray([c['box'] for c in small],dtype=float).reshape(-1,4)
    small_areas=np.asarray([c['area'] for c in small],dtype=float)
    suit_shape=(small_boxes[:,3]<=h*.095)&(np.minimum(small_boxes[:,2],small_boxes[:,3])
                >=np.maximum(small_boxes[:,2],small_boxes[:,3])*.50)
    for a in ranks:
        hierarchy=None
        contours=[]
        if 'mask' in a:
            contours,hierarchy=cv2.findContours(a['mask'].astype(np.uint8),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        wide_rank='members' in a
        if hierarchy is not None:
            holes=[cv2.contourArea(contour) for contour,item in zip(contours,hierarchy[0]) if item[3]>=0]
            wide_rank=wide_rank or sum(holes)>a['area']*.08
        solidity=0.0
        if contours:
            contour=max(contours,key=cv2.contourArea)
            solidity=cv2.contourArea(contour)/max(1,cv2.contourArea(cv2.convexHull(contour)))
        if (a['box'][3]<a['box'][2]*(.65 if wide_rank else .80)
                or (not wide_rank and solidity>.86)):
            continue
        ax,ay=a['center']
        vertical=np.abs(small_centers[:,1]-ay)
        eligible=(suit_shape
                  &(np.abs(small_centers[:,0]-ax)<max(w*.035,a['box'][2]*.45))
                  &(vertical>h*.022)&(vertical<h*.16)
                  &(a['area']<=small_areas*(7.5 if wide_rank else 4.5))
                  &(a['box'][3]>=small_boxes[:,3]*1.10)
                  &(small_areas<=a['area']*1.8))
        for small_id in np.flatnonzero(eligible):
            b=small[small_id]
            if a is b or any(b is member for member in a.get("members", ())):
                continue
            ax, ay = a["center"]
            bx, by = b["center"]
            if 'mask' in a:
                ax0,ay0,aw,ah=a['box']
                bx0,by0,bw,bh=b['box']
                left,top=max(ax0,bx0),max(ay0,by0)
                right,bottom=min(ax0+aw,bx0+bw),min(ay0+ah,by0+bh)
                if right>left and bottom>top and np.any(a['mask'][top-ay0:bottom-ay0,left-ax0:right-ax0]
                                                       &b['mask'][top-by0:bottom-by0,left-bx0:right-bx0]):
                    continue
            x = min(a["box"][0], b["box"][0])
            y = min(a["box"][1], b["box"][1])
            right = max(a["box"][0] + a["box"][2], b["box"][0] + b["box"][2])
            bottom = max(a["box"][1] + a["box"][3], b["box"][1] + b["box"][3])
            center = np.array([(x + right) / (2 * w), (y + bottom) / (2 * h)])
            top = ay < by
            anchor = np.array([0.10, 0.12]) if top else np.array([0.90, 0.88])
            location = math.exp(-float(np.sum(((center - anchor) / [0.13, 0.17]) ** 2)))
            # Only the two components enter the shape, never neighboring art
            # inside their rectangle. This also keeps the 10 grouping isolated.
            patch = np.zeros((bottom - y, right - x), np.uint8)
            for component in list(a.get("members", (a,))) + [b]:
                px, py, pw, ph = component["box"]
                patch[py - y:py - y + ph, px - x:px - x + pw] |= component["mask"].astype(np.uint8)
            adjacency = 1.0
            if owners is not None:
                source_ids = []
                for component in list(a.get("members", (a,))) + [b]:
                    px, py, pw, ph = component["box"]
                    ids = owners[py:py + ph, px:px + pw][component["mask"]]
                    ids = ids[ids > 0]
                    if len(ids):
                        source_ids.append(int(np.bincount(ids).argmax()))
                if len(set(source_ids)) > 1:
                    adjacency = 0.65
            groups.append((location, top, patch, center, adjacency, int(patch.sum())))
    best = 0.0
    similarity = 0.0
    matched_strength = 0.0
    matched_location = 0.0
    same_direction_strength=0.0
    centers=np.array([group[3] for group in groups])
    directions=np.array([group[1] for group in groups])
    for first_id,a in enumerate(groups):
        # Select the same ordered pairs in bulk, without thousands of tiny norms.
        distance=np.linalg.norm(centers-a[3],axis=1)
        eligible=(distance>=.25)&((directions==a[1])|a[1])
        # A same-direction pair contributes only a symmetric maximum.
        eligible&=(directions!=a[1])|(np.arange(len(groups))>first_id)
        for second_id in np.flatnonzero(eligible):
            b=groups[second_id]
            if a[1]==b[1]:
                ratio=min(a[5],b[5])/max(1,a[5],b[5])
                adjacency=math.sqrt(a[4]*b[4])
                if ratio*adjacency<=same_direction_strength:
                    continue
                matched=_shape_similarity(a[2],b[2],shape_cache)
                same_direction_strength=max(same_direction_strength,matched*ratio*adjacency)
                continue
            if not a[1] or b[1]:
                continue
            # Comparable shape area and opposite reading directions are required
            # before an interior pair can supply negative placement evidence.
            area_ratio = min(a[5], b[5]) / max(1, a[5], b[5])
            location=math.sqrt(a[0]*b[0])
            adjacency = math.sqrt(a[4] * b[4])
            # Shape similarity is at most one. Skip only pairs that cannot
            # pass the existing threshold or improve either tracked maximum.
            if area_ratio < (0.40 if location>.35 else 0.65):
                continue
            if (location*math.sqrt(area_ratio)*adjacency<=best
                    and area_ratio*adjacency<=matched_strength):
                continue
            matched = _shape_similarity(a[2], b[2][::-1, ::-1],shape_cache)
            if matched<.55 or matched * area_ratio < (0.40 if location>.35 else 0.65):
                continue
            strength = matched * area_ratio * adjacency
            value = location * matched * math.sqrt(area_ratio) * adjacency
            if value > best:
                best, similarity = value, matched
            if strength > matched_strength:
                matched_strength = strength
                matched_location = math.sqrt(a[0] * b[0])
    # One unmatched portrait fragment is not evidence of a misplaced index.
    # A stronger correctly placed matched pair overrides weaker interior pairs.
    misplaced = max(matched_strength * (1.0 - matched_location),same_direction_strength) * (1.0 - best)
    confidence = max(best, matched_strength,same_direction_strength)
    score = float(np.clip(0.5 + best * 0.5 - misplaced * 0.35, 0.0, 1.0))
    return score, confidence, {"pair_count": len(groups), "diagonal_match": best,
                               "shape_match": similarity, "misplaced_index": misplaced,
                               "matched_pair_strength": matched_strength,
                               "same_direction_strength":same_direction_strength,
                               "color_plane": "red" if print_mask is red else "ink"}


def _letter_index_evidence(ink,shape_cache=None):
    """配对两端完整的竖排字形串，不需要外部 OCR 或牌面模板。"""
    h,w=ink.shape
    components=_components(ink,close=False)
    split=[]
    for component in components:
        x,y,bw,bh=component['box']
        if bw>w*.14 or not h*.095<bh<h*.22:
            continue
        profile=component['mask'].sum(axis=1)
        low,high=int(bh*.30),int(bh*.70)
        if high<=low:
            continue
        rows=np.arange(low,high)
        valley=profile[low:high]/max(1,profile.max())+np.abs(rows/bh-.5)*.5
        row=low+int(np.argmin(valley))
        if profile[row]>max(1,profile.max()*.25):
            continue
        for start,stop in ((0,row),(row,bh)):
            patch=component['mask'][start:stop]
            yy,xx=np.nonzero(patch)
            if len(xx)<6:
                continue
            left,right=int(xx.min()),int(xx.max()+1)
            top,bottom=int(yy.min()),int(yy.max()+1)
            split.append({'box':(x+left,y+start+top,right-left,bottom-top),'area':len(xx),
                          'center':np.array([x+xx.mean(),y+start+yy.mean()]),
                          'mask':patch[top:bottom,left:right]})
    letters=[component for component in components+split
             if w*.018<=component['box'][2]<=w*.14
             and h*.018<=component['box'][3]<=h*.095
             and component['area']>=max(6,h*w*.0003)
             and .15<=component['area']/(component['box'][2]*component['box'][3])<=.90]
    merged=[]
    used=set()
    for first,a in enumerate(letters):
        if first in used:
            continue
        ax,ay,aw,ah=a['box']
        for second,b in enumerate(letters):
            if second<=first or second in used:
                continue
            bx,by,bw,bh=b['box']
            gap=max(ax,bx)-min(ax+aw,bx+bw)
            if not (0<=gap<=w*.025 and abs(ay+ah*.5-by-bh*.5)<=h*.015
                    and min(ah,bh)>=max(ah,bh)*.6):
                continue
            left,top=min(ax,bx),min(ay,by)
            right,bottom=max(ax+aw,bx+bw),max(ay+ah,by+bh)
            if right-left>w*.14:
                continue
            patch=np.zeros((bottom-top,right-left),bool)
            patch[ay-top:ay-top+ah,ax-left:ax-left+aw]|=a['mask']
            patch[by-top:by-top+bh,bx-left:bx-left+bw]|=b['mask']
            yy,xx=np.nonzero(patch)
            a={'box':(left,top,right-left,bottom-top),'area':len(xx),
               'center':np.array([left+xx.mean(),top+yy.mean()]),'mask':patch}
            used.add(second)
            break
        merged.append(a)
    letters=merged
    neutral=(.5,0.0,{'groups':0})
    if len(letters)<10:
        return neutral
    cell_height=max(item['box'][3] for item in letters)+4
    cell_width=max(item['box'][2] for item in letters)+4
    groups={}
    for anchor in letters:
        column=sorted([item for item in letters if abs(item['center'][0]-anchor['center'][0])<w*.04],
                      key=lambda item:item['center'][1])
        for start in range(len(column)):
            for count in (5,6,7):
                word=column[start:start+count]
                if len(word)!=count:
                    continue
                if any(not -1<=b['box'][1]-a['box'][1]-a['box'][3]<=h*.08
                       for a,b in zip(word,word[1:])):
                    continue
                left=min(item['box'][0] for item in word)
                right=max(item['box'][0]+item['box'][2] for item in word)
                top=min(item['box'][1] for item in word)
                bottom=max(item['box'][1]+item['box'][3] for item in word)
                if right-left>w*.18 or not h*.15<bottom-top<h*.40:
                    continue
                similarity=[_shape_similarity(a['mask'],b['mask'],shape_cache)
                            for index,a in enumerate(word) for b in word[index+1:]]
                if np.mean(similarity)>.93:
                    continue
                key=tuple(item['box'] for item in word)
                if key in groups:
                    continue
                # 只在比较字形串时消除字间白缝；不改变目标纸片位置。
                patch=np.zeros((cell_height*count,cell_width),np.uint8)
                for row,item in enumerate(word):
                    _,_,bw,bh=item['box']
                    x=(cell_width-bw)//2
                    y=row*cell_height+(cell_height-bh)//2
                    patch[y:y+bh,x:x+bw]=item['mask']
                groups[key]={'mask':patch,'center':np.array([(left+right)/(2*w),(top+bottom)/(2*h)]),
                             'count':count,'area':int(patch.sum())}
    best=.0
    confidence=.0
    detail={'groups':len(groups)}
    values=list(groups.values())
    for index,a in enumerate(values):
        for b in values[index+1:]:
            if np.linalg.norm(a['center']-b['center'])<.45:
                continue
            shape=_shape_similarity(a['mask'],b['mask'][::-1,::-1],shape_cache)
            same_direction=_shape_similarity(a['mask'],b['mask'],shape_cache)
            area=min(a['area'],b['area'])/max(1,a['area'],b['area'])
            if shape<.72 or shape<same_direction+.04 or area<.50:
                continue
            count=min(a['count'],b['count'])/max(a['count'],b['count'])
            strength=shape*math.sqrt(area)*count
            location=max(math.exp(-float(np.sum(((a['center']-first)/[.11,.18])**2)
                                      +np.sum(((b['center']-second)/[.11,.18])**2))*.5)
                         for first,second in ((np.array([.1,.20]),np.array([.9,.80])),
                                              (np.array([.9,.80]),np.array([.1,.20]))))
            score=.5+.5*strength*location-.35*strength*(1-location)
            if score>best:
                best=score
                confidence=strength
                detail={'groups':len(groups),'shape_match':shape,'location':location,
                        'direction_margin':shape-same_direction,
                        'characters':[a['count'],b['count']]}
    return (best,confidence,detail) if confidence else neutral


def _body_evidence(planes, components, shape_cache=None):
    ink, color = planes[:, :, 0], planes[:, :, 2] & ~planes[:, :, 1]
    h, w = ink.shape
    center = ink[int(h * 0.12):int(h * 0.88), int(w * 0.19):int(w * 0.81)]
    density = float(center.mean()) if center.size else 0.0
    portrait = min(1.0, float(color.sum()) / max(1, h * w * 0.035)) * min(1.0, density / 0.24)
    if portrait > 0.35:
        # Coarse double-ended portrait/color mass, not exact pixel symmetry.
        soft = cv2.GaussianBlur(planes.astype(np.float32), (0, 0), max(2.0, w * 0.025))
        region = soft[int(h * 0.12):int(h * 0.88), int(w * 0.19):int(w * 0.81)]
        opposite = region[::-1, ::-1]
        agreement = 1.0 - float(np.abs(region - opposite).sum() / max(1.0, (region + opposite).sum()))
        return agreement, portrait, {"kind": "portrait", "central_density": density}
    pips = [c for c in components if c["area"] > h * w * 0.004
            and c["box"][2] < w * 0.30 and c["box"][3] < h * 0.26
            and 0.16 < c["center"][0] / w < 0.84
            and 0.12 < c["center"][1] / h < 0.88]
    if len(pips) < 2:
        return 0.5, 0.0, {"kind": "unknown", "pip_count": len(pips)}
    repeat = []
    grid = []
    for a in pips:
        repeat.append(max(max(_shape_similarity(a["mask"], b["mask"],shape_cache),
                              _shape_similarity(a["mask"], b["mask"][::-1, ::-1],shape_cache))
                          for b in pips if b is not a))
        x = a["center"][0] / w
        grid.append(math.exp(-(min(abs(x - column) for column in (0.28, 0.5, 0.72)) / 0.075) ** 2))
    score = float(np.mean(repeat) * 0.75 + np.mean(grid) * 0.25)
    confidence = min(1.0, (len(pips) - 1) / 4.0) * min(1.0, float(np.mean(repeat)) / 0.7)
    return score, confidence, {"kind": "number", "pip_count": len(pips),
                               "repeat_shape": float(np.mean(repeat)), "column_fit": float(np.mean(grid))}


def score_layout_structure(frame_rgb, pieces, layout, cache=None, minimum_score=None):
    """Return score/confidence and explainable terms for a candidate rectangle.

    layout maps piece IDs to polygons in source vertex order. Reuse a cache only
    within one frame. A shared global raster reduction is allowed for speed.
    """
    neutral = {"score": 0.5, "confidence": 0.0, "valid": False}
    cache={} if cache is None else cache
    assembled = _assemble(frame_rgb, pieces, layout, cache)
    if assembled is None:
        return dict(neutral, reason="invalid_or_reflected_pose")
    planes, valid, error, scale, tracks, owners = assembled
    ink = planes[:, :, 0]
    area = max(1, int(valid.sum()))
    evidence = min(1.0, float(ink.sum()) / (area * 0.025))
    if evidence < 0.08:
        return dict(neutral, valid=True, reason="insufficient_print", ink_fraction=float(ink.sum()) / area)
    outer, outer_conf, cuts = _outer_evidence(ink, valid)
    # Track actual source-component cut pixels. Broad corner texture cannot
    # explain why the same clipped suit is placed on an external card boundary.
    cut_tracks = [track for track in tracks if track["source_cut_samples"] >= 3]
    cut_weight = sum(track["source_cut_samples"] for track in cut_tracks)
    moved_cut = sum(track["cut_on_outer_fraction"] * track["source_cut_samples"]
                    for track in cut_tracks) / max(1, cut_weight)
    if cut_weight:
        outer = min(outer, math.exp(-moved_cut * 4.0))
    joined,join_conf,join_detail=_cut_integrity_evidence(tracks)
    pose_conf = math.exp(-error / max(2.0, min(ink.shape) / scale * 0.025))
    if minimum_score is not None:
        # Unknown index/body scores and confidences are at most one. The
        # resulting bound includes every existing positive/negative term.
        # Increasing either unknown weight cannot decrease this upper bound.
        known_weight = .45*outer_conf + .25*join_conf
        total_bound = known_weight + .35 + .20
        centered_bound = .45*outer_conf*(outer-.5) + .25*join_conf*(joined-.5) + .55*.5
        upper = .5 + centered_bound / max(1.0, total_bound) * evidence * pose_conf
        if upper < minimum_score - 1e-12:
            return dict(neutral, score=upper, valid=True, pruned=True)
    components = _components(ink)
    shape_cache=cache.setdefault('card_structure_shape_scores',{})
    index, index_conf, index_detail = _index_evidence(ink, components, planes[:, :, 1], owners,shape_cache)
    body, body_conf, body_detail = _body_evidence(planes, components,shape_cache)
    letter_score,letter_conf,letter_detail=(.5,0.0,{})
    if body_detail.get('kind')=='unknown':
        letter_score,letter_conf,letter_detail=_letter_index_evidence(ink,shape_cache)
        if letter_conf>=.60:
            index,index_conf,index_detail=letter_score,letter_conf,dict(letter_detail,kind='letter-string')
            body,body_conf,body_detail=letter_score,letter_conf,{'kind':'lettered-card'}
    weights = [0.45 * outer_conf, 0.35 * index_conf, 0.20 * body_conf,.25*join_conf]
    total = sum(weights)
    raw = sum(value * weight for value, weight in zip((outer, index, body,joined), weights)) / max(1e-6, total)
    # A pose with large polygon drift has unreliable print placement, even though
    # the render always uses rotation + translation without fitting scale/shear.
    confidence = min(1.0, total) * evidence * pose_conf
    return {"score": 0.5 + (raw - 0.5) * confidence, "confidence": confidence,
            "valid": True, "raw_score": raw, "outer": outer, "outer_confidence": outer_conf,
            "outer_cut_fractions": cuts, "index": index, "index_confidence": index_conf,
            "index_detail": index_detail, "body": body, "body_confidence": body_conf,
            "body_detail": body_detail, "ink_fraction": float(ink.sum()) / area,
            'cut_integrity':joined,'cut_integrity_confidence':join_conf,'cut_integrity_detail':join_detail,
            'letter_index':letter_score,'letter_index_confidence':letter_conf,'letter_index_detail':letter_detail,
            "rigid_pose_error": error, "coverage": float(valid.mean()),
            "source_component_tracks": tracks, "source_cut_on_outer_fraction": moved_cut}
