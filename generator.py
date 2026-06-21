import json, random, hashlib, os
_HERE=os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE,'traits.json')) as f: ASSETS=json.load(f)
PALETTE=ASSETS['palette']; IMAGES=ASSETS['images']; SIZE=32
OUTLINE="0a0a14"
_EYE_DX=2
HEAD_OUT="14141f"
def _adj(hexcol, f):
    if not hexcol or len(hexcol)!=6: return hexcol
    try:
        r=int(hexcol[0:2],16); g=int(hexcol[2:4],16); b=int(hexcol[4:6],16)
    except ValueError:
        return hexcol
    r=min(255,max(0,int(r*f))); g=min(255,max(0,int(g*f))); b=min(255,max(0,int(b*f)))
    return f"{r:02x}{g:02x}{b:02x}"
import colorsys
def _hue_rotate(hexcol, deg, sat_mul=1.0):
    if not hexcol or len(hexcol)!=6 or deg==0: return hexcol
    try:
        r=int(hexcol[0:2],16)/255; g=int(hexcol[2:4],16)/255; b=int(hexcol[4:6],16)/255
    except ValueError:
        return hexcol
    h,s,v=colorsys.rgb_to_hsv(r,g,b)
    if s<0.12: return hexcol
    h=(h+deg/360.0)%1.0
    s=min(1.0,s*sat_mul)
    r,g,b=colorsys.hsv_to_rgb(h,s,v)
    return f"{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
HEAD_HUES=[(0,34),(30,8),(60,8),(120,10),(160,9),(200,10),(260,11),(300,10)]
DIAMOND=["..T..",".LMD.","LMMMD",".LMD.","..M.."]
DIAMOND_COLORS={
 "cyan": {"T":"ffffff","M":"7affe8","D":"2bb3a0","L":"caeff9"},
 "red":  {"T":"ffffff","M":"ff5a7a","D":"c01a44","L":"ffb8c8"},
 "gold": {"T":"ffffff","M":"ffce3a","D":"b8901a","L":"fff4c2"},
}
RARITY=[("cyan",70),("red",22),("gold",8)]
EYEWEAR=[("vr",20),("shades",18),("round",16),("cyclops",12),("pixel8bit",11),
         ("scouter",9),("3d",8),("laser",6)]
EYE_COLORS={
 "cyan":  {"m":"2bb3a0","hi":"caeff9","gl":"7affe8","ol":"0a3a34"},
 "gold":  {"m":"e0a81a","hi":"fff4c2","gl":"ffce3a","ol":"5a3e08"},
 "red":   {"m":"e0344f","hi":"ffb8c8","gl":"ff5a7a","ol":"4a0a1c"},
 "purple":{"m":"8a5aff","hi":"c9b3ff","gl":"9a6aff","ol":"2a1452"},
 "silver":{"m":"b8c4d4","hi":"ffffff","gl":"e0e8f0","ol":"3a4452"},
 "green": {"m":"3ac46a","hi":"c2ffd6","gl":"6aff9a","ol":"0a3a1c"},
 "orange":{"m":"ff8a3a","hi":"ffd6b8","gl":"ffaa5a","ol":"5a2e08"},
}
EYE_COLOR_W=[("cyan",22),("gold",18),("red",16),("purple",14),("silver",12),("green",10),("orange",8)]
THEME_HEADS=['goldcoin','diamond-blue','diamond-red','bank','wallet','treasurechest',
 'robot','laptop','lightning-bolt','crystalball','rock','chart-bars','rgb','satellite',
 'cash-register','wallsafe','moon','saturn','brain','ufo','calculator','cd']
