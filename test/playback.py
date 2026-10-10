#!/usr/bin/env python3
"""Grouped playback against the actual MIPS payload, using the regression suite's UI/deque mocks.
Run: python3 test/playback.py BUILD_DIRECTORY
"""
import pathlib
from unicorn import UC_HOOK_MEM_READ
from functools import cmp_to_key
# Load only fixture definitions; the full UI suite remains independently runnable.
source = pathlib.Path(__file__).with_name('patch.py').read_text()
exec(compile(source[:source.index('checks=0')], 'test/patch.py', 'exec'))
exec(compile(source[source.index('class QueueMachine'):source.index('sel=lambda m:')], 'test/patch.py', 'exec'))
ps = symbols(B/'patch.elf')

class PlaybackMachine(QueueMachine):
    def __init__(self, files=None):
        super().__init__()
        self.files = dict(files or {}); self.files['/dev/urandom'] = bytes(range(16)); self.handles = {}; self.fd = 100
        self.entropy = 0; self.fail = ''; self.elapsed = 37; self.random_calls = 0; self.rng = 71
        self.allocations = 0; self.write_opens = 0
        self.missing = set(); self.starts = []; self.stops = 0; self.seek = None; self.stock_resume = None
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
        if name=='calloc':
            self.allocations+=1
            ret=0 if self.fail=='alloc' else self.alloc((a*b+7)&~3)
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
            if path=='/dev/urandom' and len(self.files.get(path,b''))==16:
                self.entropy+=1; self.files[path]=self.entropy.to_bytes(16,'little')
            if mode=='wb': self.write_opens+=1
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
            if self.fail=='rename' or (self.fail=='checkpoint-rename' and self.text(b).endswith('-elapsed')): ret=-1
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
        elif name=='fallback':  # stock resume: stock_resume's (class, rows, index) into out, else none
            cls,rows,ret=self.stock_resume or (0,[],-1)
            self.deqs[a][1]=[self.copy('stSongInfo',e) for e in rows]; self.word(syms['g_memory_info'],cls)
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

# Album identity (name, then album artist, else folder) crosses folders with an album artist;
# folder grouping does not. Disc/track and CUE order differ from source order, and categories keep
# their first appearance without shuffle.
tracks=[('disc2','/x/01','SAME',2,1,0,0),('first','/x/02','same',1,1,0,0),
        ('other-folder','/y/01','Same',1,2,0,0),('unknown','/z/01','',0,0,0,0)]
for folder,artist,want in ((0,1,[1,2,0]),(1,1,[1]),(0,0,[1,0])):
    m=PlaybackMachine(); m.install(tracks,1)
    for r in m.items(m.get(syms['mcl_pdeqplaylist']))[:3*artist]: m.word(r+O['REC_ALBUM_ARTIST'],m.string('Artist'))
    m.options(0,1,folder)
    assert m.sequence()==want
# Without an album artist, an album's disc folders are one album group and another folder of the
# name is not; Shuffle Folders keeps each disc folder apart.
tracks=[('disc2','/m/Purple/Disc 2/01','Purple',0,0,0,0),('cd1','/m/Purple/CD1/01','Purple',0,0,0,0),
        ('other','/m/STP Purple/01','Purple',0,0,0,0)]
for folder,want in ((0,[1,0]),(1,[1])):
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
    m.fail=fail; m.elapsed+=1; m.fn('playback_save'); assert m.files['/mnt/data/ringnav-queue']==files['/mnt/data/ringnav-queue']
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
assert struct.unpack_from('<I',r.files['/mnt/data/ringnav-queue-elapsed'],36)[0]==0
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
# Without a snapshot, stock rebuilds an album queue (0xff10) from every album of its name: only
# the resumed track's album stays, at its index there. Other classes stay as stock built them.
for cls,want in ((0xff10,(1,['a2','a1'])),(0xf001,(2,['a2','b1','a1']))):
    r=PlaybackMachine(); r.byte(syms['g_memory_play'],2); rows=r.library_rows[:3]; out=r.deque([])
    for e in rows: r.word(e+O['REC_ALBUM'],r.string('Album A'))
    r.stock_resume=(cls,rows,2); assert (r.fn('ringnav_memory',out),r.names(out))==want
