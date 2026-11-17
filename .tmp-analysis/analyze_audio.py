import numpy as np, json, sys
import scipy.io.wavfile as wf

def sf_read(path):
    sr, d = wf.read(path)
    if d.dtype.kind == 'i':
        d = d.astype(np.float32) / 32768.0
    return d, sr


REF = '/workspace/reference/reference-mono-22k.wav'
VOC = '/workspace/reference/reference-vocals-separated.wav'
SR = 22050

x, sr = sf_read(REF)
if x.ndim > 1: x = x.mean(1)
print('dur', len(x)/sr, 'sr', sr)

# ---------- STFT helpers ----------
def stft(x, n_fft=2048, hop=512):
    w = np.hanning(n_fft)
    n = 1 + (len(x)-n_fft)//hop
    S = np.empty((n_fft//2+1, n), dtype=np.complex64)
    for i in range(n):
        S[:, i] = np.fft.rfft(x[i*hop:i*hop+n_fft]*w)
    return S

S = stft(x)
mag = np.abs(S)
freqs = np.fft.rfftfreq(2048, 1/SR)
times = np.arange(mag.shape[1])*512/SR

# ---------- onset envelope ----------
# log-mel-ish: compress then positive diff of magnitude
logmag = np.log1p(10*mag)
flux = np.maximum(0, np.diff(logmag, axis=1)).sum(0)
flux = np.concatenate([[0], flux])
# smooth
k = np.ones(3)/3
flux_s = np.convolve(flux, k, 'same')
hop_t = 512/SR
# normalize
flux_s = flux_s/ (flux_s.max()+1e-9)

# ---------- tempo via autocorrelation ----------
fps = 1/hop_t
f = flux_s - flux_s.mean()
ac = np.correlate(f, f, 'full')[len(f)-1:]
ac = ac/ac[0]
lo, hi = int(fps*60/200), int(fps*60/60)   # 60-200 bpm
lag = lo + np.argmax(ac[lo:hi])
bpm = 60*fps/lag
print('bpm est', bpm, 'lag', lag)

# refine around 105.47
TARGET = 105.47
period = 60/TARGET
period_frames = period*fps
# phase search: maximize flux at beat positions
best = (-1, 0)
for ph in np.linspace(0, period_frames, 400, endpoint=False):
    pos = ph + np.arange(int((len(flux_s)-ph)/period_frames))*period_frames
    pos = pos[pos < len(flux_s)-1].astype(int)
    score = flux_s[pos].mean() if len(pos) else 0
    if score > best[0]: best = (score, ph)
phase = best[1]*hop_t
print('bpm', TARGET, 'period', period, 'phase', phase, 'beats', int((len(x)/sr-phase)/period))

beat_times = np.arange(phase, len(x)/sr, period)
bar_times = beat_times[::4]
print('n beats', len(beat_times), 'n bars', len(bar_times))

# ---------- chroma ----------
# tuning estimate: use spectral peaks of full signal
def chroma_map(freqs):
    # midi
    with np.errstate(divide='ignore'):
        midi = 69 + 12*np.log2(freqs/440)
    pc = np.mod(np.round(midi).astype(int), 12)
    return midi, pc

midi, pc = chroma_map(freqs)
valid = (freqs > 55) & (freqs < 4000)
idx = np.where(valid)[0]
# tuning offset: compare spectral peaks to nearest semitone
spec_mean = mag.mean(1)
peak_idx = np.where((spec_mean[1:-1] > spec_mean[:-2]) & (spec_mean[1:-1] > spec_mean[2:]))[0] + 1
peak_idx = peak_idx[valid[peak_idx]]
devs = []
for i in peak_idx:
    m = 69+12*np.log2(freqs[i]/440)
    devs.append((m - round(m)))
devs = np.array(devs)
devs = devs[np.abs(devs) < 0.5]
tuning = np.median(devs) if len(devs) else 0
print('tuning offset cents', tuning*100)

midi_bins = midi[idx] - tuning
pcs_bins = np.mod(np.round(midi_bins).astype(int), 12)
def chroma_at(t0, t1, fmin=55, fmax=2000):
    i0 = int(t0/hop_t); i1 = int(t1/hop_t)
    i0 = max(0, min(i0, len(times)-1)); i1 = max(i0+1, min(i1, len(times)))
    M = mag[idx, i0:i1]
    sel = (freqs[idx] >= fmin) & (freqs[idx] < fmax)
    M = M[sel]
    mm = midi_bins[sel]; pp = pcs_bins[sel]
    # per-frame whitening: subtract median, keep positive deviations (harmonic peaks)
    med = np.median(M, axis=0, keepdims=True)
    M = np.maximum(0, M - med)
    M = np.log1p(20*M)
    c = np.zeros(12)
    for j, k in enumerate(pp):
        c[k] += float(M[j].sum())
    c = c/(c.sum()+1e-9)
    return c

NOTE = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
def chord_of(c):
    # templates: major, minor
    best = ('?', -1)
    for root in range(12):
        maj = np.zeros(12); maj[[root,(root+4)%12,(root+7)%12]] = 1
        mi  = np.zeros(12); mi[[root,(root+3)%12,(root+7)%12]] = 1
        for name, tpl in (('', maj), ('m', mi)):
            tpl = tpl/np.linalg.norm(tpl)
            s = float(np.dot(c/np.linalg.norm(c+1e-9), tpl))
            if s > best[1]: best = (NOTE[root]+name, s)
    return best

# per-bar chroma & chord
bars = []
for bi in range(len(bar_times)):
    t0 = bar_times[bi]; t1 = bar_times[bi+1] if bi+1 < len(bar_times) else len(x)/sr
    c = chroma_at(t0, t1)
    ch, sc = chord_of(c)
    names = [NOTE[i] for i in np.argsort(c)[::-1][:4]]
    bars.append({'bar': bi, 't': round(float(t0),3), 'chord': ch, 'score': round(sc,3),
                 'top': names, 'chroma': [round(float(v),4) for v in c]})

print('\n--- per-bar chords ---')
line = []
for b in bars:
    line.append(f"{b['bar']:02d}@{b['t']:6.2f} {b['chord']:4s}({b['score']:.2f}) {''.join(b['top'][:3])}")
    if len(line) == 6:
        print('  '.join(line)); line = []
if line: print('  '.join(line))

# ---------- band energy per bar ----------
bands = [('sub',30,90),('low',90,250),('mid',250,2000),('high',2000,8000),('air',8000,16000)]
def band_energy(t0,t1):
    i0=max(0,int(t0/hop_t)); i1=min(mag.shape[1],max(i0+1,int(t1/hop_t)))
    out={}
    for name,lo,hi in bands:
        sel=(freqs>=lo)&(freqs<hi)
        out[name]=float((mag[sel,i0:i1]**2).sum())
    tot=sum(out.values())+1e-9
    return {k:v/tot for k,v in out.items()}

# ---------- RMS per bar (dB) ----------
def rms_db(t0,t1):
    a=int(t0*SR); b=min(len(x),int(t1*SR))
    if b<=a: return -120
    seg=x[a:b]
    return 20*np.log10(np.sqrt((seg**2).mean())+1e-9)

print('\n--- bar features: rms / bands / chord ---')
rows=[]
for b in bars:
    t0=b['t']; t1 = bars[b['bar']+1]['t'] if b['bar']+1<len(bars) else len(x)/sr
    be=band_energy(t0,t1); r=rms_db(t0,t1)
    b['rms_db']=round(float(r),1); b['bands']={k:round(float(v),3) for k,v in be.items()}
    rows.append(b)
for b in rows:
    print(f"bar{b['bar']:02d} {b['t']:6.2f}s {b['chord']:4s} rms{b['rms_db']:6.1f} sub{b['bands']['sub']:.2f} low{b['bands']['low']:.2f} mid{b['bands']['mid']:.2f} hi{b['bands']['high']:.2f} air{b['bands']['air']:.2f}")

# ---------- stereo width ----------
st, ssr = sf_read('/workspace/reference/reference-stereo.wav')
if st.ndim==2:
    L,R=st[:,0],st[:,1]
    mid=(L+R)/2; side=(L-R)/2
    def stwidth(t0,t1):
        a=int(t0*ssr); b=min(len(mid),int(t1*ssr))
        m=np.sqrt((mid[a:b]**2).mean()); s=np.sqrt((side[a:b]**2).mean())
        return float(s/(m+1e-9))
    print('\n--- stereo width per 8 bars ---')
    for bi in range(0,len(bar_times),8):
        t0=bar_times[bi]; t1=bar_times[min(bi+8,len(bar_times)-1)]
        print(f'{t0:6.1f}s width {stwidth(t0,t1):.3f}')

# ---------- vocal analysis ----------
v, vsr = sf_read(VOC)
if v.ndim>1: v=v.mean(1)
print('\nvocal sr', vsr, 'dur', len(v)/vsr)
# resample if needed
if vsr != SR:
    from scipy.signal import resample_poly
    g=np.gcd(SR,vsr); v=resample_poly(v, SR//g, vsr//g)
Sv=stft(v)
magv=np.abs(Sv)
logv=np.log1p(10*magv)
fluxv=np.maximum(0,np.diff(logv,axis=1)).sum(0)
fluxv=np.concatenate([[0],fluxv])
fluxv=np.convolve(fluxv,np.ones(3)/3,'same')
fluxv=fluxv/(fluxv.max()+1e-9)
tv=np.arange(magv.shape[1])*512/SR

def voiced_mask(seg):
    # crude: spectral energy in 80-1000 > threshold with harmonicity
    return seg

# vocal onset detection: peaks above adaptive threshold
from scipy.signal import find_peaks
peaks,_=find_peaks(fluxv,height=0.12,distance=int(0.06*SR/512))
print('vocal onsets', len(peaks), 'density', len(peaks)/(len(v)/SR))

# 16th-grid phase histogram
sixteenth = period/4
def grid_hist(onset_times, grid_origin):
    pos = ((np.array(onset_times)-grid_origin) % sixteenth)/sixteenth
    return pos
pos = grid_hist(tv[peaks], phase)
hist,_=np.histogram(pos,bins=16,range=(0,1))
print('vocal onset 16th histogram', (hist/hist.max()).round(2).tolist())

# per-section vocal onset density
sections=[(0,6.2),(6.2,9),(9,27.2),(27.2,33.5),(33.5,42.6),(42.6,45.4),(45.4,60.2),(60.2,103.4),(103.4,152.04)]
print('\n--- section: vocal onset/s, rms, sub/high ---')
for a,b in sections:
    sel=(tv[peaks]>=a)&(tv[peaks]<b)
    dens=sel.sum()/(b-a)
    print(f'{a:6.1f}-{b:6.1f}s  onsets/s {dens:5.2f}  n={sel.sum()}')

# pyworld F0 / note segmentation
import pyworld as pw
f0, t = pw.harvest(v.astype(np.float64), SR, frame_period=10.0)
f0 = pw.stonemask(v.astype(np.float64), f0, t, SR)
# median smooth voiced f0 (5 frames)
fv = f0.copy(); vv = fv>0
for i in range(2, len(fv)-2):
    if vv[i-2:i+3].all(): fv[i] = np.median(fv[i-2:i+3])
f0 = fv
voiced = f0>0
print('voiced frac', float(voiced.mean()))

# note segmentation
notes=[]
i=0; n=len(f0)
while i<n:
    if f0[i]<=0: i+=1; continue
    j=i
    while j<n and f0[j]>0:
        # break on jump
        if j>i:
            cents=1200*np.log2(f0[j]/f0[j-1])
            if abs(cents)>70: break
        j+=1
    seg=f0[i:j]
    if len(seg)>=5:
        med=float(np.median(seg))
        cents=1200*np.log2(med/440)
        midi_note=69+cents/12
        notes.append({'t0':float(t[i]),'dur':float(len(seg)*0.01),'f0':med,'midi':float(midi_note)})
    i=j
print('notes', len(notes))
if notes:
    durs=np.array([n['dur'] for n in notes])
    print('note dur median', np.median(durs), 'p10',np.percentile(durs,10),'p90',np.percentile(durs,90))
    pcs=np.mod(np.round([n['midi'] for n in notes]).astype(int),12)
    # pitch class histogram in C
    print('pitch class hist (C..B)', np.bincount(pcs,minlength=12).tolist())
    # repeats: same midi within 80ms of each other
    rep=0
    for a,b in zip(notes,notes[1:]):
        if abs(a['midi']-b['midi'])<0.6 and (b['t0']-(a['t0']+a['dur']))<0.08:
            rep+=1
    print('adjacent repeated-note events', rep, f'({rep/max(1,len(notes)-1)*100:.1f}%)')

out={'bpm':TARGET,'phase':phase,'period':period,'sixteenth':sixteenth,
     'bars':rows,'notes':[{k:float(vv) if isinstance(vv,(np.floating,np.integer)) else vv for k,vv in n.items()} for n in notes],'vocal_onset_hist':[float(z) for z in (hist/hist.max()).round(3)],
     'vocal_onsets':len(peaks)}
json.dump(out, open('/workspace/.tmp-analysis/reference_audio.json','w'), ensure_ascii=False, indent=1)
print('\nsaved json')
