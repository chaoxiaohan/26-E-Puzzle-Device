"""Compare physical piece identities/rotations up to a common rigid pose."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def landmarks(record, reference):
    layout={int(key):np.asarray(value) for key,value in record['pattern_layout'].items()}
    targets={}
    for index,piece in enumerate(record['source_pieces']):
        source=np.asarray(piece['points'])
        target=layout[index]
        a,b=source.mean(axis=0),target.mean(axis=0)
        u,_,vt=np.linalg.svd((source-a).T@(target-b))
        rotation=vt.T@u.T
        assert np.linalg.det(rotation)>0,'Reflected piece'
        center=np.asarray(reference[index]['points']).mean(axis=0)
        points=np.array([center,center+(25,0),center+(0,25)])
        targets[index]=(points-a)@rotation.T+b
    return targets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference',type=Path)
    parser.add_argument('current',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rows=[]
    for path in sorted(args.reference.glob('20*.json')):
        before=json.loads(path.read_text())
        after=json.loads((args.current/path.name).read_text())
        row={'capture':path.stem,'kind':before['kind'],'status':after['status'],'reference_status':before['status'],
             'seconds':after['seconds']}
        if before['kind']=='plain':
            row['passed']=not (after.get('info') or {}).get('card_execution_ready',False) and after['status']!='VERIFIED'
        else:
            if after.get('pattern_layout') is None or len(before['source_pieces'])!=len(after['source_pieces']):
                row.update(passed=False,pose_error_pixels=None)
            else:
                a=landmarks(before,before['source_pieces'])
                b=landmarks(after,before['source_pieces'])
                ac,bc=a[0].mean(axis=0),b[0].mean(axis=0)
                u,_,vt=np.linalg.svd((a[0]-ac).T@(b[0]-bc))
                rotation=vt.T@u.T
                assert np.linalg.det(rotation)>0,'Reflected assembly'
                error=max(float(np.linalg.norm((a[index]-ac)@rotation.T+bc-b[index],axis=1).max()) for index in a)
                row.update(pose_error_pixels=error,passed=error<=.05 and before['status']==after['status'])
            first,last=path.with_suffix('.png'),(args.current/path.name).with_suffix('.png')
            row['primary_image_identical']=first.exists() and last.exists() and hashlib.sha256(first.read_bytes()).digest()==hashlib.sha256(last.read_bytes()).digest()
        rows.append(row)
    result={'count':len(rows),'poker_count':sum(r['kind']!='plain' for r in rows),
            'passed':bool(rows) and all(r['passed'] for r in rows),'pose_tolerance_pixels':.05,'cases':rows}
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))
    for row in rows:
        if not row['passed']:
            print(json.dumps(row))
    assert result['passed'],'Cross-platform card regression'


if __name__=='__main__':
    main()
