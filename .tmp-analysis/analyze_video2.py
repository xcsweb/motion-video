import subprocess, json, os, numpy as np, re
from PIL import Image
from collections import Counter

REF='/workspace/reference/av19390801-guichu-ref.mp4'
OUT='/workspace/.tmp-analysis'
PERIOD=60/105.47
BAR=PERIOD*4

shots=json.load(open(OUT+'/shots.json'))

# ---------- cut alignment to beat/bar ----------
print('--- cut alignment ---')
pos_bar=[]; pos_beat=[]; lens_beats=[]
for s in shots[1:]:
    t=s['start']
    pos_bar.append(((t % BAR)/BAR))
    pos_beat.append(((t % PERIOD)/PERIOD))
    lens_beats.append(s['dur']/PERIOD)
pos_bar=np.array(pos_bar); pos_beat=np.array(pos_beat)
# concentration: share within +-0.06 of a 16th grid? and within +-0.1 of beat
def conc(p, tol, n):
    d=np.minimum(p%1, 1-(p%1))
    # fold to nearest 1/n grid
    q=(p*n)%1
    d=np.minimum(q,1-q)/n
    return float((d<tol).mean())
print('cuts within 60ms of beat', round(float((np.minimum(pos_beat,1-pos_beat)*PERIOD<0.06).mean()),3))
print('cuts within 80ms of half-bar', round(float((np.minimum((pos_bar*2)%1,1-(pos_bar*2)%1)*BAR/2<0.08).mean()),3))
print('cuts within 60ms of 16th grid', round(float((np.minimum((pos_bar*16)%1,1-(pos_bar*16)%1)*BAR/16<0.06).mean()),3))
print('random baseline 16th 60ms', round(0.06/(BAR/16),3))

lb=np.array(lens_beats)
print('shot length in beats: median', round(float(np.median(lb)),2), 'p10',round(float(np.percentile(lb,10)),2),'p90',round(float(np.percentile(lb,90)),2))
hist=Counter()
for v in lb:
    for q,name in [(0.25,'1/16'),(0.5,'1/8'),(1,'1/4'),(2,'1/2'),(4,'1'),(8,'2'),(16,'4')]:
        if abs(v-q)<q*0.28: hist[name]+=1; break
    else: hist['other']+=1
print('shot length classes (beats->bars):', dict(hist))

# ---------- subtitle band timeline (10fps) ----------
subdir=OUT+'/subframes'
os.makedirs(subdir,exist_ok=True)
subprocess.run(f"rm -f {subdir}/*.png", shell=True)
subprocess.run(['ffmpeg','-v','error','-y','-i',REF,'-vf',
                "fps=10,crop=iw:ih*0.11:0:ih*0.825",f'{subdir}/%05d.png'])
files=sorted(os.listdir(subdir))
print('\nsubtitle frames', len(files), 'fps 10')
sigs=[]; ratios=[]
for fn in files:
    im=np.array(Image.open(f'{subdir}/{fn}').convert('L'))
    m=im>165
    ratios.append(float(m.mean()))
    small=np.array(Image.fromarray((m*255).astype(np.uint8)).resize((64,8),Image.BILINEAR))>60
    sigs.append(small)
ratios=np.array(ratios)
print('white ratio: median', round(float(np.median(ratios)),4), 'p90',round(float(np.percentile(ratios,90)),4))

# text present if ratio above threshold
thr=max(0.006, np.percentile(ratios,70)*0.55)
present=ratios>thr
# group presence
groups=[]
i=0
while i<len(present):
    if not present[i]: i+=1; continue
    j=i
    while j<len(present) and present[j]: j+=1
    groups.append((i/10,j/10))
    i=j
groups=[g for g in groups if g[1]-g[0]>=0.3]
print('subtitle visible segments', len(groups), 'total visible %.1fs'%sum(b-a for a,b in groups))

# signature change within visible runs
changes=[]
for a,b in groups:
    i0=int(a*10); i1=int(b*10)
    prev=None
    for i in range(i0,min(i1,len(sigs))):
        cur=sigs[i]
        if prev is not None:
            d=np.logical_xor(prev,cur).mean()
            if d>0.22: changes.append(i/10)
        prev=cur
# merge close changes
ch=[]
for t in changes:
    if not ch or t-ch[-1]>0.28: ch.append(t)
print('subtitle change points', len(ch), '=> changes/min', round(len(ch)/(152.04/60),1))
print('first 30 changes', [round(t,2) for t in ch[:30]])
gaps=np.diff(ch)
print('subtitle dwell median', round(float(np.median(gaps)),2), 's =', round(float(np.median(gaps))/PERIOD,2),'beats')

# relation: subtitle changes vs shot cuts
cut_times=[s['start'] for s in shots]
def nearest(t, arr):
    a=np.array(arr); return float(np.min(np.abs(a-t)))
d_sub_to_cut=[nearest(t,cut_times) for t in ch]
print('subtitle change -> nearest cut: median %.2fs, within 0.15s %.0f%%'%(np.median(d_sub_to_cut), float((np.array(d_sub_to_cut)<0.15).mean()*100)))

# ---------- per-shot subtitle presence ----------
print('\n--- per-shot subtitle ---')
for s in shots[:60]:
    a,b=s['start'],s['end']
    i0,i1=int(a*10),int(b*10)
    r=float(np.median(ratios[i0:i1])) if i1>i0 else 0
    s['sub_ratio']=round(r,4)
    s['has_sub']=bool(r>thr)
print('shots with subtitle', sum(1 for s in shots if s.get('has_sub')), '/', len(shots))

json.dump({'shots':shots,'sub_groups':groups,'sub_changes':ch,'cut_times':cut_times},
          open(OUT+'/video_timing.json','w'), ensure_ascii=False, indent=1)
print('\nsaved')

# ---------- contact sheet ----------
sel=[shots[i] for i in range(0,len(shots),max(1,len(shots)//12))][:12]
with open(OUT+'/sheet2.txt','w') as f:
    for k,s in enumerate(sel):
        t=(s['start']+s['end'])/2
        fn=f'{OUT}/cs_{k:02d}.png'
        subprocess.run(['ffmpeg','-v','error','-y','-ss',f'{t:.2f}','-i',REF,'-frames:v','1','-vf','scale=400:-1',fn])
        f.write(f"{k} {s['start']:.2f}s type {s['type']} dur {s['dur']:.2f} beat {s['dur']/PERIOD:.2f} sub {s.get('has_sub')} bright {s.get('bright')}\n")
print(open(OUT+'/sheet2.txt').read())
