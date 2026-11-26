import subprocess
import numpy as np, cv2

SRC, AUD, OUT = 'refs/idle.png', 'source-audio.mp3', 'out/talk_demo.mp4'
W, H, FPS = 720, 1280, 30
DUR = 3.0

x0, y0, cw, ch = 337, 150, 550, 978
img = cv2.imread(SRC)
base = cv2.resize(img[y0:y0+ch, x0:x0+cw], (W, H), interpolation=cv2.INTER_LANCZOS4)
sx, sy = W/cw, H/ch

# mouth seam in source px (measured on refs/idle.png)
seam_src = [(594,514),(604,512),(614,510),(624,508),(636,506.5)]
seam = [(int(round((x-x0)*sx)), (y-y0)*sy) for x,y in seam_src]
LIP_X0, LIP_X1 = 584, 648           # source px
LIP_Y0, LIP_Y1 = 511, 535
lip_box = (int((LIP_X0-x0)*sx), int((LIP_Y0-y0)*sy),
           int((LIP_X1-x0)*sx), int((LIP_Y1-y0)*sy))
MAX_D = 8                           # output px of jaw drop at mouth front
X_FRONT, X_CORNER = 598, 634        # source px: full opening -> closed corner

def seam_y(px):
    pts = np.array(seam, np.float32)
    return np.interp(px, pts[:,0], pts[:,1])

def taper(src_x):
    k = (X_CORNER-src_x)/(X_CORNER-X_FRONT)
    return float(np.clip(k, 0, 1)**0.8)

def feather_mask(w, h, f=5):
    m = np.ones((h,w), np.float32)
    ramp = np.linspace(0, 1, f)
    m[:f,:] *= ramp[:,None]; m[-f:,:] *= ramp[::-1,None]
    m[:,:f] *= ramp[None,:]; m[:,-f:] *= ramp[::-1][None,:]
    return m

# --- audio envelope
raw = subprocess.run(['ffmpeg','-v','error','-i',AUD,'-ac','1','-ar','16000','-f','s16le','-'],
                     capture_output=True).stdout
pcm = np.frombuffer(raw, np.int16).astype(np.float32)/32768.0
hop, n = 160, len(pcm)//160
rms = np.sqrt(np.mean(pcm[:n*hop].reshape(n,hop)**2, axis=1))
rms = np.clip(rms/(np.percentile(rms,98)+1e-6), 0, 1)
words = [(0.00,0.42),(0.42,0.60),(0.60,0.88),(0.88,1.20),(1.40,1.54)]
def gate(t):
    return 1.0 if any(a-0.02 <= t <= b+0.02 for a,b in words) else 0.0

def env(t):
    i = int(t/0.01)
    if i >= n: return 0.0
    return float(rms[max(0,i-1):min(n,i+2)].max())*gate(t)

def render(t, a):
    frame = base.copy()
    d = a*MAX_D
    x0b, y0b, x1b, y1b = lip_box

    # 1) lower lip patch drops, leaving a real gap
    patch = base[y0b:y1b, x0b:x1b]
    if d > 0.4:
        dy = max(1, int(round(d*0.85)))
        M = np.float32([[1,0,0],[0,1,dy]])
        sh = cv2.warpAffine(patch, M, (patch.shape[1], patch.shape[0]),
                            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        m = feather_mask(patch.shape[1], patch.shape[0], 6)
        roi = frame[y0b:y1b, x0b:x1b].astype(np.float32)
        frame[y0b:y1b, x0b:x1b] = (sh*m[...,None] + roi*(1-m[...,None])).astype(np.uint8)

        # 2) fill the gap between seam and dropped lip (tapered toward the lip corner)
        pts_up, pts_dn = [], []
        for px in range(seam[0][0], seam[-1][0]+1):
            srcx = px/sx + x0
            w = taper(srcx)
            if w <= 0.01: continue
            y = seam_y(px)
            pts_up.append((px, y))
            pts_dn.append((px, y + d*w))
        if len(pts_up) >= 3:
            poly = np.array(pts_up + pts_dn[::-1], np.int32)
            mask = np.zeros((H, W), np.float32)
            cv2.fillPoly(mask, [poly], 1.0)
            mask = cv2.GaussianBlur(mask, (9, 9), 2.4)
            a_out = min(0.82, a*1.5)
            col = np.array([58, 34, 40], np.float32)
            frame = frame.astype(np.float32)
            m3 = (mask*a_out)[..., None]
            frame = frame*(1-m3) + col*m3
            if a > 0.45 and len(pts_dn) > 8:
                cx = int(np.mean([p[0] for p in pts_up[:max(3, len(pts_up)//2)]]))
                cy = int(seam_y(cx) + d*0.55)
                tm = np.zeros((H, W), np.float32)
                cv2.ellipse(tm, (cx, cy), (max(2,int(13*a)), max(1,int(2+2.2*a))), 6,
                            0, 360, 1.0, -1, cv2.LINE_AA)
                tm = cv2.GaussianBlur(tm, (7, 7), 1.8)[..., None]*(a_out*0.9)
                frame = frame*(1-tm) + np.array([104, 70, 82], np.float32)*tm
            frame = np.clip(frame, 0, 255).astype(np.uint8)

    # 3) head / breathing motion
    dx, dy = 1.8*np.sin(2*np.pi*0.5*t), 2.4*np.sin(2*np.pi*0.5*t+1.0)
    M = cv2.getRotationMatrix2D((W/2, H*0.36), 0.4*np.sin(2*np.pi*0.35*t), 1.0)
    M[0,2]+=dx; M[1,2]+=dy
    return cv2.warpAffine(frame, M, (W,H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

vw = cv2.VideoWriter('/tmp/talk_silent.mp4', cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W,H))
prev = 0.0
for i in range(int(DUR*FPS)):
    t = i/FPS
    tgt = env(t)
    prev += (tgt-prev)*(0.55 if tgt>prev else 0.20)
    vw.write(render(t, prev))
vw.release()
print('ok', seam[0], seam[-1], lip_box)
