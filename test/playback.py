#!/usr/bin/env python3
"""Grouped playback against the actual MIPS payload, using the regression suite's UI/deque mocks.
Run: python3 test/playback.py BUILD_DIRECTORY
"""
import pathlib
from functools import cmp_to_key
# Load only fixture definitions; the full UI suite remains independently runnable.
source = pathlib.Path(__file__).with_name('patch.py').read_text()
exec(compile(source[:source.index('checks=0')], 'test/patch.py', 'exec'))
exec(compile(source[source.index('class QueueMachine'):source.index('sel=lambda m:')], 'test/patch.py', 'exec'))
ps = symbols(B/'patch.elf')

class PlaybackMachine(QueueMachine):
    def __init__(self, files=None):
        super().__init__()
        self.files = dict(files or {}); self.handles = {}; self.fd = 100
        self.fail = ''; self.elapsed = 37; self.random_calls = 0; self.rng = 71
        self.missing = set(); self.starts = []; self.stops = 0; self.seek = None
        self.handlers.pop(syms['mclLoadPlayList'], None)
        self.handlers[ps['stock_memory_trampoline']] = 'p:fallback'
        self.handlers[ps['stock_savequeue_trampoline']] = 'p:saved'
        for name in ('calloc@GLIBC_2.0','qsort@GLIBC_2.0','memcmp@GLIBC_2.0','strcmp@GLIBC_2.0',
                     'fopen@GLIBC_2.2','fread@GLIBC_2.0','fwrite@GLIBC_2.0','fclose@GLIBC_2.2',
                     'rename@GLIBC_2.0','unlink@GLIBC_2.0','access@GLIBC_2.0','mclGetPlayTime',
                     'mclStartPlayer','mclStop','mclSetStartSeekTime','mcl_open_preload','toolsRandnum','getAllMusic'):
            self.handlers[syms[name]] = 'p:'+name.split('@')[0]
        self.word(0xa2638c, 0x1000010); self.handlers[0x1000010] = 'p:free'
        self.install([
            ('a2','/A/02.flac','Album A',1,2,0,0),
            ('b1','/B/01.flac','Album B',1,1,0,0),
            ('a1','/A/01.flac','album a',1,1,0,0),
            ('cue1','/C/image.flac','',0,0,20,40),
            ('cue2','/C/image.flac','',0,0,40,60),
            ('solo','/D/single.flac','Solo',0,0,0,0),
            ('dup','/A/01.flac','ALBUM A',1,1,0,0),
        ], 2)
    def install(self, tracks, at=0):
        rows=[]
        for name,path,album,disc,track,start,end in tracks:
            r=self.song(name)
            for key,v in [('REC_PATH',self.string(path)),('REC_ALBUM',self.string(album)),('REC_DISC',disc),
                          ('REC_TRACK',track),('REC_CUE_START',start),('REC_CUE_END',end)]: self.word(r+O[key],v)
            rows.append(r)
        self.word(syms['mcl_pdeqplaylist'],self.deque(rows)); self.word(O['MCL_POS'],at)
        self.library_rows=list(self.items(self.get(syms['mcl_pdeqplaylist'])))
    def hook(self,u,address,size,unused):
        name=self.handlers.get(address,'')
        if not name.startswith('p:'): return super().hook(u,address,size,unused)
        name=name[2:]; a,b,c,d=[u.reg_read(r) for r in REGS]; ret=0
        if name=='calloc': ret=0 if self.fail=='alloc' else self.alloc((a*b+7)&~3)
        elif name=='memcmp':
            x,y=bytes(u.mem_read(a,c)),bytes(u.mem_read(b,c)); ret=(x>y)-(x<y)
        elif name=='strcmp': x,y=self.text(a),self.text(b); ret=(x>y)-(x<y)
        elif name=='qsort':
            regs=[UC_MIPS_REG_PC,*range(UC_MIPS_REG_0,UC_MIPS_REG_31+1)]
            saved=[u.reg_read(r) for r in regs]; pair=self.alloc(2*c); sp=u.reg_read(UC_MIPS_REG_SP)
            def compare(x,y):
                u.mem_write(pair,x); u.mem_write(pair+c,y)
                for r,v in ((UC_MIPS_REG_SP,sp-0x400),(UC_MIPS_REG_RA,0x1000000),(UC_MIPS_REG_T9,d),(REGS[0],pair),(REGS[1],pair+c)): u.reg_write(r,v)
                u.emu_start(d,0x1000000,count=self.budget); return signed(u.reg_read(UC_MIPS_REG_V0))
            values=sorted([bytes(u.mem_read(a+c*i,c)) for i in range(b)],key=cmp_to_key(compare))
            for i,v in enumerate(values): u.mem_write(a+c*i,v)
            for r,v in zip(regs,saved): u.reg_write(r,v)
        elif name=='fopen':
            path,mode=self.text(a),self.text(b)
            if self.fail!='open' and (mode=='wb' or path in self.files):
                self.fd+=1; ret=self.fd; self.handles[ret]=[path,0]
                if mode=='wb': self.files[path]=b''
        elif name in ('fread','fwrite'):
            path,off=self.handles[d]; length=b*c
            if name=='fread':
                chunk=self.files[path][off:off+length]; u.mem_write(a,chunk); ret=len(chunk)//b
                self.handles[d][1]+=len(chunk)
            else:
                chunk=bytes(u.mem_read(a,length)); ret=c if self.fail!='write' else 0
                self.files[path]+=chunk if ret else chunk[:1]
        elif name=='fclose': ret=-1 if self.fail=='close' else 0; del self.handles[a]
        elif name=='rename':
            if self.fail=='rename': ret=-1
            else: self.files[self.text(b)]=self.files.pop(self.text(a))
        elif name=='unlink': self.files.pop(self.text(a),None)
        elif name=='access': ret=-1 if self.text(a) in self.missing else 0
        elif name=='mclGetPlayTime': self.word(a,self.elapsed); self.word(b,300)
        elif name=='mclStartPlayer': self.starts.append(self.mcl('MCL_POS')); ret=1
        elif name=='mclStop': self.stops+=1; ret=1
        elif name=='mclSetStartSeekTime': self.seek=a; ret=1
        elif name=='mcl_open_preload': self.word(O['MCL_PRELOAD'],1); ret=1
        elif name=='toolsRandnum':
            self.random_calls+=1; self.rng=(self.rng*1103515245+12345)&0x7fffffff; ret=self.rng%a
        elif name=='getAllMusic':
            self.deqs[self.get(syms['tools_pdeq_directory'])][1]=[self.copy('stSongInfo',e) for e in self.library_rows]; ret=len(self.library_rows)
        elif name=='folder_skip': self.folder_skips+=1
        elif name=='fallback': ret=-1
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T8,UC_MIPS_REG_T9]: u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret&0xffffffff); u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    def fn(self,name,*args): return signed(self.call(address=ps[name],args=tuple(args)+(0,)*(4-len(args)),gap=0))
    def options(self,shuffle,repeat,folder):
        for kind,value in ((2,folder),(0,shuffle),(1,repeat)): assert self.fn('playback_set',kind,value)==1
    def advance_song(self,auto=1): return self.fn('ringnav_next',auto)
    def current(self): return self.mcl('MCL_POS')
    def sequence(self,auto=1,limit=30):
        out=[self.current()]
        for _ in range(limit):
            if self.advance_song(auto)<0: break
            out.append(self.current())
        return out

