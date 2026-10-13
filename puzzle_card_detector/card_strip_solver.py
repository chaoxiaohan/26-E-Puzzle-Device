"""保留一片贯穿整牌的长边，枚举另外三片的边界接法。"""

import itertools
import math
import time

import cv2
import numpy as np

from card_face_solver import score_layout_texture
from card_joint_solver import layout_pose_key,relative_texture_matches
from card_structure import score_layout_structure
from layout_constraints import evaluate_layout
from solver_v2 import normalize_polygon


def _oriented_edge(source,edge,axis):
    vector=source[(edge+1)%len(source)]-source[edge]
    length=np.linalg.norm(vector)
    angle=math.atan2(axis[1],axis[0])-math.atan2(vector[1],vector[0])
    rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
    return (source-source[edge])@rotation.T,float(length)


def _right_corner_states(polygon,bottom):
    states=[]
    for edge in range(len(polygon)):
        for axis,endpoint in (((0,1),1 if bottom else 0),((-1,0),0)) if bottom else (((1,0),1),((0,1),0)):
            target,length=_oriented_edge(polygon,edge,axis)
            if endpoint:
                target-=np.asarray(axis)*length
            if target[:,0].max()>3 or (target[:,1].max()>3 if bottom else target[:,1].min()<-3):
                continue
            states.append(target)
    return states


def _dual_side_layouts(polygons,area):
    for left_id,polygon in enumerate(polygons):
        for left_edge in range(len(polygon)):
            left,left_length=_oriented_edge(polygon,left_edge,(0,-1))
            if left_length<math.sqrt(area)*.65:
                continue
            left-=left.min(axis=0)
            for right_id in range(len(polygons)):
                if right_id==left_id:
                    continue
                for right_edge in range(len(polygons[right_id])):
                    right,right_length=_oriented_edge(polygons[right_id],right_edge,(0,1))
                    if abs(left_length-right_length)>max(6,left_length*.10):
                        continue
                    height=max(float(left[:,1].max()),right_length)
                    base_width=area/max(1,height)
                    if not .45<=height/base_width<=2.2:
                        continue
                    for padding in (0.0,2.0,4.0):
                        width=base_width+padding
                        left_target=left+(0,(height-left[:,1].max())*.5)
                        right_target=right+(width,(height-right_length)*.5)
                        if left_target[:,0].max()>width*.80 or right_target[:,0].min()<width*.20:
                            continue
                        upper_left=left_target[left_target[:,1]<4,0]
                        upper_right=right_target[right_target[:,1]<4,0]
                        lower_left=left_target[left_target[:,1]>height-4,0]
                        lower_right=right_target[right_target[:,1]>height-4,0]
                        if not all(len(points) for points in (upper_left,upper_right,lower_left,lower_right)):
                            continue
                        top_start,top_end=float(upper_left.max()),float(upper_right.min())
                        bottom_start,bottom_end=float(lower_left.max()),float(lower_right.min())
                        remaining=[i for i in range(4) if i not in (left_id,right_id)]
                        for top_id,bottom_id in itertools.permutations(remaining):
                            for top_edge in range(len(polygons[top_id])):
                                top,top_length=_oriented_edge(polygons[top_id],top_edge,(1,0))
                                if abs(top_end-top_start-top_length)>max(7,width*.10):
                                    continue
                                for bottom_edge in range(len(polygons[bottom_id])):
                                    bottom,bottom_length=_oriented_edge(polygons[bottom_id],bottom_edge,(-1,0))
                                    if abs(bottom_end-bottom_start-bottom_length)>max(7,width*.10):
                                        continue
                                    for top_x,bottom_x in itertools.product(
                                            (top_start,top_end-top_length,(top_start+top_end-top_length)*.5),
                                            (bottom_end,bottom_start+bottom_length,(bottom_start+bottom_end+bottom_length)*.5)):
                                        yield {left_id:left_target,right_id:right_target,top_id:top+(top_x,0),bottom_id:bottom+(bottom_x,height)}


