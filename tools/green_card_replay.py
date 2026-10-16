import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import subprocess
import platform
import sys
import time


def plain(value):
    if hasattr(value,'tolist'):
        return value.tolist()
    if hasattr(value,'item'):
        return value.item()
    raise TypeError(type(value).__name__)


def run_one(args, task, output):
    stage=Path(args.backend).resolve()
    os.environ['PUZZLE_HEADLESS']='1'
    os.environ['PUZZLE_UI_DIR']=str(output/'runtime')
    sys.path.insert(0,str(stage))
    import cv2
    import numpy as np
    import main as backend
    from card_face_solver import close_card_pattern_layout
    cv2.setNumThreads(1)
    from cpp_rectangle_solver import load_library
    if os.name=='nt':
        if not args.cpp_library:
            raise RuntimeError('Windows replay requires a native --cpp-library DLL')
        dll_directory=os.add_dll_directory(str(Path(args.cpp_library).resolve().parent))
    if load_library(args.cpp_library or str(stage/'librectangle_solver.so')) is None:
        raise RuntimeError('Native C++ solver was not loaded')
    case=next(r for r in json.loads((task/'green-cases.json').read_text())['cases'] if r['capture']==args.one)
    data=case['capture_data']
    assert case['background']=='green','Only green-background captures are allowed'
    image_path=task/'originals'/(args.one+'_raw.png')
    assert hashlib.sha256(image_path.read_bytes()).hexdigest()==data['raw_sha256'],image_path
    frame=cv2.cvtColor(cv2.imread(str(image_path)),cv2.COLOR_BGR2RGB)
    if args.fresh_detection:
        parameters=dict(data['detection_parameters'])
        pieces,detected=backend.detect_pieces(frame,tuple(data['roi']),**parameters)
    else:
        pieces=[dict(r,longest_edge=(r['points'][0],r['points'][1])) for r in data['detected_pieces']]
    candidates=[]
    evaluate=backend.evaluate_card_candidate
    def trace(*positional,**keywords):
        candidate=evaluate(*positional,**keywords)
        if candidate is not None:
            candidates.append(candidate)
        return candidate
    backend.evaluate_card_candidate=trace
    start=time.monotonic()
    result=backend.solve_card_piece_set_worker(frame,pieces,tuple(data['roi']))
    elapsed=time.monotonic()-start
    info=result.get('info') or {}
    preview=result.get('preview_rgb')
    if preview is not None:
        cv2.imwrite(str(output/(args.one+'.png')),cv2.cvtColor(preview,cv2.COLOR_RGB2BGR))
    candidates.sort(key=backend.card_candidate_primary_score,reverse=True)
    records=[]
    for rank,candidate in enumerate(candidates,1):
        records.append({'rank':rank,'score':backend.card_candidate_primary_score(candidate),
                        'pattern_layout':candidate['pattern_layout'],'info':candidate['info']})
    tiles=[]
    for item in result.get('candidate_pool',[])[:8]:
        image=cv2.cvtColor(item['preview_rgb'],cv2.COLOR_RGB2BGR)
        scale=min(1.0,250/image.shape[1],245/image.shape[0])
        if scale<1:
            image=cv2.resize(image,None,fx=scale,fy=scale)
        tile=np.full((285,270,3),55,np.uint8)
        tile[32:32+image.shape[0],10:10+image.shape[1]]=image
        cv2.putText(tile,'#%d score %.3f' % (item['rank'],item['score']),(8,22),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
        tiles.append(tile)
    if tiles:
        while len(tiles)%4:
            tiles.append(np.full((285,270,3),55,np.uint8))
        cv2.imwrite(str(output/(args.one+'-candidates.jpg')),np.vstack([np.hstack(tiles[n:n+4]) for n in range(0,len(tiles),4)]))
    report={'capture':args.one,'kind':case['kind'],'piece_count':len(pieces),'seconds':elapsed,
            'status':info.get('card_status','NO_LAYOUT'),'method':info.get('method'),
            'layout_found':result['layout'] is not None,'score':result.get('score'),
            'nodes':result.get('nodes'),'info':info,'source_pieces':result.get('pieces',pieces),
            'pattern_layout':close_card_pattern_layout(result['layout'],info) if result['layout'] is not None else None,
            'candidates':records}
    report['environment']=platform.system()+'-'+platform.machine()+'-native-cpp'
    report['detection']='fresh' if args.fresh_detection else 'frozen-board-detections'
    (output/(args.one+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=plain))
    print(json.dumps({k:report[k] for k in ('capture','kind','piece_count','seconds','status','method','score','nodes')},default=plain),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--one')
    parser.add_argument('--round',default='v1')
    parser.add_argument('--subset',action='store_true')
    parser.add_argument('--backend',required=True)
    parser.add_argument('--task-dir',type=Path,required=True)
    parser.add_argument('--all-green',action='store_true')
    parser.add_argument('--cpp-library')
    parser.add_argument('--fresh-detection',action='store_true')
    args=parser.parse_args()
    task=args.task_dir.resolve()
    output=task/('replay-'+args.round)
    output.mkdir(parents=True,exist_ok=True)
    if args.one:
        run_one(args,task,output)
        return
    cases=json.loads((task/'green-cases.json').read_text())['cases']
    assert cases and all(case['background']=='green' for case in cases)
    if args.subset:
        names=('20260801_013955_116','20260801_014047_329','20260801_032606_145','20260801_192916_754',
               '20260801_215940_303','20260801_225517_181','20260802_014544_004','20260802_013324_510')
        cases=[r for r in cases if r['capture'] in names]
    else:
        cases=cases if args.all_green else [r for r in cases if r['kind'] in ('poker','printed','joker')]
    backend=args.backend
    hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(backend).glob('*.py')}
    (output/'source-hashes.json').write_text(json.dumps(hashes,indent=2))
    results=[]
    for case in cases:
        started=time.monotonic()
        try:
            command=[sys.executable,__file__,'--one',case['capture'],'--round',args.round,'--task-dir',str(task)]
            if backend:
                command.extend(['--backend',backend])
            if args.cpp_library:
                command.extend(['--cpp-library',args.cpp_library])
            if args.fresh_detection:
                command.append('--fresh-detection')
            process=subprocess.run(command,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
            (output/(case['capture']+'.log')).write_bytes(process.stdout)
            path=output/(case['capture']+'.json')
            report=json.loads(path.read_text()) if process.returncode==0 and path.exists() else {
                'capture':case['capture'],'kind':case['kind'],'status':'ERROR','seconds':time.monotonic()-started}
            report['exit_code']=process.returncode
        except subprocess.TimeoutExpired as error:
            (output/(case['capture']+'.log')).write_bytes(error.stdout or b'')
            report={'capture':case['capture'],'kind':case['kind'],'status':'TIMEOUT','exit_code':124,'seconds':120}
        results.append({k:v for k,v in report.items() if k not in ('candidates','source_pieces','pattern_layout')})
        summary={'completed':len(results),'total':len(cases),'statuses':dict(collections.Counter(r['status'] for r in results)),
                 'cases':results}
        temporary=output/'results.json.tmp'
        temporary.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=plain))
        for attempt in range(5):
            try:
                temporary.replace(output/'results.json')
                break
            except PermissionError:
                if attempt==4:
                    raise
                time.sleep(.05)
        print(json.dumps({k:report[k] for k in ('capture','status','seconds')},default=plain),flush=True)
    print('GREEN_REPLAY_DONE',args.round,flush=True)
    if any(row['exit_code'] for row in results):
        raise SystemExit('One or more green replays failed')


if __name__=='__main__':
    main()