head_idx={h['filename'].replace('head-',''):i for i,h in enumerate(IMAGES['heads'])}
THEME_IDX=list(range(len(IMAGES['heads'])))
BG_GRAD=[("0f1729","1e3a5f"),("1a1040","4a2a8a"),("0d2818","1a6e4a"),
  ("2a0d2e","8a2a6a"),("3a1a0d","b8701a"),("0d1f3a","2a6ad8"),("2e0d1a","c01a4a"),
  ("1a0d3a","6a3ada"),("0d3a3a","16a0a0"),("3a2a0d","d8a81a"),
  ("141a3a","3a4ad8"),("3a0d2a","d83a8a"),("0d3a1f","2ad86a"),("3a1a3a","a83ad8"),
  ("1f0d0d","8a3a3a"),("0d1a1f","3a8a9a"),("2a1f0d","9a7a2a"),("1a0d2a","7a3aaa"),
  ("0d2a2a","2a9a9a"),("2a0d0d","aa3a3a"),("0d0d2a","3a3aaa"),("1a2a0d","6a9a2a"),
  ("2a0d1f","aa3a6a"),("12182e","2e3e6e")]
BODY_COLORS={
 "ember":  {"m":"d8513a","d":"8a2a1c"}, "rust":   {"m":"c46a2a","d":"7a3a12"},
 "amber":  {"m":"d8a02a","d":"8a5e12"}, "olive":  {"m":"9aa83a","d":"5a6a1c"},
 "fern":   {"m":"5aae4a","d":"2e6a2a"}, "jade":   {"m":"3aae7a","d":"1c6a48"},
 "teal":   {"m":"2aa8a0","d":"126a64"}, "ocean":  {"m":"3a8ad8","d":"1c4e8a"},
 "azure":  {"m":"4a6ae0","d":"2a3a9a"}, "indigo": {"m":"6a5ad8","d":"3a2e8a"},
 "violet": {"m":"9a5ad8","d":"5e2e8a"}, "orchid": {"m":"c45ac4","d":"7a2e7a"},
 "rose":   {"m":"d85a8a","d":"8a2e54"}, "coral":  {"m":"e07a6a","d":"9a4438"},
 "sand":   {"m":"c7b48a","d":"8a7a52"}, "clay":   {"m":"b08868","d":"6e5238"},
 "slate":  {"m":"5a9ad8","d":"2e5e8a"}, "steel":  {"m":"4aaed0","d":"2a6e8a"},
 "ash":    {"m":"d8b84a","d":"8a701c"}, "ink":    {"m":"4a4a5a","d":"24242e"},
 "mint":   {"m":"7aceae","d":"3e8a6e"}, "sky":    {"m":"7ab4e8","d":"3e6ea8"},
 "lilac":  {"m":"b09ae0","d":"6e5aaa"}, "peach":  {"m":"e8a87a","d":"a86a44"},
}
BODY_COLOR_KEYS=list(BODY_COLORS.keys())
def decode_rle(hexstr):
    b=bytes.fromhex(hexstr[2:]); top,right,bottom,left=b[1],b[2],b[3],b[4]
    grid=[[None]*SIZE for _ in range(SIZE)]; i=5; cx,cy=left,top
    while i+1<len(b):
        length,colidx=b[i],b[i+1]; i+=2
        col=PALETTE[colidx] if colidx<len(PALETTE) and PALETTE[colidx] else None
        for _ in range(length):
            if cy<SIZE and cx<SIZE: grid[cy][cx]=col
            cx+=1
            if cx>=right: cx=left; cy+=1
    return grid
def _draw(canvas, px, outline=True, clip=False, ol_color=None):
    oc=ol_color or OUTLINE
    if clip:
        px={(y,x+_EYE_DX):c for (y,x),c in px.items()}
    px={(y,x):c for (y,x),c in px.items() if 0<=y<SIZE and 0<=x<SIZE}
    if outline:
        for (y,x) in list(px.keys()):
            for dy in(-1,0,1):
                for dx in(-1,0,1):
                    ny,nx=y+dy,x+dx
                    if (ny,nx) not in px and 0<=ny<SIZE and 0<=nx<SIZE:
                        canvas[ny][nx]=oc
    for (y,x),c in px.items(): canvas[y][x]=c
def stamp_diamond(canvas, colors, cx=15, top=23):
    rows=DIAMOND; ox=cx-max(len(r) for r in rows)//2; oy=top
    px={}
    for j,row in enumerate(rows):
        for i,ch in enumerate(row):
            if ch in colors: px[(oy+j,ox+i)]=colors[ch]
    _draw(canvas,px)
