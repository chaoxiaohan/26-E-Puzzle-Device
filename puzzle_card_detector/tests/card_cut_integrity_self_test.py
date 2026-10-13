"""绿底有标签牌面：切口图案要跨片接合，允许纸片之间的小缝隙。"""

import numpy as np

from card_structure import score_layout_structure
from tests.card_structure_self_test import scene


def main():
    frame,pieces,expected=scene()
    correct=score_layout_structure(frame,pieces,expected)
    separated={key:polygon.copy() for key,polygon in expected.items()}
    for key,polygon in separated.items():
        center=polygon.mean(axis=0)
        separated[key]=polygon+np.sign(center-np.array([80,120]))*3
    gap=score_layout_structure(frame,pieces,separated)
    wrong={key:polygon.copy() for key,polygon in expected.items()}
    for key in (1,2):
        wrong[key]=2*wrong[key].mean(axis=0)-wrong[key]
    broken=score_layout_structure(frame,pieces,wrong)
    assert correct['cut_integrity_confidence']>.65
    assert correct['cut_integrity']>.75,correct
    assert gap['cut_integrity']>.65,gap
    assert correct['cut_integrity']>broken['cut_integrity']+.20,(correct,broken)
    blank,blank_pieces,blank_expected=scene(blank=True)
    neutral=score_layout_structure(blank,blank_pieces,blank_expected)
    assert neutral['confidence']==0
    print('CARD_CUT_INTEGRITY_OK',round(correct['cut_integrity'],3),round(gap['cut_integrity'],3),round(broken['cut_integrity'],3))


if __name__=='__main__':
    main()