checks=0
for grouping in (0,1):
    for shuffle in range(5):
        for repeat in range(6):
            m=PlaybackMachine(); m.options(shuffle,repeat,grouping)
            calls=m.random_calls; peek=m.fn('playback_successor',1)
            assert m.fn('playback_successor',1)==peek and m.random_calls==calls
            if peek>=0:
                m.fn('ringnav_preload'); assert m.mcl('MCL_PREPOS')==peek and m.random_calls==calls
                # Run the real stock gapless branch down to its mocked mutex/lyric boundaries.
                m.word(O['MCL_PRELOAD'],0)
            seq=m.sequence(limit=21)
            category={0,2,6}
            if repeat==0: assert seq==[2]
            elif repeat==1: assert set(seq)==category and len(seq)==3
            elif repeat==2: assert set(seq)==set(range(7)) and len(seq)==7
            elif repeat==3: assert set(seq)=={2} and len(seq)==22
            elif repeat==4:
                assert set(seq)<=category
                for start in range(0,18,3): assert set(seq[start:start+3])==category
            elif repeat==5:
                for start in range(0,21,7): assert set(seq[start:start+7])==set(range(7))
            if shuffle==3 and repeat==2:
                # Each album/folder stays contiguous; ordered tracks and CUE starts survive.
                groups=[0 if i in category else 1 if i==1 else 2 if i in (3,4) else 3 for i in seq]
                assert len([g for i,g in enumerate(groups) if not i or g!=groups[i-1]])==4
                assert seq.index(3)<seq.index(4)
            m=PlaybackMachine(); m.options(shuffle,repeat,grouping)
            if repeat in (0,3): assert m.advance_song(0)==1 and m.current()!=2
            if repeat in (1,4): assert set(m.sequence(0,10))<={0,2,6}
            checks+=1