def _eye_vr(canvas,c):
    px={}
    for x in range(8,22):
        for y in range(12,15): px[(y,x)]=c['m']
    for x in range(8,22): px[(12,x)]=c['hi']
    for x in range(9,21,3): px[(13,x)]=c['gl']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_shades(canvas,c):
    px={}
    for x in range(8,14): px[(12,x)]=c['m']; px[(13,x)]=c['m']
    for x in range(16,22): px[(12,x)]=c['m']; px[(13,x)]=c['m']
    px[(11,8)]=c['m']; px[(11,16)]=c['m']
    for x in range(14,16): px[(12,x)]=c['m']
    px[(12,9)]=c['gl']; px[(12,17)]=c['gl']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_round(canvas,c):
    px={}
    def circ(cx0):
        for (y,x) in [(11,cx0),(11,cx0+1),(12,cx0-1),(12,cx0+2),(13,cx0-1),(13,cx0+2),(14,cx0),(14,cx0+1)]:
            px[(y,x)]=c['m']
        for (y,x) in [(12,cx0),(12,cx0+1),(13,cx0),(13,cx0+1)]: px[(y,x)]=c['gl']
    circ(9); circ(17)
    for x in (14,15,16): px[(12,x)]=c['m']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_3d(canvas,c):
    px={}
    for x in range(8,14): px[(12,x)]="d8344f"; px[(13,x)]="d8344f"
    for x in range(16,22): px[(12,x)]="3a6ad8"; px[(13,x)]="3a6ad8"
    for x in range(14,16): px[(12,x)]=OUTLINE
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_laser(canvas,c):
    px={}
    for x in range(-2,34): px[(13,x)]=c['m']
    for (y,x) in [(13,10),(13,11),(13,18),(13,19)]: px[(y,x)]=c['gl']
    _draw(canvas,px,outline=False,clip=True)
def _eye_cyclops(canvas,c):
    px={}
    for x in range(10,20): px[(12,x)]=c['m']; px[(14,x)]=c['m']
    for x in range(13,17):
        for y in range(12,15): px[(y,x)]=c['m']
    px[(13,14)]=c['gl']; px[(13,15)]=c['hi']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_pixel8bit(canvas,c):
    px={}
    for cx0 in (8,16):
        for x in range(cx0,cx0+6): px[(11,x)]=c['m']; px[(14,x)]=c['m']
        for y in range(11,15): px[(y,cx0)]=c['m']; px[(y,cx0+5)]=c['m']
        px[(12,cx0+2)]=c['gl']; px[(12,cx0+3)]=c['hi']
    px[(12,14)]=c['m']; px[(13,14)]=c['m']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
def _eye_scouter(canvas,c):
    px={}
    for x in range(15,21):
        for y in range(11,15): px[(y,x)]=c['m']
    px[(12,16)]=c['gl']; px[(12,17)]=c['hi']; px[(13,18)]=c['gl']
    for x in range(9,15): px[(13,x)]=c['m']
    _draw(canvas,px,clip=True,ol_color=c['ol'])
EYE_FN={"vr":_eye_vr,"shades":_eye_shades,"round":_eye_round,"3d":_eye_3d,
        "laser":_eye_laser,"cyclops":_eye_cyclops,"pixel8bit":_eye_pixel8bit,"scouter":_eye_scouter}
def weighted(rng, items):
    tot=sum(w for _,w in items); r=rng.uniform(0,tot); c=0
    for k,w in items:
        c+=w
        if r<=c: return k
    return items[-1][0]
def traits_from_seed(seed):
    rng=random.Random(hashlib.sha256(seed.encode()).hexdigest())
    bi=rng.randrange(len(IMAGES['bodies']))
    hi=rng.choice(THEME_IDX)
    eye=weighted(rng, EYEWEAR)
    eyec=weighted(rng, EYE_COLOR_W)
    rarity=weighted(rng, RARITY)
    grad=rng.choice(BG_GRAD)
    bodyc=rng.choice(BODY_COLOR_KEYS)
    hhue=weighted(rng, HEAD_HUES)
    return bi,hi,eye,eyec,rarity,grad,bodyc,hhue
