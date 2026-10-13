"""枚举两条交叉切线形成的四片扇形，所有姿态仍为刚体变换。"""

import itertools
import math
import time

import cv2
import numpy as np

from card_face_solver import score_layout_texture
from card_joint_solver import layout_pose_key, relative_texture_matches
from card_structure import score_layout_structure
from layout_constraints import evaluate_layout
from solver_v2 import normalize_polygon


def _apex_states(points):
    source=np.asarray(points,dtype=float)
    polygon=normalize_polygon(source)
    states=[]
    for index,origin in enumerate(polygon):
        outside=np.delete(polygon,index,axis=0)
        if len(outside)>2:
            longest=max(itertools.combinations(range(len(outside)),2),key=lambda pair:np.linalg.norm(outside[pair[0]]-outside[pair[1]]))
            first,last=outside[list(longest)]
            vector=last-first
            difference=outside-first
            distance=np.abs(vector[0]*difference[:,1]-vector[1]*difference[:,0])/max(1,np.linalg.norm(vector))
            if distance.max()>max(2.5,np.linalg.norm(vector)*.035):
                continue
        a=polygon[(index-1)%len(polygon)]-origin
        b=polygon[(index+1)%len(polygon)]-origin
        first_length,second_length=np.linalg.norm(a),np.linalg.norm(b)
        if min(first_length,second_length)<10:
            continue
        angle=math.atan2(float(b[0]*a[1]-b[1]*a[0]),float(np.dot(a,b)))
        if not math.radians(25)<angle<math.radians(150):
            continue
        axis=math.atan2(b[1],b[0])
        rotation=np.array([[math.cos(axis),math.sin(axis)],[-math.sin(axis),math.cos(axis)]])
        target=(polygon-origin)@rotation.T
        if cv2.contourArea(source.astype(np.float32),oriented=True)<0:
            target=target[::-1].copy()
        states.append({'polygon':target,'span':angle,'before':first_length,'after':second_length})
    return states


def generate_fan_card_candidates(frame_rgb,pieces,candidate_limit=24,cache=None):
    started=time.monotonic()
    empty={'candidates':[],'nodes':0,'search_complete':True}
    if len(pieces)!=4 or any(not 3<=len(piece['points'])<=5 for piece in pieces):
        return empty
    options=[_apex_states(piece['points']) for piece in pieces]
    if any(not values for values in options):
        return empty
    cache={} if cache is None else cache
    unique={}
    nodes=0
    for order in itertools.permutations((1,2,3)):
        ids=(0,*order)
        for states in itertools.product(*(options[index] for index in ids)):
            nodes+=1
            if abs(sum(s['span'] for s in states)-2*math.pi)>math.radians(8):
                continue
            if any(abs(states[index]['before']-states[(index+1)%4]['after'])>
                   max(4,states[index]['before']*.08) for index in range(4)):
                continue
            layout={}
            angle=0.0
            for index,state in zip(ids,states):
                rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
                layout[index]=state['polygon']@rotation.T
                angle+=state['span']
            key=layout_pose_key(layout)
            if key in unique:
                continue
            report=evaluate_layout(layout,edge_tolerance_ratio=.065)
            if report['coverage']<.84 or report['overlap']>.008 or report['outer_piece_ratio']<.999 or report['aspect']>2.2:
                continue
            unique[key]={'layout':layout,'report':report,'structure':score_layout_structure(frame_rgb,pieces,layout,cache),
                         'source':'card-fan','assignment':ids}
    candidates=sorted(unique.values(),key=lambda item:item['structure']['score'],reverse=True)[:64]
    for item in candidates:
        item['texture']=score_layout_texture(frame_rgb,pieces,item['layout'],cache)
    for item in candidates:
        item['texture']=relative_texture_matches(item['texture'],cache.get('pairs',{}))
        item['rank']=item['structure']['score']*.65+item['texture']['score']*.35
    candidates.sort(key=lambda item:item['rank'],reverse=True)
    return {'candidates':candidates[:candidate_limit],'nodes':nodes,'search_complete':True,
            'candidate_pool_complete':len(unique)<=candidate_limit,
            'elapsed_ms':(time.monotonic()-started)*1000}