# Album identity crosses folders; folder grouping does not. Disc/track and CUE order differ
# from source order, and categories keep their first appearance without shuffle.
tracks=[('disc2','/x/01','SAME',2,1,0,0),('first','/x/02','same',1,1,0,0),
        ('other-folder','/y/01','Same',1,2,0,0),('unknown','/z/01','',0,0,0,0)]
for folder,want in ((0,[1,2,0]),(1,[1])):
    m=PlaybackMachine(); m.install(tracks,1); m.options(0,1,folder)
    assert m.sequence()==want
m=PlaybackMachine(); m.install([('a','/a/1','A',0,0,0,0),('b','/b/1','B',0,0,0,0),('c','/c/1','C',0,0,0,0)],1)
m.options(0,2,0); assert m.sequence()==[1,2]
m=PlaybackMachine(); m.options(1,2,0); q=m.get(syms['mcl_pdeqplaylist'])
m.items(q).append(m.song('appended')); m.fn('playback_insert',7,1,0)
assert set(m.sequence())==set(range(8))
m.fn('playback_save'); assert '/mnt/data/ringnav-queue' in m.files
m.handlers[ps['stock_mode_trampoline']]='p:saved'; m.fn('ringnav_mode',2)
assert '/mnt/data/ringnav-queue' not in m.files and m.fn('playback_successor',1)==-1
checks+=1

# Explicit group skips bypass category boundaries and return to the previous group's start.
for folder in (0,1):
    for repeat in range(6):
        m=PlaybackMachine(); m.options(3,repeat,folder)
        assert m.fn('playback_group_skip',1)==1 and m.current() not in (0,2,6)
        assert m.fn('playback_group_skip',0)==1 and m.current()==2
        assert m.fn('playback_successor',0) in (0,6)
        checks+=1
m=PlaybackMachine(); m.install([('a','/a/1','A',0,0,0,0)],0); m.options(3,5,0)
assert m.fn('playback_group_skip',1)==0 and m.fn('playback_group_skip',0)==0
checks+=1

# Actual history, duplicates, option changes, and successor/preload consistency.
m=PlaybackMachine(); m.options(4,5,0)
seq=[m.current()]
for _ in range(6): m.advance_song(0); seq.append(m.current())
for want in reversed(seq[:-1]): assert m.fn('ringnav_prev')==1 and m.current()==want
assert m.fn('ringnav_prev')==1 and m.current()==seq[0]
pos=m.current(); elapsed=m.elapsed
assert m.fn('playback_set',2,1)==1 and m.current()==pos and m.elapsed==elapsed
m.fn('ringnav_preload'); assert m.mcl('MCL_PREPOS')==m.fn('playback_successor',1)
# Real stock handoff updates pos from the preload, without starting another decoder.
for name in ('pthread_mutex_lock@GLIBC_2.0','pthread_mutex_unlock@GLIBC_2.0','mclLoadExLyric'): m.mock(name)
m.byte(0xa3be54,1); want=m.fn('playback_successor',1); starts=len(m.starts)
assert m.advance_song()==1 and m.current()==want and len(m.starts)==starts
checks+=1