checks+=1

# Missing priority files retain the remaining Play Next block and a valid next-boot snapshot.
m=PlaybackMachine(); m.options(1,5,0)
q=m.get(syms['mcl_pdeqplaylist']); at=m.current()+1
m.items(q)[at:at]=[m.song('priority1'),m.song('priority2'),m.song('priority3')]
m.fn('playback_insert',at,3,1)
for missing in ({'priority1'}, {'priority3'}, {'priority1','priority3'},
                {'priority1','priority2','priority3'}):
    r=PlaybackMachine(m.files); r.byte(syms['g_memory_play'],2)
    r.library_rows.extend(r.song(n) for n in ('priority1','priority2','priority3'))
    r.missing={'/p/'+n for n in missing}
    assert r.fn('ringnav_memory',r.deque([]))==2
    r.fn('playback_save')
    saved=struct.unpack_from('<15I',r.files['/mnt/data/ringnav-queue'])
    assert saved[12]<=saved[13]<=saved[4]
    remaining=[n for n in ('priority1','priority2','priority3') if n not in missing]
    for name in remaining:
        r.advance_song(0); assert r.names()[r.current()]==name
    again=PlaybackMachine(r.files); again.byte(syms['g_memory_play'],2)
    again.library_rows.extend(again.song(n) for n in ('priority1','priority2','priority3'))
    again.missing=r.missing
    assert again.fn('ringnav_memory',again.deque([]))==2
    checks+=1

# Unchanged settings preserve the shuffle, next decoder, history, and saved queue.
m=PlaybackMachine(); m.options(4,5,0); m.advance_song(0); m.fn('playback_save')
m.fn('ringnav_preload')
state=(m.random_calls,m.allocations,m.write_opens,m.fn('playback_successor',1),dict(m.files))
for kind,value in ((0,4),(1,5),(2,0)):
    assert m.fn('playback_set',kind,value)==1
    assert m.mcl('MCL_PRELOAD')==1
    assert (m.random_calls,m.allocations,m.write_opens,m.fn('playback_successor',1),m.files)==state
for _ in range(5):
    m.fn('playback_save'); m.now+=5000; m.fn('playback_poll')
assert (m.allocations,m.write_opens)==state[1:3]
# An elapsed-time change still checkpoints, while a dirty transition saves even at the same second.
m.elapsed+=1; m.now+=5000; m.fn('playback_poll')
assert m.write_opens==state[2]+1
m.advance_song(0); m.fn('playback_poll')
assert m.write_opens==state[2]+3
checks+=1

# Failed writes preserve the prior snapshot and retry even if playback has since paused.
# Repeated UI passes do not hammer allocation/storage while the checkpoint is pending.
for failure in ('alloc','open','write','close','rename'):
    m=PlaybackMachine(); m.options(4,5,0)
    previous=m.files['/mnt/data/ringnav-queue']; m.advance_song(0)
    m.fail=failure; m.fn('playback_poll')
    attempts=(m.allocations,m.write_opens)
    assert m.files['/mnt/data/ringnav-queue']==previous
    for delta in (1,100,1000,3000,898):
        m.now+=delta; m.fn('playback_poll')
        assert (m.allocations,m.write_opens)==attempts
    m.fail=''; m.now+=1; m.fn('playback_poll')
    assert m.files['/mnt/data/ringnav-queue']!=previous
    assert struct.unpack_from('<I',m.files['/mnt/data/ringnav-queue'],20)[0]==m.current()
    assert m.allocations==attempts[0]+1 and m.write_opens==attempts[1]+2
    m.fn('playback_save'); assert m.allocations==attempts[0]+1
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
legacy=bytearray(files['/mnt/data/ringnav-queue']); del legacy[56:76]
struct.pack_into('<I',legacy,4,1); struct.pack_into('<I',legacy,8,len(legacy)); snapshot_checksum(legacy)
r=PlaybackMachine({'/mnt/data/ringnav-queue':bytes(legacy)}); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))==want and r.mcl('MCL_TYPE')==0xf001
bad=bytearray(files['/mnt/data/ringnav-queue']); struct.pack_into('<I',bad,56,5); snapshot_checksum(bad)
r=PlaybackMachine({'/mnt/data/ringnav-queue':bytes(bad)}); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))==-1
checks+=1