def generate_strip_card_candidates(frame_rgb,pieces,candidate_limit=24,cache=None):
    started=time.monotonic()
    empty={'candidates':[],'nodes':0,'search_complete':True}
    if len(pieces)!=4 or any(not 3<=len(p['points'])<=8 for p in pieces):
        return empty
    cache={} if cache is None else cache
    originals=[np.asarray(piece['points'],dtype=float) for piece in pieces]
    polygons=[normalize_polygon(polygon) for polygon in originals]
    area=sum(abs(cv2.contourArea(p.astype(np.float32))) for p in polygons)
    top_states=[_right_corner_states(p,False) for p in polygons]
    bottom_states=[_right_corner_states(p,True) for p in polygons]
    accepted={}
    nodes=0
    for layout in _dual_side_layouts(polygons,area):
        nodes+=1
        layout={i:p[::-1].copy() if cv2.contourArea(originals[i].astype(np.float32),oriented=True)<0 else p.copy()
                for i,p in layout.items()}
        key=layout_pose_key(layout)
        if key in accepted:
            continue
        report=evaluate_layout(layout,edge_tolerance_ratio=.065)
        if report['coverage']<.85 or report['overlap']>.008 or report['outer_piece_ratio']<.999:
            continue
        accepted[key]={'layout':layout,'report':report,'source':'card-opposite-boundaries',
                       'assignment':tuple(layout),'structure':score_layout_structure(frame_rgb,pieces,layout,cache)}
    for anchor,polygon in enumerate(polygons):
        for edge in range(len(polygon)):
            target,length=_oriented_edge(polygon,edge,(0,-1))
            if length<math.sqrt(area)*.65:
                continue
            target-=target.min(axis=0)
            height=float(target[:,1].max())
            width=area/max(1,height)
            if not .45<=height/width<=2.2 or target[:,0].max()>width*.60:
                continue
            for top_id,bottom_id,middle_id in itertools.permutations([i for i in range(4) if i!=anchor]):
                for upper,lower in itertools.product(top_states[top_id],bottom_states[bottom_id]):
                    for padding in (0.0,max(2,width*.015)):
                        right=width+padding
                        upper_target=upper+(right,0)
                        lower_target=lower+(right,height)
                        top=upper_target[np.abs(upper_target[:,0]-right)<4,1]
                        bottom=lower_target[np.abs(lower_target[:,0]-right)<4,1]
                        if not len(top) or not len(bottom):
                            continue
                        start,end=float(top.max()),float(bottom.min())
                        for middle_edge in range(len(polygons[middle_id])):
                            middle,middle_length=_oriented_edge(polygons[middle_id],middle_edge,(0,1))
                            if abs(end-start-middle_length)>max(6,height*.08):
                                continue
                            for y in (start,end-middle_length,(start+end-middle_length)*.5):
                                nodes+=1
                                layout={anchor:target,top_id:upper_target,bottom_id:lower_target,
                                        middle_id:middle+(right,y)}
                                if any(p[:,0].min()<-4 or p[:,0].max()>right+4 or p[:,1].min()<-4 or p[:,1].max()>height+4 for p in layout.values()):
                                    continue
                                if sum(cv2.intersectConvexConvex(a.astype(np.float32),b.astype(np.float32))[0]
                                       for a,b in itertools.combinations(layout.values(),2))>area*.015:
                                    continue
                                layout={i:p[::-1].copy() if cv2.contourArea(originals[i].astype(np.float32),oriented=True)<0 else p.copy()
                                        for i,p in layout.items()}
                                key=layout_pose_key(layout)
                                if key in accepted:
                                    continue
                                report=evaluate_layout(layout,edge_tolerance_ratio=.065)
                                if report['coverage']<.85 or report['overlap']>.008 or report['outer_piece_ratio']<.999:
                                    continue
                                accepted[key]={'layout':layout,'report':report,'source':'card-strip-boundary',
                                               'assignment':(anchor,top_id,bottom_id,middle_id),
                                               'structure':score_layout_structure(frame_rgb,pieces,layout,cache)}
    candidates=sorted(accepted.values(),key=lambda item:item['structure']['score'],reverse=True)[:64]
    for item in candidates:
        item['texture']=score_layout_texture(frame_rgb,pieces,item['layout'],cache)
    for item in candidates:
        item['texture']=relative_texture_matches(item['texture'],cache.get('pairs',{}))
        item['rank']=item['structure']['score']*.65+item['texture']['score']*.35
    candidates.sort(key=lambda item:item['rank'],reverse=True)
    return {'candidates':candidates[:candidate_limit],'nodes':nodes,'search_complete':True,
            'candidate_pool_complete':len(accepted)<=candidate_limit,
            'elapsed_ms':(time.monotonic()-started)*1000}
