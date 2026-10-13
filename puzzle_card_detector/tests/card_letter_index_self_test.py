"""绿底字形串回归：完整对角匹配、缺字、同朝向和重复装饰。"""

import cv2
import numpy as np

from card_structure import _letter_index_evidence


def scene(missing=False,same_direction=False,decoration=False,fragmented=False,fused=False):
    frame=np.full((300,220,3),(35,145,85),np.uint8)
    paper=np.full((240,160,3),245,np.uint8)
    words=[]
    for bottom in (False,True):
        patch=np.full((90,30,3),245,np.uint8)
        for row,character in enumerate('JOKER'):
            if missing and bottom and row==4:
                continue
            if decoration:
                cv2.fillConvexPoly(patch,np.array([(10,20+row*15),(16,26+row*15),(4,26+row*15)]),(20,20,20))
            else:
                cv2.putText(patch,character,(5,25+row*15),cv2.FONT_HERSHEY_SIMPLEX,.50,(20,20,20),1,cv2.LINE_AA)
        if fragmented and bottom:
            patch[29:42,10:12]=245
        if fused and bottom:
            cv2.line(patch,(6,69),(6,76),(20,20,20),1)
        words.append(patch)
    paper[10:100,5:35]=words[0]
    paper[140:230,125:155]=words[1] if same_direction else words[1][::-1,::-1]
    frame[30:270,30:190]=paper
    return frame[30:270,30:190].max(axis=2)<100


def main():
    score,confidence,detail=_letter_index_evidence(scene())
    assert confidence>.65 and score>.80,(score,confidence,detail)
    for kwargs in ({'missing':True},{'same_direction':True},{'decoration':True}):
        wrong,_,_=_letter_index_evidence(scene(**kwargs))
        assert score>wrong+.15,(kwargs,score,wrong)
    for kwargs in ({'fragmented':True},{'fused':True}):
        repaired,reliability,evidence=_letter_index_evidence(scene(**kwargs))
        assert repaired>.75 and reliability>.60,(kwargs,repaired,reliability,evidence)
        assert evidence['characters']==[5,5]
    print('CARD_LETTER_INDEX_OK',round(score,3),round(confidence,3),detail['characters'])


if __name__=='__main__':
    main()