# List Play stops both Next and natural completion at the selected library queue's end.
# Exercise actual stock loading, restored identity, and switching from advanced repeat.
for cls in (0xf001,0xff10,0xff11):
    for skip in (0,1):
        for automatic in (0,1):
            for count in (1,3):
                for origin in ('fresh','restored','advanced'):
                    m=PlaybackMachine()
                    tracks=[('first','/A/1','Album A',1,1,0,0),
                            ('second','/A/2','Album A',1,2,0,0),
                            ('last','/B/1','Album B',1,1,0,0)][:count]
                    m.install(tracks)
                    q=m.deque(list(m.items(m.get(syms['mcl_pdeqplaylist']))))
                    m.fn('ringnav_load',q,0,cls)
                    if origin!='fresh':
                        m.word(O['MCL_POS'],count-1); m.options(0,5,0)
                        m.fn('ringnav_preload'); assert m.mcl('MCL_PRELOAD')==1
                        if origin=='restored':
                            m.fn('playback_save')
                            m=PlaybackMachine(m.files); m.install(tracks)
                            m.byte(syms['g_memory_play'],2)
                            out=m.deque([])
                            assert m.fn('ringnav_memory',out)==count-1
                            m.fn('ringnav_load',out,count-1,1)
                            m.fn('ringnav_preload'); assert m.mcl('MCL_PRELOAD')==1
                        m.fn('ringnav_mode',0)
                        assert m.mcl('MCL_PRELOAD')==0 and m.mcl('MCL_PREPOS')==-1
                    m.byte(0xa3be53,skip)
                    callback=0x1000020; m.handlers[callback]='p:folder_skip'
                    m.word(0xa3bda8,callback); m.folder_skips=0
                    if origin=='fresh':
                        for at in range(1,count):
                            starts=len(m.starts)
                            assert m.advance_song(automatic)==1 and m.current()==at
                            assert len(m.starts)==starts+1 and m.stops==0
                    q=m.get(syms['mcl_pdeqplaylist'])
                    def identity():
                        rows=m.items(q)
                        return (m.get(syms['mcl_pdeqplaylist']),m.mcl('MCL_TYPE'),
                                m.get(syms['g_memory_info']),list(rows),
                                [bytes(m.u.mem_read(row,0x60)) for row in rows],
                                [[m.text(m.get(row+O[key])) for key in
                                  ('REC_NAME','REC_PATH','REC_ALBUM','REC_ARTIST')] for row in rows])
                    before=identity(); starts=len(m.starts); stops=m.stops
                    assert m.mcl('MCL_TYPE')==cls
                    # Even a pending stale preload must not hand off beyond the boundary.
                    m.word(O['MCL_PRELOAD'],1); m.word(O['MCL_PREPOS'],0); m.word(O['MCL_FD'],9)
                    sent=len(m.sent)
                    for action in (automatic,0,0):
                        result=m.advance_song(action)
                        assert result==-1, (cls,skip,automatic,count,origin,action,result,
                                            m.mcl('MCL_MODE'),m.current(),len(m.items(q)))
                        stops+=1
                        assert m.stops==stops and len(m.starts)==starts
                        assert m.current()==count-1 and m.folder_skips==0
                        assert m.mcl('MCL_PRELOAD')==0 and m.mcl('MCL_PREPOS')==-1
                        assert identity()==before
                    assert m.sent[sent:]==[(9,b'{mcl-closegapless\\null}',23,0)]
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