# Add and Play next remap history and occurrences, including multiple priority tracks.
m=PlaybackMachine(); m.options(1,5,0)
q=m.get(syms['mcl_pdeqplaylist']); old=m.current()
added=[m.song('priority1'),m.song('priority2')]
m.deqs[q][1][old+1:old+1]=added
m.fn('playback_insert',old+1,2,1)
assert m.current()==old
assert m.advance_song(0)==1 and m.current()==old+1
assert m.advance_song(0)==1 and m.current()==old+2
assert m.fn('ringnav_prev')==1 and m.current()==old+1
m.fn('playback_insert',len(m.items(q)),0,0)
# Replacement resets history and retains options.
new=m.deque([m.song('replacement')]); m.fn('ringnav_load',new,0,1)
assert m.fn('ringnav_prev')==1 and m.current()==0
checks+=1

# Restore exact order/history/duplicates through stock loading; preserve previous snapshot on errors.
m=PlaybackMachine(); m.options(4,5,0); m.advance_song(0); m.advance_song(0); m.fn('playback_save')
files=dict(m.files); want=m.current(); expected=m.fn('playback_successor',1)
for fail in ('open','write','close','rename','alloc'):
    m.fail=fail; m.fn('playback_save'); assert m.files['/mnt/data/ringnav-queue']==files['/mnt/data/ringnav-queue']
m.fail=''
r=PlaybackMachine(files); r.byte(syms['g_memory_play'],2); out=r.deque([])
assert r.fn('ringnav_memory',out)==want and r.seek==37
assert r.fn('playback_successor',1)==expected
r.fn('ringnav_load',out,want,1) # home_page/player_start's second load keeps restored traversal
assert r.fn('playback_successor',1)==expected and len(r.names())==7
record=r.items(r.get(syms['mcl_pdeqplaylist']))[want]
assert r.fn('playback_resumed',record)==1 and r.fn('playback_resumed',record)==0
r.elapsed=0; r.fn('playback_save')
assert struct.unpack_from('<I',r.files['/mnt/data/ringnav-queue'],24)[0]==37
r.elapsed=38; r.fn('playback_save'); r.elapsed=0; r.fn('playback_save')
assert struct.unpack_from('<I',r.files['/mnt/data/ringnav-queue'],24)[0]==0
assert r.fn('ringnav_prev')==1 and r.current()!=want
# Skip missing files; both CUE occurrences and duplicate files remain distinct.
r=PlaybackMachine(files); r.byte(syms['g_memory_play'],2); r.missing={'/B/01.flac'}
assert r.fn('ringnav_memory',r.deque([]))>=0 and len(r.names())==6
for corrupt in (b'',files['/mnt/data/ringnav-queue'][:-1],b'bad'+files['/mnt/data/ringnav-queue'][3:],files['/mnt/data/ringnav-queue']+b'x'):
    r=PlaybackMachine({'/mnt/data/ringnav-queue':corrupt}); r.byte(syms['g_memory_play'],2)
    before=r.names(); assert r.fn('ringnav_memory',r.deque([]))==-1 and r.names()==before
r=PlaybackMachine(files); r.byte(syms['g_memory_play'],1)
assert r.fn('ringnav_memory',r.deque([]))>=0 and r.seek==0
r=PlaybackMachine(files); assert r.fn('ringnav_memory',r.deque([]))==-1
checks+=1

# Selecting a stock mode during playback also closes a stale advanced repeat preload.
for skip in (0,1):
    m=PlaybackMachine(); m.word(O['MCL_POS'],6); m.options(0,5,0)
    m.fn('ringnav_preload'); assert m.mcl('MCL_PRELOAD')==1
    m.byte(0xa3be53,skip); m.fn('ringnav_mode',0)
    assert m.mcl('MCL_PRELOAD')==0
    m.advance_song(); assert m.stops==1 and m.current()==6
    checks+=1

