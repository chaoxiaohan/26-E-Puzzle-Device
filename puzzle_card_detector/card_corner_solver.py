"""用四个真实纸角构建整牌，保留每片旋转和平移的顶点对应。"""

import itertools
import heapq
import math
import time

import cv2
import numpy as np

from card_face_solver import score_layout_texture
from card_joint_solver import layout_pose_key, relative_texture_matches
from card_structure import score_layout_structure
from layout_constraints import evaluate_layout
from solver_v2 import normalize_polygon


def _corner_states(points):
    source=np.asarray(points,dtype=float)
    polygon=normalize_polygon(source)
    states=[]
    corners=[(index,origin,polygon[(index-1)%len(polygon)],polygon[(index+1)%len(polygon)])
             for index,origin in enumerate(polygon)]
    lengths=np.linalg.norm(np.roll(polygon,-1,axis=0)-polygon,axis=1)
    if len(polygon)>4:
        for index in range(len(polygon)):
            first=polygon[(index-1)%len(polygon)]
            start=polygon[index]
            end=polygon[(index+1)%len(polygon)]
            last=polygon[(index+2)%len(polygon)]
            short=np.linalg.norm(end-start)
            before,after=start-first,last-end
            if short>max(5.0,float(lengths.max())*.16) or min(np.linalg.norm(before),np.linalg.norm(after))<max(8,short*2):
                continue
            matrix=np.column_stack((before,-after))
            if abs(np.linalg.det(matrix))<np.linalg.norm(before)*np.linalg.norm(after)*.10:
                continue
            amount=np.linalg.solve(matrix,end-start)[0]
            origin=start+before*amount
            if max(np.linalg.norm(origin-start),np.linalg.norm(origin-end))>max(8,float(lengths.max())*.12):
                continue
            corners.append((index,origin,first,last))
    for corner,origin,previous_point,next_point in corners:
        first=previous_point-origin
        second=next_point-origin
        a,b=np.linalg.norm(first),np.linalg.norm(second)
        if min(a,b)<8:
            continue
        cosine=float(np.dot(first,second)/(a*b))
        if abs(cosine)>0.22:
            continue
        angle=math.atan2(second[1],second[0])
        other=math.atan2(first[1],first[0])-math.pi/2
        difference=math.atan2(math.sin(other-angle),math.cos(other-angle))
        angle+=difference*.5
        rotation=np.array([[math.cos(angle),math.sin(angle)],[-math.sin(angle),math.cos(angle)]])
        target=(polygon-origin)@rotation.T
        previous=first@rotation.T
        following=second@rotation.T
        if previous[1]<=0 or following[0]<=0:
            continue
        if cv2.contourArea(source.astype(np.float32),oriented=True)<0:
            target=target[::-1].copy()
        states.append({'polygon':target,'horizontal':float(following[0]),'vertical':float(previous[1]),
                       'corner':corner,'angle_error':abs(math.degrees(difference))})
    return states


def generate_corner_card_candidates(frame_rgb,pieces,candidate_limit=24,cache=None):
    started=time.monotonic()
    if len(pieces)!=4 or any(not 3<=len(piece['points'])<=8 for piece in pieces):
        return {'candidates':[],'nodes':0,'search_complete':True}
    cache={} if cache is None else cache
    choices=[_corner_states(piece['points']) for piece in pieces]
    if any(not options for options in choices):
        return {'candidates':[],'nodes':0,'search_complete':True}
    turns=(np.eye(2),np.array([[0.,-1.],[1.,0.]]),-np.eye(2),np.array([[0.,1.],[-1.,0.]]))
    area=sum(abs(cv2.contourArea(np.asarray(piece['points'],np.float32))) for piece in pieces)
    candidates=[]
    best_scores=[]
    ranking_limit=max(64,candidate_limit*3)
    seen=set()
    nodes=0
    for order in itertools.permutations((1,2,3)):
        ids=(0,*order)
        for states in itertools.product(*(choices[index] for index in ids)):
            nodes+=1
            top=states[0]['horizontal']+states[1]['vertical']
            bottom=states[2]['horizontal']+states[3]['vertical']
            left=states[0]['vertical']+states[3]['horizontal']
            right=states[1]['horizontal']+states[2]['vertical']
            width,height=max(top,bottom),max(left,right)
            if min(width,height)<20 or max(width,height)/min(width,height)>2.2:
                continue
            if abs(top-bottom)>max(5,width*.06) or abs(left-right)>max(5,height*.06):
                continue
            if not .85<=area/(width*height)<=1.06:
                continue
            spacing=max(1.0,min(width,height)*.005)
            for expansion in range(5):
                w,h=width+expansion*spacing,height+expansion*spacing
                corners=((0,0),(w,0),(w,h),(0,h))
                layout={index:state['polygon']@turn.T+corner
                        for index,state,turn,corner in zip(ids,states,turns,corners)}
                overlap=sum(cv2.intersectConvexConvex(first.astype(np.float32),second.astype(np.float32))[0]
                            for first,second in itertools.combinations(layout.values(),2))
                if overlap<=area*.004:
                    break
            if overlap>area*.004:
                continue
            key=layout_pose_key(layout)
            if key in seen:
                continue
            seen.add(key)
            span_error=abs(top-bottom)+abs(left-right)
            cutoff=best_scores[0]+.002*span_error if len(best_scores)==ranking_limit else None
            structure=score_layout_structure(frame_rgb,pieces,layout,cache,minimum_score=cutoff)
            if not structure.get('pruned'):
                rank=structure['score']-.002*span_error
                if len(best_scores)<ranking_limit:
                    heapq.heappush(best_scores,rank)
                elif rank>best_scores[0]:
                    heapq.heapreplace(best_scores,rank)
            candidates.append({'layout':layout,'structure':structure,'source':'card-corners',
                               'assignment':ids,'span_error':span_error})
    candidates.sort(key=lambda item:item['structure']['score']-.002*item['span_error'],reverse=True)
    kept=[]
    # 外角和外边缘先筛选，完整拼缝仅计算有结构依据的候选。
    for item in candidates[:max(64,candidate_limit*3)]:
        report=evaluate_layout(item['layout'],edge_tolerance_ratio=.065)
        if report['overlap']>.008 or report['coverage']<.84 or report['outer_piece_ratio']<.75:
            continue
        item['report']=report
        item['texture']=score_layout_texture(frame_rgb,pieces,item['layout'],cache)
        kept.append(item)
    pairs=cache.get('pairs',{})
    for item in kept:
        item['texture']=relative_texture_matches(item['texture'],pairs)
        item['rank']=item['structure']['score']*.65+item['texture']['score']*.35
    kept.sort(key=lambda item:item['rank'],reverse=True)
    return {'candidates':kept[:candidate_limit],'nodes':nodes,'search_complete':True,
            'candidate_pool_complete':len(kept)<=candidate_limit and len(candidates)<=max(64,candidate_limit*3),
            'elapsed_ms':(time.monotonic()-started)*1000,
            'corner_candidate_count':len(candidates),
            'excluded_structure_bound':kept[candidate_limit]['rank'] if len(kept)>candidate_limit else None}