# Boot applies the saved stock mode before restoring the queue, then again when hciplayer
# connects. Execute config_init's actual call site: neither startup call is a mode choice.
for folder in (0,1):
    for mode in range(4):
        m=PlaybackMachine()
        assert m.fn('playback_groups',m.deque(list(m.items(m.get(syms['mcl_pdeqplaylist'])))),folder)==1
        m.advance_song(); m.fn('ringnav_savequeue'); want=m.sequence()
        r=PlaybackMachine(m.files); r.byte(syms['g_memory_play'],2); out=r.deque([])
        r.handlers.pop(syms['config_playmode'],None)
        r.u.reg_write(UC_MIPS_REG_GP,0xa26cc0)
        r.u.reg_write(UC_MIPS_REG_SP,0x7000f000)
        r.u.reg_write(UC_MIPS_REG_V0,mode)
        r.u.reg_write(UC_MIPS_REG_A1,0)
        r.u.emu_start(0x4f9998,0x4f99a4,count=r.budget)
        assert r.u.reg_read(UC_MIPS_REG_PC)==0x4f99a4
        assert r.mcl('MCL_MODE')==mode
        assert r.files['/mnt/data/ringnav-queue']==m.files['/mnt/data/ringnav-queue']
        at=r.fn('ringnav_memory',out); assert at==want[0] and r.seek==37
        r.fn('ringnav_load',out,at,0xf001)
        r.call(address=0x513374,args=(0,0,0,0),gap=0) # player_initconfig
        assert '/mnt/data/ringnav-queue' in r.files and r.sequence()==want
        # A real mode choice still clears the snapshot after startup.
        r.call(address=syms['config_playmode'],args=(mode,0,0,0),gap=0)
        assert '/mnt/data/ringnav-queue' not in r.files
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
# Capacity: a scan's 65,000 songs fit QUEUE_LIMIT (65,536); one occurrence past it stays a stock queue.
# ponytail: the 65,000 side (sorts and snapshot) takes minutes under emulation, so it is run by hand.
m=PlaybackMachine(); m.u.mem_map(0x1200000,0x1000000); q=m.get(syms['mcl_pdeqplaylist'])
m.deqs[q][1]=[m.song('t')]*65537
assert m.fn('playback_set',0,1)==0 and m.fn('playback_successor',1)==-1; checks+=1

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
item=m.nodes[view]['children'][-1]; button,=m.nodes[item]['children']
label=m.nodes[button]['children'][1]
assert m.nodes[label]['text']=='Wheel sensitivity: 100%'
assert not any(n.get('type')=='slider' for n in m.nodes.values())
f,ctx=m.handler(button,O['EVT_CLICK'])
def open_wheel():
    m.call(address=f,args=(ctx,m.event,0,0),gap=0)
    m.advance(0,clear=False)
    assert m.labels()==[f'{v}%' for v in range(50,201,10)]
    assert any(n.get('image')=='select' for n in m.nodes.values())
open_wheel()
m.pick(10)
assert m.top==m.stack[0] and m.fn('wheel_value')==150
assert m.nodes[label]['text']=='Wheel sensitivity: 150%'
open_wheel()
dialog=m.top
back,owner=m.handler(dialog,O['EVT_KEY_UP'])
m.word(m.event+O['EVENT_TYPE'],O['EVT_KEY_UP']); m.word(m.event+O['EVENT_KEY'],O['KEY_RETURN'])
m.call(address=back,args=(owner,m.event,0,0),event_type=O['EVT_KEY_UP'],key=O['KEY_RETURN'],gap=0)
assert m.top==m.stack[0] and m.fn('wheel_value')==150
open_wheel()
arrow=m.back
back,owner=m.handler(arrow,O['EVT_CLICK'])
m.call(address=back,args=(owner,m.event,0,0),event_type=O['EVT_CLICK'],gap=0)
assert m.top==m.stack[0] and m.fn('wheel_value')==150
checks+=1

# At default sensitivity, execute stock's original leaf too, including both wrap directions.
stock=Machine(patched=False); m=PlaybackMachine()
for threshold in (12,24):
    for now in range(200):
        for before in (0,99,100,199):
            want=signed(stock.call(address=syms['get_direction'],args=(now,before,threshold,0),gap=0))
            assert m.fn('ringnav_direction',now,before,threshold)==want
checks+=1