# Stock repeat modes still repeat after advanced playback is cleared.
for mode,want in ((1,6),(3,0)):
    m=PlaybackMachine(); m.word(O['MCL_POS'],6); m.options(0,5,0); m.fn('ringnav_preload')
    assert m.fn('ringnav_mode',mode)==1 and m.mcl('MCL_PRELOAD')==0
    m.advance_song(); assert m.current()==want and m.stops==0 and len(m.starts)==1
    checks+=1

# The Library's grouped shuffles are library queues, including when grouping by folders.
for folder in (0,1):
    m=PlaybackMachine(); all=m.deque(list(m.items(m.get(syms['mcl_pdeqplaylist']))))
    assert m.fn('playback_groups',all,folder)==1
    assert m.mcl('MCL_TYPE')==0xf001 and m.opened[-1][3]==0xf001
    checks+=1

# Upgrade V1 snapshots safely; an omitted class must not turn a library into Folder Play.
def snapshot_checksum(data):
    struct.pack_into('<I',data,12,0)
    value=2166136261
    for b in data: value=((value^b)*16777619)&0xffffffff
    struct.pack_into('<I',data,12,value)
legacy=bytearray(files['/mnt/data/ringnav-queue']); del legacy[56:60]
struct.pack_into('<I',legacy,4,1); struct.pack_into('<I',legacy,8,len(legacy)); snapshot_checksum(legacy)
r=PlaybackMachine({'/mnt/data/ringnav-queue':bytes(legacy)}); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))==want and r.mcl('MCL_TYPE')==0xf001
bad=bytearray(files['/mnt/data/ringnav-queue']); struct.pack_into('<I',bad,56,5); snapshot_checksum(bad)
r=PlaybackMachine({'/mnt/data/ringnav-queue':bytes(bad)}); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))==-1
checks+=1

# Stock List Play must discard advanced repeat preloads and retain queue provenance on reboot.
for cls in (0xf001,0xff10,1):
    for skip in (0,1):
        m=PlaybackMachine(); m.word(O['MCL_TYPE'],cls); m.word(O['MCL_POS'],6)
        m.options(0,5,0); m.fn('ringnav_preload'); m.fn('playback_save')
        r=PlaybackMachine(m.files); r.byte(syms['g_memory_play'],2); out=r.deque([])
        assert r.fn('ringnav_memory',out)==6
        assert r.mcl('MCL_TYPE')==cls
        assert r.get(syms['g_memory_info'])==cls
        r.fn('ringnav_load',out,6,1) # legacy startup caller must not reclassify the restored queue
        assert r.mcl('MCL_TYPE')==cls
        r.fn('ringnav_preload'); assert r.mcl('MCL_PRELOAD')==1
        r.byte(0xa3be53,skip)
        assert r.fn('ringnav_mode',0)==1 and r.mcl('MCL_PRELOAD')==0
        assert r.mcl('MCL_PREPOS')==-1 and r.mcl('MCL_MODE')==0
        # Run native List Play, including its folder-only callback at the boundary.
        callback=0x1000020; r.handlers[callback]='p:folder_skip'
        r.word(0xa3bda8,callback); r.folder_skips=0
        r.advance_song()
        assert r.folder_skips==(1 if cls==1 and skip else 0)
        assert r.current()==6 and r.stops==1
        checks+=1

# Empty replacement cannot resurrect the previous saved queue at the next boot.
m=PlaybackMachine(); m.options(0,2,0); assert '/mnt/data/ringnav-queue' in m.files
m.fn('ringnav_load',m.deque([]),0,1); m.fn('playback_save')
assert '/mnt/data/ringnav-queue' not in m.files
checks+=1

# Empty and one-track queues, all combinations.
for n in (0,1):
    for shuffle in range(5):
        for repeat in range(6):
            m=PlaybackMachine(); m.install([('one','/one/song','',0,0,0,0)]*n)
            m.options(shuffle,repeat,0)
            assert m.fn('playback_successor',1)==(0 if n and repeat>=3 else -1)
            m.advance_song(); checks+=1

