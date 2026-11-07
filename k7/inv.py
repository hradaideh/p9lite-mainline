import os,re,collections,subprocess
V='/home/deck/k7/vendor'; M='/home/deck/k7/linux-7.3.1'
cfg={}
for l in open('/tmp/k16.config'):
    m=re.match(r'CONFIG_(\w+)=(y|m)',l)
    if m: cfg[m.group(1)]=1
def syms(root):
    s=set()
    for d,_,fs in os.walk(root):
        for f in fs:
            if f.startswith('Kconfig'):
                for l in open(os.path.join(d,f),errors='ignore'):
                    m=re.match(r'\s*(?:menu)?config\s+(\w+)',l)
                    if m: s.add(m.group(1))
    return s
ms=syms(M)
vendor_only=[k for k in cfg if k not in ms]
# map symbol -> dirs/files via Makefiles in vendor
hits=collections.defaultdict(set)
for d,_,fs in os.walk(V):
    if 'Makefile' in fs:
        for l in open(os.path.join(d,'Makefile'),errors='ignore'):
            for m in re.finditer(r'obj-\$\(CONFIG_(\w+)\)\s*\+?=\s*(.*)',l):
                if m.group(1) in vendor_only:
                    for t in m.group(2).split():
                        hits[m.group(1)].add(os.path.relpath(os.path.join(d,t.rstrip('/').replace('.o','')),V))
def loc(p):
    full=os.path.join(V,p)
    paths=[full] if os.path.isdir(full) else [full+'.c']
    n=0
    for q in paths:
        if os.path.isdir(q):
            for d,_,fs in os.walk(q):
                for f in fs:
                    if f.endswith(('.c','.h')): n+=sum(1 for _ in open(os.path.join(d,f),errors='ignore'))
        elif os.path.exists(q): n+=sum(1 for _ in open(q,errors='ignore'))
    return n
top=collections.Counter()
rows=[]
for s,ps in hits.items():
    for p in ps:
        n=loc(p); rows.append((n,s,p))
        top['/'.join(p.split('/')[:3])]+=n
rows.sort(reverse=True)
print('enabled syms:',len(cfg),'not in 7.3.1:',len(vendor_only),'mapped to code:',len(hits))
print('TOTAL vendor-only LOC (approx, may double count):',sum(r[0] for r in rows))
for n,s,p in rows[:45]: print(f'{n:8d} {s:40s} {p}')