def gen(seed, with_symbol=True):
    bi,hi,eye,eyec,rarity,grad,bodyc,hhue=traits_from_seed(seed)
    canvas=[[None]*SIZE for _ in range(SIZE)]
    bcol=BODY_COLORS[bodyc]
    gb=decode_rle(IMAGES['bodies'][bi]['data'])
    bys=[y for y in range(SIZE) for x in range(SIZE) if gb[y][x]]
    bbot=max(bys) if bys else SIZE-1
    for y in range(SIZE):
        for x in range(SIZE):
            if gb[y][x]:
                canvas[y][x]= bcol['d'] if y>=bbot-1 else bcol['m']
    gh=decode_rle(IMAGES['heads'][hi]['data'])
    hys=[y for y in range(SIZE) for x in range(SIZE) if gh[y][x]]
    if hys:
        ytop,ybot=min(hys),max(hys)
        for y in range(SIZE):
            for x in range(SIZE):
                if gh[y][x]:
                    for dy in(-1,0,1):
                        for dx in(-1,0,1):
                            ny,nx=y+dy,x+dx
                            if 0<=ny<SIZE and 0<=nx<SIZE and not gh[ny][nx]:
                                canvas[ny][nx]=HEAD_OUT
        for y in range(SIZE):
            for x in range(SIZE):
                col=gh[y][x]
                if not col: continue
                if hhue: col=_hue_rotate(col, hhue, sat_mul=1.08)
                if y<=ytop+1:      col=_adj(col,1.28)
                elif y>=ybot:      col=_adj(col,0.62)
                elif y>=ybot-2:    col=_adj(col,0.82)
                canvas[y][x]=col
    EYE_FN[eye](canvas, EYE_COLORS[eyec])
    if with_symbol:
        stamp_diamond(canvas, DIAMOND_COLORS[rarity])
    c1,c2=grad
    s=f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {SIZE} {SIZE}' shape-rendering='crispEdges'>"
    s+=f"<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#{c1}'/><stop offset='1' stop-color='#{c2}'/></linearGradient></defs>"
    s+=f"<rect width='{SIZE}' height='{SIZE}' fill='url(#g)'/>"
    for y in range(SIZE):
        for x in range(SIZE):
            if canvas[y][x]: s+=f"<rect x='{x}' y='{y}' width='1' height='1' fill='#{canvas[y][x]}'/>"
    head_name=IMAGES['heads'][hi]['filename'].replace('head-','')
    return s+"</svg>", (head_name, rarity, eye, eyec, bodyc, hhue)
TOTAL_SUPPLY=21000
def build_collection(n=TOTAL_SUPPLY):
    used=set(); seeds=[]
    for i in range(1, n+1):
        salt=0
        while True:
            seed=f"CC-STAMP-{i:05d}-{salt}"
            fp=traits_from_seed(seed)
            if fp not in used:
                used.add(fp); seeds.append(seed); break
            salt+=1
    return seeds
if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="verify":
        seeds=build_collection(TOTAL_SUPPLY)
        fps={traits_from_seed(s) for s in seeds}
        print(f"分配 {len(seeds)} 个, 唯一外观 {len(fps)}, 重复 {len(seeds)-len(fps)}")
        space=len(IMAGES['bodies'])*len(THEME_IDX)*len(EYEWEAR)*len(EYE_COLORS)*len(RARITY)*len(BG_GRAD)
        print(f"组合空间 {space}, 21000 占 {21000/space*100:.1f}%")
        print("OK 0重复" if len(seeds)==len(fps) else "FAIL 有重复!")
        sys.exit(0)
    n=int(sys.argv[1]) if len(sys.argv)>1 else 12
    seeds=build_collection(n)
    for i,seed in enumerate(seeds):
        svg,info=gen(seed)
        open(f'/tmp/cc_{i}.svg','w').write(svg)
        print(i, "seed:",seed,"| head:",info[0],"| badge:",info[1],"| accessory:",info[2],info[3])
