"""从纸片长直边恢复测量角点，保留相机原图并保持碎片身份。"""

import math

import cv2
import numpy as np


def refine_card_piece_geometry(frame_rgb,pieces,roi):
    x,y,width,height=roi
    region=frame_rgb[y:y+height,x:x+width]
    if not region.size or len(pieces)!=4:
        return pieces,{'changed':0}
    hsv=cv2.cvtColor(region,cv2.COLOR_RGB2HSV)
    maximum=region.max(axis=2).astype(float)
    red,green_channel,blue=[region[:,:,index].astype(float) for index in range(3)]
    green=((hsv[:,:,0]>=35)&(hsv[:,:,0]<=100)&(hsv[:,:,1]>=40)&(hsv[:,:,2]>=40)
           &(green_channel-red>maximum*.12)&(green_channel-blue>maximum*.04))
    mask=(~green).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    candidates=[]
    for contour in contours:
        area=cv2.contourArea(contour)
        if area<350 or area>width*height*.25:
            continue
        candidates.append((contour+np.array([[[x,y]]]),area))
    refined=[]
    changed=0
    details=[]
    used=set()
    for piece in pieces:
        source=np.asarray(piece['points'],dtype=np.float32)
        center=source.mean(axis=0)
        nearest=sorted((np.linalg.norm(contour.reshape(-1,2).mean(axis=0)-center),index)
                       for index,(contour,_) in enumerate(candidates) if index not in used)
        if not nearest or nearest[0][0]>max(8,np.ptp(source,axis=0).max()*.12):
            refined.append(piece)
            continue
        index=nearest[0][1]
        contour,area=candidates[index]
        hull=cv2.convexHull(contour).reshape(-1,2)
        perimeter=cv2.arcLength(hull.reshape(-1,1,2).astype(np.float32),True)
        polygon=None
        for epsilon in (.007,.01,.014,.018,.024,.03):
            approximation=cv2.approxPolyDP(hull.reshape(-1,1,2).astype(np.float32),perimeter*epsilon,True).reshape(-1,2)
            if len(approximation)==4:
                polygon=approximation
                break
        if polygon is None or abs(cv2.contourArea(polygon.astype(np.float32)))/max(1,area)<.88:
            refined.append(piece)
            continue
        lines=[]
        boundary=contour.reshape(-1,2).astype(float)
        for point_id,point in enumerate(polygon):
            vector=polygon[(point_id+1)%4]-point
            length=np.linalg.norm(vector)
            axis=vector/max(1,length)
            relative=boundary-point
            along=relative@axis
            distance=np.abs(relative[:,0]*axis[1]-relative[:,1]*axis[0])
            samples=boundary[(along>length*.15)&(along<length*.85)&(distance<max(2.5,length*.035))]
            if len(samples)<3:
                lines.append((point.astype(float),axis))
                continue
            vx,vy,px,py=cv2.fitLine(samples.astype(np.float32),cv2.DIST_L2,0,.01,.01).ravel()
            lines.append((np.array([px,py],dtype=float),np.array([vx,vy],dtype=float)))
        corners=[]
        for point_id in range(4):
            first,first_axis=lines[(point_id-1)%4]
            second,second_axis=lines[point_id]
            matrix=np.column_stack((first_axis,-second_axis))
            if abs(np.linalg.det(matrix))<.2:
                break
            amount=np.linalg.solve(matrix,second-first)[0]
            corners.append(first+first_axis*amount)
        if len(corners)!=4:
            refined.append(piece)
            continue
        corners=np.asarray(corners)
        drift=max(np.min(np.linalg.norm(source[:,None]-corners[None,:],axis=2),axis=0))
        if drift>max(6,np.ptp(source,axis=0).max()*.06):
            refined.append(piece)
            continue
        fitted_area=abs(cv2.contourArea(corners.astype(np.float32)))
        if not .97<=fitted_area/max(1,abs(cv2.contourArea(source)))<=1.14:
            refined.append(piece)
            continue
        if cv2.contourArea(corners.astype(np.float32),oriented=True)*cv2.contourArea(source,oriented=True)<0:
            corners=corners[::-1].copy()
        first=int(np.argmin(np.linalg.norm(corners-source[0],axis=1)))
        corners=np.roll(corners,-first,axis=0)
        moments=cv2.moments(corners.astype(np.float32))
        center=(float(moments['m10']/moments['m00']),float(moments['m01']/moments['m00']))
        vectors=np.roll(corners,-1,axis=0)-corners
        longest=int(np.argmax(np.linalg.norm(vectors,axis=1)))
        vector=vectors[longest]
        updated=dict(piece,points=corners.tolist(),center=center,area=fitted_area,
                     source_contour=contour.reshape(-1,2).tolist(),
                     angle=math.degrees(math.atan2(vector[1],vector[0])))
        updated['longest_edge']=(tuple(corners[longest]),tuple(corners[(longest+1)%4]))
        refined.append(updated)
        used.add(index)
        changed+=1
        details.append({'piece':len(refined)-1,'vertex_drift':float(drift),'area_ratio':fitted_area/max(1,abs(cv2.contourArea(source)))})
    return refined,{'changed':changed,'details':details}
