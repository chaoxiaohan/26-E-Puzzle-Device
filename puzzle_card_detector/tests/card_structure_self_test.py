"""绿底、相同矩形片的有标签回归，检查身份、朝向和缺乏花纹时的准入。"""

import math

import cv2
import numpy as np

from card_face_solver import close_card_pattern_layout
from card_structure import score_layout_structure
from main import card_execution_ready, solve_card_piece_set_worker
from tests.card_graph_self_test import _pose_error


def scene(blank=False):
    card=np.full((241,161,3),245,np.uint8)
    color=(160,24,38)

    def diamond(center,size):
        x,y=center
        polygon=np.array([(x,y-size),(x+size,y),(x,y+size),(x-size,y)],np.int32)
        cv2.fillConvexPoly(card,polygon,color)

    if not blank:
        cv2.putText(card,'7',(7,27),cv2.FONT_HERSHEY_SIMPLEX,.72,color,2,cv2.LINE_AA)
        diamond((16,40),5)
        card[-50:,-30:]=card[:50,:30][::-1,::-1]
        for center in ((45,65),(115,65),(45,120),(115,120),(45,180),(115,180),(80,92)):
            diamond(center,13)
    frame=np.empty((700,700,3),np.uint8)
    frame[:]=(35,145,85)
    pieces=[]
    expected={}
    polygons=[[(0,0),(80,0),(80,120),(0,120)],
              [(80,0),(160,0),(160,120),(80,120)],
              [(0,120),(80,120),(80,240),(0,240)],
              [(80,120),(160,120),(160,240),(80,240)]]
    for index,points in enumerate(polygons):
        polygon=np.array(points,dtype=float)
        if index%2==0:
            polygon=polygon[::-1].copy()
        angle=math.radians((17,-61,128,-149)[index])
        rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
        center=np.array(((175,175),(520,175),(175,520),(520,520))[index])
        shift=center-polygon.mean(axis=0)@rotation.T
        moved=polygon@rotation.T+shift
        warped=cv2.warpAffine(card,np.column_stack((rotation,shift)),(700,700),flags=cv2.INTER_LINEAR)
        mask=np.zeros((700,700),np.uint8)
        cv2.fillPoly(mask,[np.rint(moved).astype(np.int32)],255)
        frame[mask>0]=warped[mask>0]
        pieces.append({'points':moved.tolist(),'center':center.tolist()})
        expected[index]=polygon
    return frame,pieces,expected


def main():
    frame,pieces,expected=scene()
    correct=score_layout_structure(frame,pieces,expected)
    flipped=dict(expected)
    flipped[0]=2*expected[0].mean(axis=0)-expected[0]
    wrong=score_layout_structure(frame,pieces,flipped)
    assert correct['score']>wrong['score']+.08,(correct,wrong)
    reflected={index:polygon*np.array([-1,1]) for index,polygon in expected.items()}
    assert not score_layout_structure(frame,pieces,reflected)['valid']
    result=solve_card_piece_set_worker(frame,pieces,(0,0,700,700))
    assert result['layout'] is not None
    layout=close_card_pattern_layout(result['layout'],result['info'])
    error=_pose_error(layout,expected)
    assert error<4.0,('wrong identity or independent orientation',error)
    for index,source in enumerate(result['pieces']):
        source=np.asarray(source['points'])
        target=np.asarray(result['layout'][index])
        a=np.linalg.norm(source[:,None]-source[None,:],axis=2)
        b=np.linalg.norm(target[:,None]-target[None,:],axis=2)
        assert np.max(np.abs(a-b))<1e-5
        assert cv2.contourArea(source.astype(np.float32),oriented=True)*cv2.contourArea(target.astype(np.float32),oriented=True)>0
    print('GREEN_EQUAL_RECTANGLES',result['info']['card_status'],'pose_error',round(error,3))
    blank,blank_pieces,_=scene(blank=True)
    blank_result=solve_card_piece_set_worker(blank,blank_pieces,(0,0,700,700))
    assert not card_execution_ready(blank_result['info'])
    assert blank_result['info']['card_status']=='WEAK_TEXTURE'
    print('CARD_STRUCTURE_OK')


if __name__=='__main__':
    main()