# Manual Next/Prev at the queue ends runs stock player_change_music through ringnav_change. Stock
# keeps Folder Skip's sibling folder for class 1; other classes stop at the end (Next) or wrap (Prev); advanced
# playback takes mclNextSong/mclPrevSong, then restores MCL_MODE and Folder Skip. Its tail notifications are mocked.
class ChangeMachine(PlaybackMachine):
    TAIL=('strncmp@GLIBC_2.0','strcpy@GLIBC_2.0','toolsCheckMount','config_outputchannel','toolsLoadNextDir',
          'toolsLoadPrevDir','player_refresh_playqueue','mclSetPlayPos','player_get_id3info','notifyPlayStatus',
          'dmrNotifyPlayStatus','sendBtHeadsetPlayStatus','notifyPlayInfo','sendBtHeadsetPlayInfo',
          'notifyRefreshLyric','dlnaRenderSaveUrlMetadata','reset_repeatinfo','initializeDmrQCurrentInfo')
    def __init__(self):
        super().__init__(); self.seen=[]
        for n in self.TAIL: self.handlers[syms[n]]='x:'+n.split('@')[0]
    def hook(self,u,address,size,unused):
        if address in (syms['mclNextSong'],syms['mclPrevSong']): self.seen.append(self.handlers.get(address,'mcl'))
        name=self.handlers.get(address,'')
        if not name.startswith('x:'): return super().hook(u,address,size,unused)
        name=name[2:]; a=u.reg_read(REGS[0]); self.seen.append((name,a) if name=='mclSetPlayPos' else name)
        ret=1 if name in ('toolsCheckMount','toolsLoadNextDir','toolsLoadPrevDir','player_refresh_playqueue') else 0
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T8,UC_MIPS_REG_T9]: u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret); u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
for nxt,pos,wrap,folder in ((1,6,0,'toolsLoadNextDir'),(0,0,6,'toolsLoadPrevDir')):
    for active in (0,1):
        for cls in (1,0xff10,0xf001):
            m=ChangeMachine()
            if active: m.options(0,2,0); want=m.fn('playback_successor',0) if nxt else None
            m.word(O['MCL_TYPE'],cls); m.word(O['MCL_POS'],pos); m.word(O['MCL_MODE'],0); m.byte(O['MCL_JUMPFOLDER'],1)
            stop=not active and nxt and cls!=1 # List Play stops a library queue's manual Next at its end
            assert signed(m.call(address=syms['player_change_music'],args=(nxt,0,0,0),gap=0))==(0 if stop else 1)
            if active:
                assert 'mcl' in m.seen and folder not in m.seen and not any(type(e) is tuple for e in m.seen), m.seen
                assert m.mcl('MCL_MODE')==0 and m.u.mem_read(O['MCL_JUMPFOLDER'],1)==b'\1'
                assert not nxt or m.current()==want
            elif cls==1: assert folder in m.seen, m.seen
            elif stop: assert m.stops==1 and folder not in m.seen and not any(type(e) is tuple for e in m.seen), m.seen
            else: assert folder not in m.seen and ('mclSetPlayPos',wrap) in m.seen, m.seen
            checks+=1

print(f'{checks} advanced playback/wheel MIPS checks passed ({variant})')

# Elapsed checkpoints are fixed-size, atomic, and tied to both snapshot and position.
m=PlaybackMachine(); m.options(0,5,0)
full=m.files['/mnt/data/ringnav-queue']; m.elapsed=52; m.fn('playback_save')
checkpoint=m.files['/mnt/data/ringnav-queue-elapsed']
assert len(checkpoint)==40 and m.files['/mnt/data/ringnav-queue']==full
for failure in ('open','write','close','rename'):
    m.fail=failure; m.elapsed=53; m.fn('playback_save')
    assert m.files['/mnt/data/ringnav-queue-elapsed']==checkpoint
m.fail=''; m.fn('playback_save')
for kind in ('valid','truncated','extra','checksum','identity','position','version','size'):
    c=bytearray(checkpoint)
    if kind=='truncated': c=c[:-1]
    elif kind=='extra': c+=b'x'
    elif kind=='checksum': c[-1]^=1
    elif kind in ('identity','position','version','size'):
        offset={'identity':16,'position':32,'version':4,'size':8}[kind]
        struct.pack_into('<I',c,offset,999); snapshot_checksum(c)
    r=PlaybackMachine({'/mnt/data/ringnav-queue':full,'/mnt/data/ringnav-queue-elapsed':bytes(c)})
    r.byte(syms['g_memory_play'],2)
    assert r.fn('ringnav_memory',r.deque([]))>=0 and r.seek==(52 if kind=='valid' else 37),kind
