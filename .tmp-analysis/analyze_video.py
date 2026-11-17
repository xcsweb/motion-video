import subprocess, json, os, numpy as np, csv, re

REF='/workspace/reference/av19390801-guichu-ref.mp4'
OUT='/workspace/.tmp-analysis'
os.makedirs(OUT+'/subs', exist_ok=True)

# ---------- shot detection ----------
cmd=['ffmpeg','-v','error','-i',REF,'-vf',
     "select='gt(scene,0.10)',metadata=print:file=-",'-f','null','-']
p=subprocess.run(cmd,capture_output=True,text=True)
txt=p.stdout
scores=[float(m.group(1)) for m in re.finditer(r'scene_score=([0-9.]+)', txt)]
times=[float(m.group(1)) for m in re.finditer(r'pts_time:([0-9.]+)', txt)]
print('raw cuts>0.10', len(times), 'score mean', round(np.mean(scores),3) if scores else None)
# keep strong cuts only
pairs=sorted(zip(times,scores))
ths=[]
for t in [0.25,0.3,0.35,0.4]:
    sel=[a for a,b in pairs if b>=t]
    ths.append((t,len(sel)))
print('cuts by threshold', ths)
times=[a for a,b in pairs if b>=0.30]
times=[0.0]+sorted(set(t for t in times if t>0.1))
# dedupe close
ded=[]
for t in times:
    if not ded or t-ded[-1]>0.18: ded.append(t)
print('shots', len(ded)-1)
print('first 20 cut times', [round(t,2) for t in ded[:21]])

dur=152.04
shots=[]
for i,t in enumerate(ded):
    end=ded[i+1] if i+1<len(ded) else dur
    shots.append({'i':i,'start':round(t,3),'end':round(end,3),'dur':round(end-t,3)})
json.dump(shots, open(OUT+'/shots.json','w'), indent=1)

import statistics
durs=[s['dur'] for s in shots]
print('median shot', statistics.median(durs), 'p10', np.percentile(durs,10), 'p90',np.percentile(durs,90))
print('cuts/min', (len(shots)-1)/(dur/60))

# ---------- shot frame metrics ----------
# sample 3 frames per shot (10%,50%,90%) using ffmpeg to raw rgb 160x90
def frames_at(ts):
    out=[]
    for t in ts:
        r=subprocess.run(['ffmpeg','-v','error','-ss',f'{t:.3f}','-i',REF,'-frames:v','1',
                          '-vf','scale=160:90','-f','rawvideo','-pix_fmt','rgb24','-'],
                         capture_output=True)
        a=np.frombuffer(r.stdout,dtype=np.uint8)
        if a.size==160*90*3: out.append(a.reshape(90,160,3).astype(np.float32))
    return out

def metrics(fr):
    if fr is None: return None
    g=fr.mean(2)
    bright=float(g.mean())
    mx=fr.max(2); mn=fr.min(2)
    sat=float(((mx-mn)/(mx+1e-6)).mean())
    # edge density
    gx=np.abs(np.diff(g,axis=1)).mean(); gy=np.abs(np.diff(g,axis=0)).mean()
    edge=float(gx+gy)
    # skin ratio (center)
    c=fr[20:70,40:120]
    r,gc,b=c[:,:,0],c[:,:,1],c[:,:,2]
    skin=((r>95)&(gc>40)&(b>20)&(r>gc)&(r>b)&((r-np.minimum(gc,b))>15)&(np.abs(r-gc)>15)).mean()
    return bright,sat,edge,float(skin)

for s in shots:
    ts=[s['start']+0.1, (s['start']+s['end'])/2, max(s['start']+0.1,s['end']-0.1)]
    frs=frames_at(ts)
    ms=[metrics(f) for f in frs]
    ms=[m for m in ms if m]
    if ms:
        s['bright']=round(float(np.mean([m[0] for m in ms])),1)
        s['sat']=round(float(np.mean([m[1] for m in ms])),3)
        s['edge']=round(float(np.mean([m[2] for m in ms])),2)
        s['skin']=round(float(np.mean([m[3] for m in ms])),3)
    # type heuristic
    if s.get('skin',0)>0.12 and s.get('edge',0)<18: s['type']='CU'
    elif s.get('edge',0)>25: s['type']='WIDE'
    else: s['type']='MED'

from collections import Counter
print('shot types', Counter(s['type'] for s in shots))
print('bright range', min(s.get('bright',0) for s in shots), max(s.get('bright',0) for s in shots))

# ---------- contact sheet 3x4 of interesting shots ----------
pick=[s for s in shots if s['dur']>=1.2][:12]
files=[]
for k,s in enumerate(pick):
    t=(s['start']+s['end'])/2
    fn=f'{OUT}/shot_{k:02d}.png'
    subprocess.run(['ffmpeg','-v','error','-y','-ss',f'{t:.2f}','-i',REF,'-frames:v','1',
                    '-vf','scale=480:-1',fn])
    files.append(fn)
with open(OUT+'/sheet.txt','w') as f:
    f.write('\n'.join(f"{k} {pick[k]['start']}s {pick[k]['type']} dur{pick[k]['dur']}" for k in range(len(pick))))

# ---------- subtitle OCR at 2fps ----------
subdir=OUT+'/subs'
subprocess.run(f"rm -f {subdir}/*.png", shell=True)
subprocess.run(['ffmpeg','-v','error','-y','-i',REF,'-vf',
                "fps=2,crop=iw:ih*0.24:0:ih*0.76,scale=iw*1.5:ih*1.5",f'{subdir}/%05d.png'])
files=sorted(os.listdir(subdir))
print('sub frames', len(files))
rows=[]
for i,fn in enumerate(files):
    r=subprocess.run(['tesseract',f'{subdir}/{fn}','stdout','-l','chi_sim','--psm','7','tsv'],
                     capture_output=True,text=True)
    words=[]
    for line in r.stdout.splitlines()[1:]:
        parts=line.split('\t')
        if len(parts)>=12 and parts[11].strip():
            try: conf=float(parts[10])
            except: conf=0
            if conf>30: words.append(parts[11].strip())
    text=''.join(words)
    text=re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]','',text)
    rows.append({'t':i/2,'text':text})
# group consecutive identical/non-empty
groups=[]
for r in rows:
    if not r['text']:
        continue
    if groups and r['text']==groups[-1]['text']:
        groups[-1]['end']=r['t']
    else:
        groups.append({'start':r['t'],'end':r['t'],'text':r['text']})
groups=[g for g in groups if g['end']-g['start']>=0.4]
print('\n--- subtitle groups (start-end text) ---')
for g in groups[:60]:
    print(f"{g['start']:6.1f}-{g['end']:6.1f} {g['text']}")
json.dump(groups, open(OUT+'/subs.json','w'), ensure_ascii=False, indent=1)
json.dump(shots, open(OUT+'/shots.json','w'), ensure_ascii=False, indent=1)