# Shared wheel threshold: compare the patched leaf directly to stock at 100% for every
# pair, and check strict scaled boundaries, half turns, and wraparound at 50/200%.
for value in (50,100,200):
    m=PlaybackMachine(); m.fn('wheel_set',value)
    for threshold in (12,24):
        scaled=(threshold*100+value//2)//value
        for now in range(200):
            for before in (0,1,50,99,100,150,199):
                d=now-before
                if d < -100: d+=200
                elif d > 100: d-=200
                want=0 if abs(d)<=scaled or abs(d)==100 else -1 if d>0 else 1
                assert m.fn('ringnav_direction',now,before,threshold)==want
    checks+=1
for invalid in ('49','201','105','100x','-100','', '0100'):
    m=PlaybackMachine(); m.config['WHEELSENSITIVITY']=invalid
    assert m.fn('wheel_value')==100
# UI wiring in both variants: stock-style choice menu, selected marker, touch and wheel slider.
m=PlaybackMachine(); m.top=m.node('window','playing_page'); m.stack=[m.top]; m.word(m.top+O['W_PARENT'],m.wm)
m.press(100); assert m.hold()==11
assert m.labels()[-5:]==['Shuffle','Repeat','Group by: Album','Next album','Previous album']
m.pick(6); m.advance(0,clear=False)
assert m.labels()==['Off','All','Songs','Categories','Songs/Categories']
assert any(n.get('image')=='select' for n in m.nodes.values())
m.pick(3); m.advance(0,clear=False); assert m.fn('playback_option',0)==3
for folder in (0,1):
    m=PlaybackMachine(); m.options(3,2,folder)
    m.top=m.node('window','playing_page'); m.stack=[m.top]; m.word(m.top+O['W_PARENT'],m.wm)
    m.press(100); assert m.hold()==11
    assert m.labels()[-2:]==(['Next folder','Previous folder'] if folder else ['Next album','Previous album'])
    m.pick(9); m.advance(0,clear=False); assert m.current() not in (0,2,6)
    checks+=1
m=PlaybackMachine(); m.handlers[ps['stock_display_trampoline']]='stock_display'
view=m.node('scroll_view','scroll_view_display'); lst=m.node('list_view','list_view_display',[view])
m.top=m.node('window','display_page',[lst]); m.stack=[m.top]
for child,parent in ((view,lst),(lst,m.top),(m.top,m.wm)): m.word(child+O['W_PARENT'],parent)
assert m.fn('ringnav_display',m.top,0)==0
item=m.nodes[view]['children'][-1]; button,slider=m.nodes[item]['children']
label=m.nodes[button]['children'][1]
assert m.nodes[label]['text']=='Wheel sensitivity: 100%'
assert m.nodes[button]['style:normal:bg_color']==0
assert m.nodes[slider]['style']=='s_ipod_progress' and m.nodes[slider]['bar_size']==10
assert m.nodes[slider]['slide_with_bar']==1 and m.nodes[slider]['style:normal:round_radius']==5
f,ctx=m.handler(slider,O['EVT_VALUE_CHANGED'])
m.nodes[slider]['value']=150; m.call(address=f,args=(ctx,m.event,0,0),gap=0)
assert m.fn('wheel_value')==150 and m.nodes[label]['text']=='Wheel sensitivity: 150%'
f,ctx=m.handler(button,O['EVT_CLICK']); m.call(address=f,args=(ctx,m.event,0,0),gap=0)
assert m.call(O['KEY_NEXT'],gap=1000)==11 and m.fn('wheel_value')==160
assert m.call(O['KEY_RETURN'],gap=1000)==11
checks+=1

# At default sensitivity, execute stock's original leaf too, including both wrap directions.
stock=Machine(patched=False); m=PlaybackMachine()
for threshold in (12,24):
    for now in range(200):
        for before in (0,99,100,199):
            want=signed(stock.call(address=syms['get_direction'],args=(now,before,threshold,0),gap=0))
            assert m.fn('ringnav_direction',now,before,threshold)==want
checks+=1

print(f'{checks} advanced playback/wheel MIPS checks passed ({variant})')