# Interrupted full-snapshot publication leaves an old checkpoint harmless.
stale=bytearray(checkpoint); stale[16]^=1; snapshot_checksum(stale)
r=PlaybackMachine({'/mnt/data/ringnav-queue':full,'/mnt/data/ringnav-queue-elapsed':bytes(stale)})
r.byte(syms['g_memory_play'],2); assert r.fn('ringnav_memory',r.deque([]))>=0 and r.seek==37
# Identity generation failure leaves the previous snapshot committed and retries later.
m=PlaybackMachine(); m.options(0,5,0); previous=m.files['/mnt/data/ringnav-queue']
m.files['/dev/urandom']=b''; m.advance_song(); m.fn('playback_save')
assert m.files['/mnt/data/ringnav-queue']==previous
m.files['/dev/urandom']=bytes(range(16)); m.fn('playback_save')
assert m.files['/mnt/data/ringnav-queue']!=previous
# V2 remains readable too.
v2=bytearray(full); del v2[60:76]
struct.pack_into('<I',v2,4,2); struct.pack_into('<I',v2,8,len(v2)); snapshot_checksum(v2)
r=PlaybackMachine({'/mnt/data/ringnav-queue':bytes(v2)}); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))>=0 and r.seek==37
# Measure actual payload instructions: even exhausted/category-repeat scans occur only once.
for n in (8,128):
    for repeat in (1,4):
        m=PlaybackMachine(); m.budget=2000000
        m.install([(str(i),'/a/'+str(i),'A' if i==0 else 'B',0,i,0,0) for i in range(n)],0)
        m.options(0,repeat,0)
        cost=[0]; visits=[0]
        # playback's private o32 layout: order/cycle pointers follow 27 words of scalar state.
        tables=[m.get(ps['s']+108),m.get(ps['s']+112)]
        def count_traversal(u,access,address,size,value,unused):
            if any(start<=address<start+n*12 for start in tables): visits[0]+=1
        read_hook=m.u.hook_add(UC_HOOK_MEM_READ,count_traversal)
        def count_payload(*args): cost[0]+=1
        hook=m.u.hook_add(UC_HOOK_CODE,count_payload,begin=BASE,end=SCRATCH-1)
        expected=m.fn('playback_successor',0); uncached=cost[0]; scanned=visits[0]; cost[0]=0
        assert m.fn('playback_successor',1)==expected
        cold=cost[0]; cost[0]=0; visits[0]=0
        for _ in range(10): m.fn('playback_successor',1)
        warm=cost[0]//10; m.u.hook_del(hook)
        for _ in range(10): m.fn('playback_poll')
        m.u.hook_del(read_hook)
        assert scanned>=n-1 and visits[0]==0
        assert warm<100 and cold>=warm
        full_bytes=len(m.files['/mnt/data/ringnav-queue']); m.elapsed+=5; m.fn('playback_save')
        assert len(m.files['/mnt/data/ringnav-queue-elapsed'])==40
        print(f'queue={n} repeat={repeat}: successor uncached={uncached}, cold={cold}, cached={warm} instructions, traversal reads {scanned} -> 0; elapsed save {full_bytes-16} (v2 full) -> 40 bytes')
print('Checkpoint and polling performance checks passed')

# A checkpoint publication failure after full commit retries without rewriting the queue.
m=PlaybackMachine(); m.options(0,5,0)
old_checkpoint=m.files['/mnt/data/ringnav-queue-elapsed']
m.advance_song(); m.elapsed=49; m.fail='checkpoint-rename'; m.fn('playback_save')
committed=m.files['/mnt/data/ringnav-queue']; writes=m.write_opens
assert m.files['/mnt/data/ringnav-queue-elapsed']==old_checkpoint
r=PlaybackMachine(m.files); r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))==m.current() and r.seek==49
m.fail=''; m.fn('playback_save')
assert m.files['/mnt/data/ringnav-queue']==committed and m.write_opens==writes+1
assert m.files['/mnt/data/ringnav-queue-elapsed']!=old_checkpoint

# Uncommitted checkpoint temporaries never override the committed full snapshot.
r=PlaybackMachine({'/mnt/data/ringnav-queue':full,'/mnt/data/ringnav-queue-elapsed.tmp':checkpoint})
r.byte(syms['g_memory_play'],2)
assert r.fn('ringnav_memory',r.deque([]))>=0 and r.seek==37
