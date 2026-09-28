#!/usr/bin/env python3
"""Execute the actual patched MIPS callback with stock filter and mocked UI services.
Requires unicorn==2.1.4. Does not emulate the entire device or flash hardware.
"""
import re, json, pathlib, struct, sys
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from build import segments, symbols, HOOK, HOOKS, FUNCTIONS, GLOBALS
B=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'build')
manifest=json.loads((B/'manifest.json').read_text())
syms=symbols(B/'stock-demo')
IPOD=manifest.get('ipod',False)  # iPod rows replace the outline with styled rows
DUMP=bool(manifest.get('dump'))
INSET=manifest.get('row_inset',0)
ACCEL=manifest.get('accel',False)
REGS=[UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3]
SAVED=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,
       UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP]

def signed(x): return x if x<0x80000000 else x-0x100000000

def rect_(m,a,r):
    for j,v in enumerate(r): m.word(a+4*j,v)

class Machine:
    def __init__(self, patched=True):
        self.u=Uc(UC_ARCH_MIPS, UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        data=(B/('demo' if patched else 'stock-demo')).read_bytes()
        for _,(t,o,v,_,f,m,flags,_) in segments(data):
            if t!=1: continue
            start=v&~4095; end=(v+m+4095)&~4095
            self.u.mem_map(start,end-start)
            self.u.mem_write(v,data[o:o+f])
            # Payload text is execute-only; its top page holds the scratch cell.
            if v==0xb00000: self.u.mem_protect(start,((v+f+4095)&~4095)-start,5)
        self.u.mem_map(0x1000000,0x200000)
        self.u.mem_map(0x70000000,0x10000)
        self.next=0x1001000; self.nodes={}; self.calls=[]; self.animating=0; self.pressed=0
        self.top=0; self.wm=0x1000000; self.event=0x1000100
        self.strokes=[]; self.rebind=None; self.on_click=None; self.glide=True
        self.canvas=0x1000200; self.lcd=0x1000300; self.now=1000; self.np_pos=0; self.np_n=0; self.playtime=0; self.scrolls=[]; self.unloaded=[]; self.layouts=[]; self.btvols=[]; self.bt_abs=0xff; self.bt_sets=[]; self.closed=[]; self.bt_links=[]; self.bt_pairs=[]; self.threads=[]; self.sent=[]; self.rx=[]; self.socks_closed=[]; self.selects=0; self.inputs={}; self.opened=[]; self.volsets=[]; self.navs=[]; self.style_color=None; self.grad=[]; self.imgadds=[]; self.unloads=0; self.ons=[]; self.evq=[]; self.queued=[]; self.player=[]; self.inputs_closed=[]; self.link_left=None; self.play_status=2; self.toggles=0; self.cover_ready=set(); self.big_ready=set(); self.cover_asks=[]
        self.nodes[self.wm]=dict(type='window_manager',children=[]); self.timers={}; self.timer_ids=0; self.idles=[]; self.bitmaps={}; self.vg=[]; self.fills=[]; self.fill=0; self.on_load=None; self.loaddata=None; self.dir_items=[]; self.files={}
        self.word(self.canvas+0x38,self.lcd)
        self.word(self.lcd+0xc0,0x12345678)
        self.clip=(0,0,240,240)
        self.handlers={}
        for name in FUNCTIONS: self.handlers[syms[name]]=name
        if patched:
            for name in ('paint','dispatch')+(('rowh','loaddata','prepare','scrollto','layout','btvol','stylecolor','imgadd') if IPOD else ()):
                self.handlers[int(manifest['patch_symbols']['stock_'+name+'_trampoline'],16)]='stock_'+name
        self.handlers[syms['reset_poweroptions_timer']]='reset_poweroptions_timer'
        self.handlers[0x1000840]='fake_get_gradient'  # a style's get_gradient (vtable +0x18)
        self.handlers[syms['memcpy@GLIBC_2.0']]='memcpy'
        for k in syms:  # libc calls made by the patch (AirPods battery thread)
            if '@' in k and k.split('@')[0] in ('socket','connect','send','recv','select','close','usleep','__errno_location','pthread_create','pthread_detach','ioctl','open','read'):
                self.handlers[syms[k]]=k.split('@')[0]
        self.handlers[syms['memset@GLIBC_2.0']]='memset'
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        for name in GLOBALS: self.byte(syms[name],0)
        self.byte(syms['g_backlight_status'],1)
    def byte(self,a,v): self.u.mem_write(a,bytes([v]))
    def word(self,a,v): self.u.mem_write(a,struct.pack('<I',v&0xffffffff))
    def get(self,a): return struct.unpack('<I',self.u.mem_read(a,4))[0]
    def alloc(self,n=0x200): a=self.next; self.next+=n; return a
    def string(self,s):
        a=self.alloc((len(s)+4)&~3); self.u.mem_write(a,s.encode()+b'\0'); return a
    def text(self,a):
        if not a: return ''
        out=bytearray()
        while (c:=self.u.mem_read(a,1))!=b'\0': out+=c; a+=1
        return out.decode()
    def node(self,t='scroll_view',name='',children=(),visible=1,enable=1,**kw):
        a=self.alloc(); self.nodes[a]=dict(type=t,name=name,children=list(children),visible=visible,enable=enable,**kw)
        self.word(a+8,240); self.word(a+0x0c,240); self.word(a+0x78,48); self.word(a+0x7c,960 if t=='scroll_view' else 100)
        self.byte(a+0x91,1)
        return a
    def entry(self,parent,y=0,index=None,t='list_item'):
        """A leafless tap target: emitter with one EVT_CLICK item, widget_y offset y, height 48."""
        a=self.node(t)
        em=self.alloc(4); it=self.alloc(0x28)
        self.word(a+0x60,em); self.word(em,it); self.word(it+8,0x10c)
        self.word(a+0x48,parent); self.word(a+0x04,y); self.word(a+0x0c,48)
        if index is not None: self.word(a+0x78,index)
        return a
    def selected(self,w): return self.nodes[w].get('_ringnav_index',-1)
    def paint(self,w): return self.call(address=HOOKS['widget_on_paint_border'][0],args=(w,self.canvas,0,0))
    def touch(self): return self.call(address=HOOKS['on_wm_tsdown_before_fun'][0])
    def click(self,w): return self.call(address=HOOKS['widget_dispatch'][0],args=(w,self.event,0,0),event_type=0x10c)
    def hook(self,u,address,size,_):
        if address not in self.handlers: return
        name=self.handlers[address]
        if not name.startswith('stock_'):
            assert u.reg_read(UC_MIPS_REG_T9)==address, (name,'PIC call missing t9')
        a,b,c,d=[u.reg_read(r) for r in REGS]
        n=self.nodes.get(a,{})
        self.calls.append((name,a,b,c))
        if name=='memcpy': self.u.mem_write(a,bytes(self.u.mem_read(b,c))); ret=a
        elif name=='memset': self.u.mem_write(a,bytes([b&255])*c); ret=a
        elif name=='window_manager': ret=self.wm
        elif name=='window_manager_get_top_window': ret=self.top
        elif name=='window_manager_is_animating': ret=self.animating
        elif name=='window_manager_get_pointer_pressed': ret=self.pressed
        elif name=='widget_get_visible': ret=n.get('visible',0)
        elif name=='widget_get_type': ret=self.string(n.get('type',''))
        elif name=='widget_get_prop_str': ret=self.string(n.get(self.text(b),''))
        elif name in ('widget_get_prop_bool','widget_get_prop_int'): ret=n.get(self.text(b),c)
        elif name=='widget_count_children': ret=len(n['children'])
        elif name=='widget_get_child': ret=n['children'][b] if b<len(n['children']) else 0
        elif name=='widget_set_prop_int': n[self.text(b)]=signed(c); ret=0
        elif name=='pointer_event_init':
            self.word(a,b); self.word(a+0x10,c); ret=a
        elif name=='time_now_ms': ret=self.now
        elif name=='mclGetPlayPos': ret=self.np_pos
        elif name=='mclGetPlayStatus': ret=self.play_status
        elif name=='player_play_pause': self.toggles+=1; self.play_status={2:3,3:2}.get(self.play_status,self.play_status); ret=1
        elif name=='player_playtime': ret=self.playtime
        elif name=='check_albumcover_flag': ret=int(a in (self.cover_ready if b==0 else self.big_ready))
        elif name=='local_albumsmallcover_task': self.cover_asks.append((signed(a),b)); ret=0
        elif name=='local_albumcover_task': self.cover_asks.append(('big',signed(a),b)); ret=0
        elif name=='image_manager': ret=0x1000900
        elif name=='image_manager_unload_bitmap_by_name': assert a==0x1000900; self.unloaded.append(self.text(b)); ret=0
        elif name=='stock_scrollto': self.scrolls.append((a,signed(b),signed(c),signed(d))); ret=0
        elif name=='deque_size': ret=self.np_n if a==0x1234 else len(self.bt_pairs)
        elif name=='tk_snprintf':  # %s %u %d and %*s: enough for the debug logs
            sp=u.reg_read(UC_MIPS_REG_SP); argv=iter([d]+[self.get(sp+16+4*k) for k in range(24)])
            def conv(mt):
                flags,spec=mt.group(1) or '',mt.group(2)
                if spec=='%': return '%'
                w=next(argv) if flags=='*' else int(flags) if flags else 0
                v=next(argv)
                txt=self.text(v) if spec=='s' else '%x'%v if spec=='x' else str(signed(v) if spec=='d' else v)
                return txt.zfill(w) if flags.startswith('0') and spec!='s' else txt.rjust(w)
            out=re.sub(r'%(\*|\d+)?([sudx%])',conv,self.text(c)).encode()[:max(b-1,0)]
            self.u.mem_write(a,out+b'\0'); ret=len(out)
        elif name=='file_write': self.files[self.text(a)]=bytes(self.u.mem_read(b,c)).decode(); ret=0
        elif name=='stock_layout': self.layouts.append(a); ret=0
        elif name=='stock_btvol': self.btvols.append((signed(a),signed(b))); ret=0
        elif name=='btctl_transport_get_volume': ret=self.bt_abs
        elif name in ('popup_create','image_create','label_create','list_item_create','button_create','hscroll_label_create',
                      'window_create','list_view_create','scroll_view_create'):
            t={'popup_create':'popup','image_create':'image','label_create':'label','list_item_create':'list_item',
               'button_create':'button','hscroll_label_create':'hscroll_label','window_create':'window',
               'list_view_create':'list_view','scroll_view_create':'scroll_view'}[name]
            w_=self.node(t); self.word(w_+0x48,a); rect_(self,w_,(signed(b),signed(c),signed(d),self.get(u.reg_read(UC_MIPS_REG_SP)+16)))
            (self.nodes[self.wm] if not a else self.nodes[a])['children'].append(w_); ret=w_
        elif name=='image_base_set_image': n['image']=self.text(b); ret=0
        elif name=='widget_set_text_utf8': n['wtext']=self.text(b); ret=0
        elif name=='window_close': self.closed.append(a); self.nodes[self.wm]['children'].remove(a); ret=0
        elif name=='pthread_create': self.threads.append(c); self.word(a,0x7777); ret=0
        elif name=='pthread_detach': ret=0
        elif name=='usleep': ret=0
        elif name=='socket': self.sock=(a,b,c); ret=7
        elif name=='open': ret=self.inputs.get(self.text(a),(-1,''))[0]; self.opened.append(self.text(a))
        elif name=='ioctl' and b==0x40404506:  # EVIOCGNAME(64)
            nm=next((n for f,n in self.inputs.values() if f==a),'').encode()+b'\0'; self.u.mem_write(c,nm); ret=len(nm)
        elif name=='read':
            if self.evq: pk=self.evq.pop(0); self.u.mem_write(b,pk); ret=len(pk)
            else: self.byte(syms['bt_linkstatus'],0); ret=-1  # the headset went: the device is gone
        elif name=='idle_queue': self.queued.append(a); ret=0
        elif name=='player_next_music': self.player.append('next'); ret=0
        elif name=='device_set_volume': self.volsets.append((a,b)); ret=0
        elif name=='stock_stylecolor': self.word(a,self.style_color if self.style_color is not None else d); ret=a
        elif name=='stock_imgadd': self.imgadds.append((self.text(b),c)); ret=0
        elif name=='bitmap_lock_buffer_for_write': ret=self.get(a+20)
        elif name=='bitmap_unlock_buffer': ret=0
        elif name=='file_read':
            if self.text(a) in self.files:
                data=self.files[self.text(a)].encode(); buf=self.alloc(len(data)+1); self.u.mem_write(buf,data)
                if b: self.word(b,len(data))
                ret=buf
            else: ret=0
        elif name=='tk_free': ret=0
        elif name=='fake_get_gradient':
            if self.grad is None: ret=0x1000860  # from somewhere else: not the caller's copy
            else:
                self.word(c+8,len(self.grad)); [self.word(c+0xc+8*i,col) for i,col in enumerate(self.grad)]; ret=c
        elif name=='image_manager_unload_all': self.unloads+=1; ret=0
        elif name=='widget_on': self.ons.append((a,b,c,d)); ret=1
        elif name=='navigator_to': self.navs.append(self.text(a)); ret=0
        elif name=='player_prev_music': self.player.append('prev'); ret=0
        elif name=='player_start': self.player.append(('start',a,b,c,d)); ret=0
        elif name=='connect': self.sock_addr=bytes(self.u.mem_read(b,c)); ret=0
        elif name=='send': self.sent.append(bytes(self.u.mem_read(b,c))); ret=c
        elif name=='select':  # a 1 s timeout when nothing arrives; link_left: idle seconds until the link drops
            self.selects+=1; ret=1 if self.rx else 0
            if not self.rx:
                self.now+=1000
                if self.link_left is not None:
                    self.link_left-=1
                    if self.link_left<=0: self.byte(syms['bt_linkstatus'],0)
        elif name=='recv':
            pk=self.rx.pop(0) if self.rx else b''
            if not self.rx: self.byte(syms['bt_linkstatus'],0)  # the headset goes away after the last packet
            self.u.mem_write(b,pk); ret=len(pk)
        elif name=='close' and a>=30: self.inputs_closed.append(a); ret=0
        elif name=='close': self.socks_closed.append(a); ret=0
        elif name=='__errno_location': ret=0x1000a00
        elif name=='getBtLinkSize': ret=len(self.bt_links)
        elif name=='getBtLinkItem':
            st,mac=self.bt_links[a]; self.word(b,st); self.u.mem_write(c,mac.encode()+b'\0'); ret=0
        elif name=='deque_at': ret=self.bt_pairs[b]
        elif name=='btctl_transport_set_volume': self.bt_sets.append(signed(a)); self.bt_abs=signed(a); ret=0
        elif name=='widget_move_resize':
            for j,v in enumerate((b,c,d,self.get(u.reg_read(UC_MIPS_REG_SP)+16))): self.word(a+4*j,v)
            ret=0
        elif name=='widget_use_style': n['style']=self.text(b); ret=0
        elif name=='idle_add': self.idles.append(a); ret=len(self.idles)
        elif name=='widget_get_text':
            t=n.get('wtext'); ret=0
            if t is not None:
                ret=self.alloc(4*len(t)+8); self.u.mem_write(ret,b''.join(struct.pack('<I',ord(ch)) for ch in t)+b'\0'*4)
        elif name=='widget_set_text':
            out=''; q=b
            while (ch:=self.get(q)): out+=chr(ch); q+=4
            n['wtext']=out; ret=0
        elif name=='widget_load_image':
            img=self.text(b); ret=1  # the name asked for, not the widget's own image
            if img and img in self.bitmaps:
                self.word(c,self.bitmaps[img][0]); self.word(c+4,self.bitmaps[img][1]); ret=0
        elif name=='canvas_get_vgcanvas': ret=0x1000500
        elif name=='canvas_set_fill_color': self.fill=b; ret=0
        elif name=='canvas_fill_rect':
            self.fills.append((signed(b),signed(c),signed(d),signed(self.get(u.reg_read(UC_MIPS_REG_SP)+16)),self.fill)); ret=0
        elif name.startswith('vgcanvas_'):
            f=lambda v: struct.unpack('<f',struct.pack('<I',v&0xffffffff))[0]
            sp=u.reg_read(UC_MIPS_REG_SP)
            args={'vgcanvas_translate':(f(b),f(c)),'vgcanvas_scale':(f(b),f(c)),'vgcanvas_set_global_alpha':(f(b),),
                  'vgcanvas_rounded_rect':(f(b),f(c),f(d),f(self.get(sp+16)),f(self.get(sp+20))),
                  'vgcanvas_paint':(b,c),'vgcanvas_set_fill_color':(b,)}.get(name,())
            self.vg.append((name,)+tuple(round(x,3) if isinstance(x,float) else x for x in args)); ret=0
        elif name=='widget_lookup':  # a named descendant of a (pre-order), as AWTK searches
            want=self.text(b)
            def find(w):
                for ch in self.nodes.get(w,{}).get('children',[]):
                    if self.nodes.get(ch,{}).get('name')==want: return ch
                    f=find(ch)
                    if f: return f
                return 0
            ret=find(a)
        elif name=='widget_set_prop_str': n[self.text(b)]=self.text(c); ret=0
        elif name=='timer_add' and c==2000: ret=0xd0d0  # debug dump timer (--dump builds only)
        elif name=='timer_add' and c==800: self.letter_timer=a; ret=0x1e77  # fast-scroll letter hide
        elif name=='timer_add' and c==120: self.np_timer=a; ret=0x0b0b  # now-playing bars tick
        elif name=='timer_add' and c==80: self.home_timer=a; ret=0x0a0a  # home art pan tick
        elif name=='timer_add' and c==200: self.cover_timer=a; ret=0x0c0c  # album cover re-bind tick
        elif name=='timer_add' and c==400: self.bt_poll=a; ret=0x0b70  # headset connect poll
        elif name=='timer_add' and c==300: self.card_tick=a; ret=0x0cc3  # connect card: battery text, auto-close
        elif name=='os_fs': ret=0x1000600
        elif name=='fs_open_dir': self.dir_left=list(self.dir_items); ret=0x1000700 if self.text(b)=='/mnt/mmc/.sldp' else 0
        elif name=='fs_dir_read':
            ret=1
            if self.dir_left:
                nm,reg=self.dir_left.pop(0); self.u.mem_write(b,bytes([0,0,reg])+nm.encode()+b'\0'); ret=0
        elif name=='fs_dir_close': ret=0
        elif name=='timer_remove' and a==0x1e77: ret=0
        elif name=='timer_remove' and a==0xd0d0: ret=0
        elif name=='timer_add':
            assert c==250; self.timer_ids+=1; self.timers[self.timer_ids]=(a,b); ret=self.timer_ids
        elif name=='timer_remove': assert a in self.timers; del self.timers[a]; ret=0
        elif name=='stock_loaddata': self.loaddata=(a,b,c); ret=0
        elif name=='app_load':  # the page's own row binder: restores its stock card, as on play/pause
            if self.on_load: self.on_load(a,b,c)
            ret=0
        elif name=='stock_dispatch':
            if self.on_click: self.on_click(a,b)
            ret=0
        elif name=='table_client_stop_animator_scroll': self.word(a+0xd0,0); ret=0
        elif name=='table_client_set_yoffset':
            self.word(a+0x80,b)
            if self.rebind: self.rebind(a,b)
            ret=0
        elif name=='canvas_get_clip_rect':
            for j,v in enumerate(self.clip): self.word(b+4*j,v)
            ret=0
        elif name=='canvas_set_clip_rect': self.clip=tuple(signed(self.get(b+4*j)) for j in range(4)); ret=0
        elif name=='canvas_set_stroke_color': self.word(self.lcd+0xc0,b); ret=0
        elif name in ('canvas_stroke_rect','lcd_stroke_rect'):
            h=self.get(u.reg_read(UC_MIPS_REG_SP)+16)
            clip=self.clip if name=='canvas_stroke_rect' else (self.get(self.canvas+0x10),self.get(self.canvas+0x14),self.get(self.canvas+0x18)-self.get(self.canvas+0x10)+1,self.get(self.canvas+0x1c)-self.get(self.canvas+0x14)+1)
            self.strokes.append((signed(b),signed(c),signed(d),signed(h),clip,self.get(self.lcd+0xc0))); ret=0
        elif name=='scroll_view_scroll_delta_to':
            if self.glide:
                self.word(a+0x80,self.get(a+0x80)+b); self.word(a+0x84,self.get(a+0x84)+c)
            else: self.word(a+0xe8,0x1234)
            ret=0
        else: ret=0
        # Clobber caller-saved registers to catch accidental ABI assumptions.
        for r in [UC_MIPS_REG_V1,*REGS,UC_MIPS_REG_T0,UC_MIPS_REG_T1,UC_MIPS_REG_T2,
                  UC_MIPS_REG_T3,UC_MIPS_REG_T4,UC_MIPS_REG_T5,UC_MIPS_REG_T6,
                  UC_MIPS_REG_T7,UC_MIPS_REG_T8,UC_MIPS_REG_T9]:
            u.reg_write(r,0xdeadbeef)
        u.reg_write(UC_MIPS_REG_V0,ret&0xffffffff)
        u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
    def call(self,key=173,address=HOOK,args=None,event_type=0x114,gap=1000,fire=True):
        # By default a centre click's double-press window closes before the next input step.
        ret=self.run(key,address,args,event_type,gap)
        if fire and self.timers:
            calls=self.calls; ret2=self.expire(); self.calls=calls+self.calls
        return ret
    def idle(self):
        # Run queued idle callbacks as the main loop does after the frame; returns their calls.
        calls=[]
        while self.idles:
            cb=self.idles.pop(0); assert self.run(0,cb,(0x1000400,0,0,0),0x114,0)==7; calls+=self.calls
        return calls
    def expire(self):
        # Fire the pending click timer as the main loop would once its 250 ms elapse.
        (tid,(cb,ctx)),=self.timers.items(); del self.timers[tid]
        ret=self.run(0,cb,(0x1000400,0,0,0),0x114,250)
        assert ret==7, 'Timer must remove itself'
        return ret
    def run(self,key,address,args,event_type,gap):
        # Independent input steps occur after the stock key debounce timer expires.
        self.now+=gap
        self.byte(0xa37c89,0)
        self.calls=[]; self.word(self.event+0x18,key)
        self.word(self.event,event_type)
        self.u.reg_write(UC_MIPS_REG_SP,0x7000f000)
        self.u.reg_write(UC_MIPS_REG_RA,0x1000000)
        self.u.reg_write(UC_MIPS_REG_T9,address)
        for r,v in zip(REGS,args or (self.wm,self.event,0,0)): self.u.reg_write(r,v&0xffffffff)
        for i,r in enumerate(SAVED): self.u.reg_write(r,0x12340000+i)
        self.u.emu_start(address,0x1000000,count=100000)
        assert self.u.reg_read(UC_MIPS_REG_PC)==0x1000000, 'Instruction limit reached'
        assert self.u.reg_read(UC_MIPS_REG_SP)==0x7000f000
        assert [self.u.reg_read(r) for r in SAVED]==[0x12340000+i for i in range(len(SAVED))]
        return signed(self.u.reg_read(UC_MIPS_REG_V0))
    def page(self,name='sysset_page',t='scroll_view'):
        child=self.node(t)
        self.top=self.node('window',name,[child])
        return child
    def moved(self): return [x for x in self.calls if x[0] in ('scroll_view_scroll_delta_to','table_client_set_yoffset','slide_menu_scroll_to_next','slide_menu_scroll_to_prev')]
    def dispatched(self): return [x for x in self.calls if x[0]=='stock_dispatch']

checks=0
def passed():
    global checks
    checks+=1

for t,off in [('scroll_view',0x84),('table_client',0x80)]:
    m=Machine(); w=m.page(t=t)
    for _ in range(20): assert m.call()==11
    assert m.get(w+off)==min(20*manifest['ring_step_pixels'],720 if t=='scroll_view' else 4560)
    assert m.call(172)==11 and m.moved()
    for _ in range(120): m.call(172)
    assert m.get(w+off)==0
    # Empty/short lists consume input without turning into volume changes.
    m.word(w+0x7c,0); assert m.call()==11 and m.get(w+off)==0
    passed()

for name in ['playing_page','volume_dialog','saverscreen_page','usbmode_page','unknown_page','equalizer_page']:
    m=Machine(); m.page(name); assert m.call()==0 and not m.moved(); passed()
for flag,value in [('g_backlight_status',0),('g_lockscreen_pageflag',1),('g_testmode_flag',1),
                   ('g_guideflag',1),('g_poweroff_state',2),('g_usblink_status',2),('bt__recv_pageflag',1)]:
    m=Machine(); m.page(); m.byte(syms[flag],value); assert m.call()==0 and not m.moved(); passed()
for field in ['animating','pressed']:
    m=Machine(); m.page(); setattr(m,field,1); assert m.call()==11 and not m.moved(); passed()

m=Machine(); w=m.page('home_page','slide_menu')
assert m.call()==11 and m.moved()[0][0]=='slide_menu_scroll_to_next'
assert m.call(172)==11 and m.moved()[0][0]=='slide_menu_scroll_to_prev'; passed()
m=Machine(); hidden=m.node(visible=0); shown=m.node(); pages=m.node('pages',children=[hidden,shown],active=1)
m.top=m.node('window','artistinfo_page',[pages]); assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.nodes[hidden]['visible']=1
assert m.call()==11 and m.moved()[0][1]==shown; passed()
m.top=m.node('window','sysset_page',[hidden,shown]); assert m.call()==11 and not m.moved(); passed()
for attribute in ['visible','enable']:
    m=Machine(); w=m.page(); m.nodes[w][attribute]=0; assert m.call()==11 and not m.moved(); passed()
# An in-flight scroll animation is retargeted by the animated glide, not torn down.
m=Machine(); w=m.page(); m.word(w+0x84,100)
assert m.call()==11 and m.moved()[0][0]=='scroll_view_scroll_delta_to' and m.moved()[0][3]==48
assert m.get(w+0x84)==148 and m.get(w+0xe8)==0; passed()

# Painting establishes selection without a sacrificial button press or native focus.
m=Machine(); w=m.page(); m.word(w+0x0c,96); m.word(w+0x7c,1000)
entries=[m.entry(w,i*48) for i in range(5)]; m.nodes[w]['children']=entries
assert m.paint(w)==0 and m.selected(w)==0
assert IPOD or (m.strokes[0][:4]==(1,1,238,46) and m.strokes[0][5]==int(manifest['ring_color'],16))
assert m.clip==(0,0,240,240) and m.get(m.lcd+0xc0)==0x12345678
assert not any(m.get(e+0x24)&0x80 for e in entries); passed()
assert m.call(218)==11 and m.dispatched()[0][1]==entries[0]; passed()
assert m.call()==11 and m.selected(w)==1 and not m.moved()
assert m.call()==11 and m.selected(w)==2 and m.get(w+0x84)==48
assert m.call(218)==11 and m.dispatched()[0][1]==entries[2]; passed()
# The separate Play/Pause key remains native even with an active selection.
assert m.call(171)==0 and not m.dispatched(); passed()
# Touching a different row selects it before the native callback runs; no extra click.
assert m.touch()==0
m.on_click=lambda a,b: (None if m.selected(w)==1 else (_ for _ in ()).throw(AssertionError('late selection')))
assert m.click(entries[1])==0 and len(m.dispatched())==1 and m.selected(w)==1
m.on_click=None
assert m.call(218)==11 and m.dispatched()[0][1]==entries[1]; passed()
# Native touch focus may move anywhere without altering the logical selection.
m.word(entries[4]+0x24,0x80)
assert m.call(218)==11 and m.dispatched()[0][1]==entries[1]; passed()
# Swipe preserves selection during momentum; settle chooses the first FULLY visible row.
m.touch(); m.word(w+0x84,110); m.word(w+0xe8,0x1234)
m.paint(w); assert m.selected(w)==1
m.word(w+0xe8,0); m.paint(w); assert m.selected(w)==3
assert m.call(218)==11 and m.dispatched()[0][1]==entries[3]; passed()
# Wheel interrupts touch momentum, and centre while a finger is down is consumed without a click.
m.touch(); m.word(w+0xe8,0x1234)
assert m.call(172)==11 and m.get(w+0xe8)==0 and m.selected(w)==2
m.pressed=1
assert m.call(218)==11 and not m.dispatched()
assert m.call()==11 and m.selected(w)==2
m.pressed=0; passed()
# Native click may destroy the current page. Nothing dereferences its target afterwards.
def destroy(a,b):
    m.nodes.clear(); m.top=0
m.on_click=destroy
assert m.call(218)==11 and len(m.dispatched())==1; passed()

# Recycle a small row pool: selection belongs to the logical index, never the widget.
m=Machine(); w=m.page('allmusic_page','table_client')
m.word(w+0x78,48); m.word(w+0x7c,20); m.word(w+0x0c,96)
rows=[m.node('table_row') for _ in range(4)]
entries=[m.entry(r) for r in rows]; m.nodes[w]['children']=rows
for r,e in zip(rows,entries): m.nodes[r]['children']=[e]; m.word(r+0x48,w)
def rebind(a,offset):
    start=offset//48
    for j,r in enumerate(rows):
        m.word(r+0x78,start+j); m.word(r+4,(start+j)*48)
m.rebind=rebind; rebind(w,0)
m.paint(w); assert m.selected(w)==0
assert m.call()==11 and m.selected(w)==1
assert m.call()==11 and m.selected(w)==2 and m.get(w+0x80)==48
assert m.call(218)==11 and m.dispatched()[0][1]==entries[1]; passed()
# A touch click in a rebound row immediately changes what centre opens.
m.touch(); m.click(entries[0]); assert m.selected(w)==1
assert m.call(218)==11 and m.dispatched()[0][1]==entries[0]; passed()
# Swipe out of the old pool, then centre: settle/re-resolve before dispatch.
m.touch(); m.word(w+0x80,480); rebind(w,480); m.word(w+0xd0,0x9876)
assert m.call(218)==11 and m.selected(w)==10 and m.dispatched()[0][1]==entries[0]
assert m.get(w+0xd0)==0; passed()
# Returning to a surviving menu keeps a valid selection; shrinking data repairs it.
oldtop=m.top; m.page('playing_page'); assert m.call(218)==0
m.top=oldtop; m.paint(w); assert m.selected(w)==10
m.word(w+0x7c,1); m.word(w+0x80,0); rebind(w,0); m.paint(w)
assert m.selected(w)==0; passed()

# Home keeps its native carousel presentation and value (including touch changes).
m=Machine(); w=m.page('home_page','slide_menu'); m.word(w+0x78,1)
child=[m.entry(w),m.entry(w)]; m.nodes[w]['children']=child
assert m.paint(w)==0 and not m.strokes
assert any(c[0]=='stock_paint' for c in m.calls)
assert m.call(218)==11 and m.dispatched()[0][1]==child[1]
m.word(w+0x78,0)
assert m.call(218)==11 and m.dispatched()[0][1]==child[0]; passed()
# Long-press/boot release must reach stock cleanup, never activate a menu item.
for addr in [syms['g_power_longkey'],syms['g_ingore_bootkey_flag'],0xa37c8a]:
    m.byte(addr,1); assert m.call(218)==0 and not m.dispatched(); m.byte(addr,0); passed()
# A quick second centre release reaches stock, whose short press toggles the screen.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and not m.dispatched() and m.timers
assert m.call(218,gap=100)==0 and not m.dispatched() and not m.timers
assert m.call(218,gap=100)==11 and len(m.dispatched())==1; passed()
# The held click opens the entry selected when the window closes, exactly once.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and not m.dispatched()
m.expire(); assert len(m.dispatched())==1 and m.dispatched()[0][1]==es[0] and not m.timers; passed()
# A page change during the window drops the click instead of opening something else.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11
m.page('playing_page'); m.expire(); assert not m.dispatched(); passed()
# A touch during the window cancels the held click.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and m.timers
m.touch(); assert not m.timers and not m.dispatched(); passed()
# A wheel detent ends the double-click window: the next press selects instead.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and m.timers
m.call(gap=50); assert not m.timers and not m.dispatched()
assert m.call(218,gap=50)==11 and len(m.dispatched())==1; passed()
# The first press usually opens a page that is still animating in; the second must still reach stock.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and not m.dispatched()
m.animating=1
assert m.call(218,gap=100)==0 and not m.dispatched() and not m.timers; passed()
# A release repeated within 80 ms is the same press: it never reaches stock or clicks twice.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(3)]; m.nodes[w]['children']=es
assert m.call(218,fire=False)==11 and m.timers
assert m.call(218,gap=5,fire=False)==11 and not m.dispatched() and len(m.timers)==1
assert m.call(218,gap=150)==0 and not m.dispatched() and not m.timers; passed()
# An empty menu swallows a single press but still hands a double press to stock.
m=Machine(); w=m.page()
assert m.call(218,fire=False)==11 and not m.dispatched()
assert m.call(218,gap=100)==0 and not m.dispatched(); passed()
# Real canvas ABI, translation and clip code execute; only the LCD rectangle sink is mocked.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
e=m.entry(w,48); m.nodes[w]['children']=[e]
for name in ('canvas_get_clip_rect','canvas_set_clip_rect','canvas_set_stroke_color','canvas_stroke_rect'):
    del m.handlers[syms[name]]
m.handlers[syms['lcd_stroke_rect']]='lcd_stroke_rect'
m.word(m.lcd+0x3c,1); m.word(m.lcd+0xb0,240); m.word(m.lcd+0xb4,240)
m.word(m.canvas,7); m.word(m.canvas+4,20)
for off,val in [(0x10,10),(0x14,30),(0x18,229),(0x1c,199)]: m.word(m.canvas+off,val)
m.paint(w)
assert IPOD or m.strokes[0][:4]==(8,69,238,46)
assert IPOD or m.strokes[0][4:]==((10,30,220,86),int(manifest['ring_color'],16))
assert [m.get(m.canvas+off) for off in (0x10,0x14,0x18,0x1c)]==[10,30,229,199]
assert m.get(m.lcd+0xc0)==0x12345678; passed()
# Centre and rapid wheel reversals retain the selected item during an unfinished wheel glide.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
es=[m.entry(w,i*48) for i in range(6)]; m.nodes[w]['children']=es
m.paint(w); m.glide=False
m.call(); m.call(); assert m.selected(w)==2 and m.get(w+0x84)==0
m.paint(w); assert m.selected(w)==2
assert m.call(218)==11 and m.dispatched()[0][1]==es[2]
m.call(); assert m.selected(w)==3
m.call(172); assert m.selected(w)==2
m.call(172); assert m.selected(w)==1 and m.get(w+0xe8)==0; passed()
# Empty menus never activate or turn off the screen; touch doesn't swallow its first event.
m=Machine(); w=m.page(); assert m.call(218)==11 and not m.dispatched()
assert m.touch()==0 and not m.dispatched(); passed()
# Clip an oversized target to its surface without losing its selection.
m=Machine(); w=m.page(); m.word(w+0x0c,96)
e=m.entry(w); m.word(e+0x0c,140); m.nodes[w]['children']=[e]
m.paint(w); assert m.selected(w)==0 and (IPOD or m.strokes[0][4]==(0,0,240,96)); passed()
# The actual stock filter runs first, including each screen-off lock mode.
for backlight in [0,1]:
    for mode in range(4):
        for key in [170,171,172,173,218,222,223,42]:
            results=[]
            for patched in [False,True]:
                m=Machine(patched); m.page('playing_page')
                m.byte(syms['g_backlight_status'],backlight)
                m.byte(syms['g_keylock_flag'],1); m.byte(syms['g_keylock_mode'],mode)
                results.append(m.call(key))
            assert results[0]==results[1],(backlight,mode,key,results)
            passed()
# Non-ring keys on supported pages must pass through unchanged.
for key in [0,13,170,171,222,223,0xffffffff]:
    m=Machine(); m.page(); assert m.call(key)==0 and not m.moved(); passed()
# Execute get_direction (in accel builds, the patched copy) for wraparound, thresholds, half-turn ambiguity.
for current,previous,threshold,want in [(5,195,5,-1),(195,5,5,1),(20,20,10,0),
    (30,20,10,0),(31,20,10,-1),(9,20,10,1),(120,20,10,0),(20,120,10,0)]:
    m=Machine(); assert m.call(address=syms['get_direction'],args=(current,previous,threshold,0))==want; passed()
if IPOD:
    def rect(m,a,r):
        for j,v in enumerate(r): m.word(a+4*j,v)
    def kid(m,parent,t,r,**kw):
        a=m.node(t,**kw); rect(m,a,r); m.word(a+0x48,parent); m.nodes[parent]['children'].append(a); return a
    # Stock 78 px card rows become flat 30 px text rows; only the selected row takes the blue style.
    m=Machine(); w=m.page(); m.word(w+0x0c,210)
    rows=[]
    for i in range(4):
        row=m.node('list_item'); rect(m,row,(0,i*30,375,30)); m.word(row+0x48,w)
        btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
        m.nodes[row]['children']=[btn]
        icon=kid(m,btn,'image',(10,0,52,70),image='local_allsongs')
        info=kid(m,btn,'view',(72,0,200,70))
        title=kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
        artist=kid(m,info,'view',(0,40,200,16)); kid(m,artist,'hscroll_label',(0,0,151,16))
        badge=kid(m,artist,'image',(0,0,36,16),image='img_aiff')
        choice=kid(m,btn,'image',(8,0,26,70),name='img_choice',visible=0)
        arrow=kid(m,btn,'image',(282,0,50,70),image='list_into')
        rows.append(dict(btn=btn,icon=icon,info=info,title=title,artist=artist,arrow=arrow,choice=choice))
    m.nodes[w]['children']=[m.get(r['btn']+0x48) for r in rows]
    got=lambda a:tuple(signed(m.get(a+4*j)) for j in range(4))
    got2=lambda mm,a:tuple(signed(mm.get(a+4*j)) for j in range(4))
    # Row geometry with the build's selection-pill inset: the button shrinks inside its row.
    E,ey=INSET,(1 if INSET else 0)
    def pill(w,h): return (E,ey,w-2*E,h-2*ey)
    W30,H30=375-2*E,30-2*ey
    # Paint only queues the pass: mutating mid-frame would lose the invalidation.
    assert m.paint(w)==0 and not m.strokes and m.selected(w)==0 and len(m.idles)==1
    assert not [c for c in m.calls if c[0] in ('widget_move_resize','widget_use_style')]
    m.paint(w); assert len(m.idles)==1
    done=m.idle(); assert ('widget_invalidate_force',w,0) in [c[:3] for c in done]
    r=rows[0]
    assert got(r['btn'])==pill(375,30) and got(r['info'])==(12,0,W30-48,H30) and got(r['title'])==(0,0,W30-48,H30)
    assert got(r['arrow'])==(W30-30,0,24,H30)
    assert not m.nodes[r['icon']]['visible'] and not m.nodes[r['artist']]['visible']
    assert m.nodes[r['choice']]['visible']==0 and got(r['choice'])==(8,0,26,70)
    assert m.nodes[r['btn']]['style']=='ipod_sel' and m.nodes[r['title']]['style']=='ipod_sel'
    assert m.nodes[r['btn']]['_ipod_style']=='s_btn_listitem'
    assert m.nodes[rows[1]['btn']]['style']=='s_btn_listitem'; passed()
    # A page slide snapshots the new window before its first frame, while the paint pass stands
    # down: the prepare hook lays it out and restyles it first, so the slide shows iPod rows.
    m2=Machine(); w2=m2.page(); m2.word(w2+0x0c,210); btns=[]
    for i in range(3):
        row=m2.node('list_item'); rect(m2,row,(0,i*30,375,30)); m2.word(row+0x48,w2)
        btn=m2.entry(row); m2.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m2,btn,(20,0,335,70))
        m2.nodes[row]['children']=[btn]; kid(m2,btn,'hscroll_label',(72,14,200,24),style='s_scrlabel_white24l')
        btns.append(btn)
    m2.nodes[w2]['children']=[m2.get(b+0x48) for b in btns]
    m2.animating=1; assert m2.paint(w2)==0 and not m2.idles  # mid-slide paints change nothing
    wa=m2.alloc(0x100)
    assert m2.run(0,0x682ee8,(wa,m2.canvas,0,m2.top),0x114,0)==0
    names=[c[0] for c in m2.calls]
    assert 'widget_layout' in names and names[-1]=='stock_prepare' and names.index('widget_layout')<names.index('widget_use_style')
    assert m2.nodes[btns[0]]['style']=='ipod_sel' and m2.nodes[btns[1]]['style']=='s_btn_listitem'
    assert got2(m2,btns[0])==pill(375,30); passed()
    # Moving on restores the app's own styles, including one it changed while selected.
    m.nodes[r['title']]['_ipod_style']='s_scrlabel_green24l'
    # The detent moves the bar itself, before its own frame paints.
    m.call(); assert m.selected(w)==1
    assert m.nodes[r['btn']]['style']=='s_btn_listitem' and m.nodes[r['title']]['style']=='s_scrlabel_green24l'
    assert m.nodes[rows[1]['btn']]['style']=='ipod_sel'; passed()
    # A settled layout repaints without touching widgets again, and the idle pass stops.
    m.paint(w); done=m.idle()
    assert not [c for c in done if c[0] in ('widget_move_resize','widget_use_style','widget_set_prop_int','widget_invalidate_force')]
    assert not m.idles; passed()
    # Disabled rows are flattened too; right-hand state images stay, shrunk into the row.
    m=Machine(); w=m.page(); m.word(w+0x0c,210)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    btn=m.node('button',enable=0,style='s_btn_listitem'); rect(m,btn,(20,0,335,70)); m.word(btn+0x48,row)
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    title=kid(m,btn,'hscroll_label',(10,0,246,70),style='s_scrlabel_gray24l')
    gain=kid(m,btn,'image',(276,0,50,70),image='gain_low')
    down=kid(m,btn,'image',(282,0,50,70),image='list_intodown')
    m.paint(w); m.idle()
    assert got(btn)==pill(375,30) and got(title)==(12,0,W30-84,H30) and m.nodes[title]['style']=='s_scrlabel_gray24l'
    assert got(gain)==(W30-56,0,50,H30) and m.nodes[gain]['visible'] and m.nodes[gain].get('draw_type')=='icon'
    assert got(down)==(W30-30,0,24,H30); passed()
    # Home rows: the tap target is a full-row image inside the button; it selects the whole row.
    m=Machine(); w=m.page('home_page'); m.word(w+0x0c,234)
    homes=[]
    for i in range(3):
        row=m.node('list_item'); rect(m,row,(0,i*30,375,30)); m.word(row+0x48,w)
        btn=m.node('button',style='s_btn_listitem'); rect(m,btn,(0,0,375,30)); m.word(btn+0x48,row)
        m.nodes[row]['children']=[btn]
        label=kid(m,btn,'label',(12,0,291,30),style='s_label_white20l')
        kid(m,btn,'image',(345,0,24,30),image='list_into')
        hit=m.entry(btn); m.nodes[hit].update(type='image'); rect(m,hit,(0,0,375,30)); m.nodes[btn]['children'].append(hit)
        homes.append((row,btn,label,hit))
    m.nodes[w]['children']=[h[0] for h in homes]
    m.paint(w); m.idle()
    assert m.nodes[homes[0][1]]['style']=='ipod_sel' and m.nodes[homes[0][2]]['style']=='ipod_sel'
    assert m.nodes[homes[0][3]]['visible'] and got(homes[0][3])==(0,0,375,30)
    m.call(); assert m.nodes[homes[1][1]]['style']=='ipod_sel' and m.nodes[homes[0][1]]['style']=='s_btn_listitem'
    m.top=m.nodes[w].get('_win', m.top); m.run(0,0x6461b0,(w,0,0,0),0x114,0)  # a layout pass keeps the selection
    assert m.selected(w)==1 and m.nodes[homes[1][1]]['style']=='ipod_sel'
    m.call(); assert m.selected(w)==2 and m.nodes[homes[2][1]]['style']=='ipod_sel'
    m.call(172); m.call(172); assert m.selected(w)==0
    assert m.call(173)==11 and m.call(218)==11 and m.dispatched()[0][1]==homes[1][3]; passed()
    # iPod builds also drive Update Library, whose rows only render once re-laid out.
    m=Machine(); m.page('updatemusic_page'); assert m.call()==11 and m.moved(); passed()
    # Now-playing marker: the row whose gif badge is switched on gets pink bars at its right edge
    # (white on the selected pill); the title's green "playing" style marks it too.
    m=Machine(); w=m.page('allmusic_page'); m.word(w+0x0c,160)
    np_rows=[]
    for i in range(3):
        row=m.node('table_row'); rect(m,row,(0,i*40,365,40)); m.word(row+0x48,w)
        btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
        m.nodes[row]['children']=[btn]
        icon=kid(m,btn,'image',(8,0,50,70),name='img_icon'); gbg=kid(m,icon,'image',(0,9,50,52),name='img_gifbg',visible=int(i==2))
        info=kid(m,btn,'view',(72,0,200,70)); kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
        np_rows.append(btn)
    m.nodes[w]['children']=[m.get(b+0x48) for b in np_rows]
    m.paint(w); m.idle()
    assert [m.nodes[b].get('_ipod_np',0) for b in np_rows]==[0,0,1]; passed()
    m.fills=[]; m.paint(np_rows[2]); W2,H2=365-2*E,40-2*ey
    frames=[5,9,13,15,11,7,10,14]; fr=lambda k:[frames[(k+i*3)&7] for i in range(3)]
    hs=fr(0); assert [f[:4] for f in m.fills]==[(W2-26+5*i,H2//2+7-hs[i],3,hs[i]) for i in range(3)] \
        and m.fills[0][4]==0xff482dfa, m.fills; passed()
    # Bouncing while playing (status bar shows bar_play): each tick advances a frame and repaints.
    state=m.node('image',name='img_state',image='bar_play'); sb=m.node('system_bar',children=[state])
    m.nodes[m.wm]['children']=[sb]
    ticks=m.run(0,m.np_timer,(0,0,0,0),0x114,120); assert ticks==8 and ('widget_invalidate_force',np_rows[2]) in [c[:2] for c in m.calls]
    m.fills=[]; m.paint(np_rows[2]); assert [f[3] for f in m.fills]==fr(1)!=hs; passed()
    # Paused (bar_pause): the tick keeps running but neither advances nor repaints: bars freeze.
    m.nodes[state]['image']='bar_pause'
    assert m.run(0,m.np_timer,(0,0,0,0),0x114,120)==8 and not [c for c in m.calls if c[0]=='widget_invalidate_force']
    m.fills=[]; m.paint(np_rows[2]); assert [f[3] for f in m.fills]==fr(1); passed()
    m.nodes[state]['image']='bar_play'; m.run(0,m.np_timer,(0,0,0,0),0x114,120)
    m.fills=[]; m.paint(np_rows[2]); assert [f[3] for f in m.fills]==fr(2); passed()  # resumes
    # Paused, the app switches its badge off: the row with the last playing title keeps the marker.
    titles=[m.nodes[m.nodes[b]['children'][1]]['children'][0] for b in np_rows]
    for lab,t in zip(titles,('Alpha','Beta','Gamma')): m.nodes[lab]['wtext']=t
    m.paint(w); m.idle()  # playing: Gamma is remembered
    gbg=m.nodes[m.nodes[np_rows[2]]['children'][0]]['children'][0]; m.nodes[gbg]['visible']=0
    m.nodes[state]['image']='bar_pause'; m.paint(w); m.idle()
    assert [m.nodes[b].get('_ipod_np',0) for b in np_rows]==[0,0,1]; passed()
    m.paint(w); assert not [c for c in m.idle() if c[0]=='widget_set_prop_int']; passed()  # stable, no churn
    m.nodes[state]['image']='bar_play'; m.nodes[gbg]['visible']=1; m.paint(w); m.idle()  # playing again
    m.nodes[np_rows[2]]['_ipod_np']=0; assert m.run(0,m.np_timer,(0,0,0,0),0x114,120)==7; passed()  # stops when none
    m.nodes[np_rows[2]]['_ipod_np']=1
    m.fills=[]; m.paint(np_rows[0]); assert not m.fills; passed()
    m.nodes[np_rows[2]]['style']='ipod_sel'; m.fills=[]; m.paint(np_rows[2]); assert m.fills[0][4]==0xffffffff; passed()
    m=Machine(); w=m.page('allmusic_page'); m.word(w+0x0c,160)
    row=m.node('table_row'); rect(m,row,(0,0,365,40)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    kid(m,btn,'hscroll_label',(72,0,200,70),style='s_scrlabel_green24l')
    m.call(); m.paint(w); m.idle(); assert m.nodes[btn].get('_ipod_np')==1; passed()  # green title while selected
    # Row binding: the page's on_load_data is wrapped, so a row it re-binds (play/pause refreshes all
    # of them) is flattened in the same call, before any paint: no frame of the stock card.
    m=Machine(); w=m.page('allmusic_page','table_client'); m.word(w+0x0c,160); m.word(w+0x48,m.top); m.nodes[m.top]['type']='window'
    APP=0x1100000; m.handlers[APP]='app_load'
    m.call(address=0x5ca984,args=(w,APP,0xc7c7,0))  # table_client_set_on_load_data
    assert m.loaddata[0]==w and m.loaddata[2]==w and m.nodes[w]['_ipod_load_fn']==APP and m.nodes[w]['_ipod_load_ctx']==0xc7c7; passed()
    wrapper=m.loaddata[1]
    row=m.node('table_row'); rect(m,row,(0,40,365,40)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    info=kid(m,btn,'view',(72,0,200,70)); title=kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
    va=kid(m,info,'view',(0,40,200,16)); badge=kid(m,va,'image',(0,0,36,16),image='img_aiff')
    kid(m,va,'hscroll_label',(42,0,151,16),style='s_scrlabel_white16l')
    m.nodes[w]['_ringnav_index']=1
    def restock(ctx,index,r):  # what the app does: stock positions, badge back on
        assert ctx==0xc7c7 and index==1 and r==row
        rect(m,btn,(20,0,335,70)); rect(m,title,(0,14,200,24)); m.nodes[badge]['visible']=1
    m.on_load=restock
    m.run(0,wrapper,(w,1,row,0),0x114,0)
    assert m.nodes[badge]['visible']==0 and got(title)==(0,1,W2-48,22) and got(btn)==pill(365,40)
    assert m.nodes[btn]['style']=='ipod_sel' and m.nodes[title]['style']=='ipod_sel'; passed()  # selected row
    # Grid rows (album covers) keep their stock layout.
    m=Machine(); w=m.page(); row=m.node('table_row'); rect(m,row,(0,0,365,160)); m.word(row+0x48,w)
    btn=m.entry(row); rect(m,btn,(20,0,150,150)); m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    m.paint(w); m.idle(); assert got(btn)==(20,0,150,150) and 'style' not in m.nodes[btn]; passed()
    # Tables request 78 px rows once at creation; that becomes 30, other heights pass through.
    for page,asked,want in [('sysset_page',78,30),('allmusic_page',78,40),('album_page',78,46),
                            ('album_page',160,160),('localclass_page',48,48),('playerqueue_page',78,46)]:
        m=Machine(); tc=m.page(page,'table_client'); m.word(tc+0x48,m.top); m.nodes[m.top]['type']='window'
        m.call(address=0x5c9de0,args=(tc,asked,0,0))
        assert [c[1:3] for c in m.calls if c[0]=='stock_rowh']==[(tc,want)]; passed()
    # Two-line song rows: title over artist; the format badge goes; both lines turn white.
    m=Machine(); w=m.page('allmusic_page'); m.word(w+0x0c,160)
    row=m.node('table_row'); rect(m,row,(0,0,365,40)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    info=kid(m,btn,'view',(72,0,200,70)); title=kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
    va=kid(m,info,'view',(0,40,200,16)); badge=kid(m,va,'image',(0,0,36,16),image='img_aiff')
    artist=kid(m,va,'hscroll_label',(42,0,151,16),style='s_scrlabel_white16l')
    m.paint(w); m.idle()
    W2,H2=365-2*E,40-2*ey
    assert got(btn)==pill(365,40) and got(info)==(12,0,W2-48,H2) and got(title)==(0,1,W2-48,22)
    assert got(va)==(0,21,W2-48,18) and got(artist)==(0,0,W2-48,18) and not m.nodes[badge]['visible']
    assert m.nodes[title]['style']=='ipod_sel' and m.nodes[artist]['style']=='ipod_sel2'; passed()
if ACCEL:
    def accel_model(calls, rows, sel=0):
        """Reference for the acceleration rules: calls = [(gap_ms, dir, flick_counts)]."""
        streak, last_dir, out = 0, 0, []
        for n, (gap, d, mag) in enumerate(calls):
            first = n == 0
            streak = 0 if first or d != last_dir or gap >= 400 else streak // 2 if gap >= 200 else streak + 1
            last_dir = d
            k = streak
            st = 64 if k >= 30 else 32 if k >= 22 else 16 if k >= 16 else 8 if k >= 10 else 4 if k >= 5 else 2 if k >= 2 else 1
            fl = 8 if mag >= 80 else 4 if mag >= 60 else 2 if mag >= 40 else 1
            cap = rows // 16
            step = max(st, fl); step = min(step, cap) if cap > 1 else 1
            sel = min(max(sel + d * step, 0), rows - 1) if step > 1 else sel + d if 0 <= sel + d < rows else sel
            out.append(sel)
        return out
    def big_table(rows):
        # Virtual table (the song list): only 5 rows bound, never rebound; jumps must still stick.
        m=Machine(); w=m.page(t='table_client'); m.word(w+0x0c,192); m.word(w+0x78,48); m.word(w+0x7c,rows)
        m.nodes[w]['children']=[m.entry(w,i*48,index=i) for i in range(5)]; m.paint(w); return m,w
    def run(m,w,calls):
        out=[]
        for gap,d,mag in calls:
            if mag: assert m.call(address=syms['get_direction'],args=(mag,0,20,0),gap=0)==-1  # knob thread: no UI time
            m.call(173 if d>0 else 172,gap=gap); out.append(m.selected(w))
        return out
    spin=[(83,1,0)]*40
    for rows in (6000,1000,200,60):
        m,w=big_table(rows); got_=run(m,w,spin); assert got_==accel_model(spin,rows),(rows,got_); passed()
    m,w=big_table(6000); run(m,w,spin); assert m.selected(w)-accel_model(spin,6000)[-2]==64; passed()  # top speed
    # Short lists never accelerate: every detent is exactly one row.
    m,w=big_table(20); assert run(m,w,[(83,1,0)]*15)==list(range(1,16)); passed()
    m,w=big_table(20); assert run(m,w,[(1000,1,60)])==[1]; passed()  # nor does a flick
    # Flicks, skipped polls (165-185 ms keep speed), hesitations (halve), pauses and reversals (reset).
    mixed=[(1000,1,60),(83,1,0),(83,1,80)]+[(83,1,0)]*12+[(170,1,0),(300,1,0),(83,1,0),(500,1,0),(83,-1,0),(83,-1,0)]
    m,w=big_table(6000); assert run(m,w,mixed)==accel_model(mixed,6000); passed()
    if IPOD:
        # Fast-scroll letter: shown once detents jump 8+ rows, from the selected title's first
        # character (read after the table binds the landed-on rows), hidden by its timer.
        m,w=big_table(6000); tc=w
        letter=m.node('label',name='ipod_letter',visible=0,wtext=''); m.nodes[m.top]['children'].append(letter)
        run(m,w,[(83,1,0)]*12); sel=m.selected(w)
        assert not m.nodes[letter]['visible']  # the landed-on row is not bound yet: nothing to read
        for i,e in enumerate(m.nodes[w]['children']):  # the table rebinds rows around the selection
            m.word(e+0x78,sel-2+i); lab=m.node('hscroll_label',wtext='banana' if i==2 else 'zz'); m.word(lab+0x48,e)
            m.nodes[e]["children"]=[lab]; m.word(e+4,(sel-2+i)*48)  # table rows sit at virtual y
        m.word(w+0x80,(sel-2)*48)
        m.paint(w); m.idle()
        assert m.nodes[letter]['visible'] and m.nodes[letter]['wtext']=='B', m.nodes[letter]; passed()
        m.run(0,m.letter_timer,(0,0,0,0),0x114,800); assert not m.nodes[letter]['visible']; passed()
        m,w=big_table(6000); letter=m.node('label',name='ipod_letter',visible=0,wtext='')
        m.nodes[m.top]['children'].append(letter); run(m,w,[(1000,1,0)]*3)
        assert not m.nodes[letter]['visible']; passed()  # slow browsing never shows it
    # A jump near the end stops on the last row instead of being refused.
    m,w=big_table(300); assert run(m,w,[(83,1,0)]*80)[-1]==299; passed()
if IPOD:
    # The shown album line mirrors the hidden app label without "Album:"; lookalikes stay intact,
    # and a repeat sync with nothing new sets nothing (no flicker while the app re-sets its label).
    for text,want in [('Album:Hooray for Boobies','Hooray for Boobies'),('Star Wars: A New Hope','Star Wars: A New Hope')]:
        m=Machine(); src=m.node('label',name='label_album',wtext=text,visible=0)
        dst=m.node('label',name='label_album_ipod',wtext=''); bar=m.node('slider',name='slider_play')
        m.top=m.node('window','playing_page',[src,dst,bar])
        m.paint(bar); m.idle(); assert m.nodes[dst]['wtext']==want,(text,m.nodes[dst]['wtext'])
        m.paint(bar); assert not [c for c in m.idle() if c[0]=='widget_set_text']; passed()
    # Rounded art: when the art page paints, the cover's image is filled through a rounded path:
    # translate to the cover, scale the image to its 140 px box, radius 12 px on screen.
    m=Machine(); cover=m.node('image',name='img_cover',image='file:///tmp/coverpic.jpg')
    for j,v in enumerate((0,0,140,140)): m.word(cover+4*j,v)
    view=m.node('view',name='view_album',children=[cover]); m.top=m.node('window','playing_page',[view])
    m.bitmaps['file:///tmp/coverpic.jpg']=(500,500); m.word(m.canvas,16); m.word(m.canvas+4,70)
    m.paint(view)
    assert m.vg[:5]==[('vgcanvas_save',),('vgcanvas_translate',16.0,70.0),('vgcanvas_scale',0.28,0.28),
                      ('vgcanvas_begin_path',),('vgcanvas_rounded_rect',0.0,0.0,500.0,500.0,42.857)], m.vg
    assert m.vg[5][:2]==('vgcanvas_paint',0) and m.vg[6:]==[('vgcanvas_restore',)], m.vg; passed()  # fill
    m=Machine(); cover=m.node('image',name='img_cover',image='play_defaultcover')  # not loaded: draw nothing
    view=m.node('view',name='view_album',children=[cover]); m.top=m.node('window','playing_page',[view])
    m.paint(view); assert m.vg==[]; passed()
    # Home art pane, idle: a wall of cached thumbnails, every tile clipped inside the pane.
    def screen_rects(vg):
        out=[]; t=s_=None
        for c in vg:
            if c[0]=='vgcanvas_translate': t=c[1:]
            elif c[0]=='vgcanvas_scale': s_=c[1:]
            elif c[0]=='vgcanvas_rounded_rect':
                x,y,w,h,r=c[1:]; out.append((t[0]+x*s_[0],t[1]+y*s_[1],w*s_[0],h*s_[1],r*s_[0]))
        return out
    m=Machine(); pane=m.node('view',name='view_homeart'); m.top=m.node('window','home_page',[pane])
    for j,v in enumerate((221,48,144,204)): m.word(pane+4*j,v)
    m.word(m.canvas,221); m.word(m.canvas+4,78)
    m.dir_items=[('%02dabc0.jpg'%i,1) for i in range(30)]+[('notes.txt',1),('sub',0)]
    for i in range(30): m.bitmaps['file:///mnt/mmc/.sldp/%02dabc0.jpg'%i]=(60,60)
    m.paint(pane); rs=screen_rects(m.vg)
    alphas=[c[1] for c in m.vg if c[0]=='vgcanvas_set_global_alpha']; assert alphas and all(0<=a<=1 for a in alphas), alphas
    assert rs and all(221-0.05<=x and 78-0.05<=y and x+w<=221+144+0.05 and y+h<=78+204+0.05 for x,y,w,h,r in rs), rs
    assert len({(round(x),round(y)) for x,y,w,h,r in rs})==len(rs); passed()
    # A new cycle picks a new wall and releases the old wall's thumbnails from the image cache.
    w2=Machine(); p2=w2.node('view',name='view_homeart'); w2.top=w2.node('window','home_page',[p2])
    for j,v in enumerate((221,48,144,204)): w2.word(p2+4*j,v)
    w2.dir_items=list(m.dir_items); w2.bitmaps=dict(m.bitmaps); w2.paint(p2)
    shown={'file:///mnt/mmc/.sldp/'+c[0] for c in w2.dir_items if c[0].endswith('.jpg')}
    w2.now+=9000; w2.unloaded=[]; w2.paint(p2)
    assert len(w2.unloaded)==24 and set(w2.unloaded)<=shown, w2.unloaded; passed()
    # A track loaded (status bar play/pause): one panned cover filling the pane, rounded 12 px.
    state=m.node('image',name='img_state',image='bar_pause'); m.nodes[m.wm]['children']=[m.node('system_bar',children=[state])]
    m.bitmaps['file:///tmp/coverpic.jpg']=(500,500); m.vg=[]; m.paint(pane); rs=screen_rects(m.vg)
    assert len(rs)==1 and [round(v,1) for v in rs[0]]==[221.0,78.0,144.0,204.0,12.0], rs; passed()
    # Continuous drift: the art is in the same place just before and just after a cycle boundary.
    tr=lambda: [c for c in m.vg if c[0]=='vgcanvas_translate'][-1][1:]
    m.now+=9000-1-(m.now-1000)%9000; m.vg=[]; m.paint(pane); a=tr()
    m.now+=2; m.vg=[]; m.paint(pane); b=tr()
    assert abs(a[0]-b[0])<1.0 and abs(a[1]-b[1])<1.0, (a,b); passed()
    # The pan timer repaints only the pane while Home is on top, and stops elsewhere.
    assert m.run(0,m.home_timer,(0,0,0,0),0x114,80)==8 and ('widget_invalidate_force',pane) in [c[:2] for c in m.calls]
    m.top=m.node('window','sysset_page',[]); assert m.run(0,m.home_timer,(0,0,0,0),0x114,80)==7; passed()
    # Up Next: 46 px rows, the cover a smooth rounded 36 px thumbnail left of title over artist
    # (stock draw skipped with opacity 0; the paint hook draws it through vgcanvas).
    m=Machine(); w=m.page('playerqueue_page'); m.word(w+0x0c,184)
    row=m.node('table_row'); rect(m,row,(0,0,365,46)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    icon=kid(m,btn,'image',(8,0,50,70),name='img_icon',image='file:///mnt/mmc/.sldp/q1.jpg')
    info=kid(m,btn,'view',(72,0,200,70)); title=kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
    va=kid(m,info,'view',(0,40,200,16)); kid(m,va,'image',(0,0,36,16),image='img_aiff')
    kid(m,va,'hscroll_label',(42,0,151,16),style='s_scrlabel_white16l')
    m.paint(w); m.idle()
    H=46-2*ey; TW=365-2*E-48-44
    assert got(icon)==(10,(H-36)//2,36,36) and m.nodes[icon]['opacity']==0 and m.nodes[icon]['visible']
    assert got(info)==(56,0,TW,H) and got(title)==(0,(H-40)//2+1,TW,22) and m.nodes[btn]['_ipod_art']==1; passed()
    m.bitmaps['file:///mnt/mmc/.sldp/q1.jpg']=(60,60); m.word(m.canvas,100); m.word(m.canvas+4,200)
    m.vg=[]; m.paint(btn); rs=screen_rects(m.vg)
    assert [tuple(round(v,1) for v in r) for r in rs]==[(110.0,200.0+(H-36)//2,36.0,36.0,6.0)], rs; passed()
    # Pop-ups: the wheel moves a focus between the buttons (left one first: Cancel), the centre
    # clicks the focused one after the double-press window; the confirm pills take ringed styles.
    m=Machine(); dlg=m.node('dialog','confirminfo_dialog'); m.top=dlg
    cancel=m.entry(dlg); m.nodes[cancel].update(type='image',name='img_cancel',style='s_img_confirmcancel'); rect(m,cancel,(30,172,150,46))
    ok=m.entry(dlg); m.nodes[ok].update(type='image',name='img_enter',style='s_img_confirmok'); rect(m,ok,(195,172,150,46))
    note=m.node('hscroll_label'); m.nodes[dlg]['children']=[note,cancel,ok]
    m.paint(dlg); m.idle()
    assert m.nodes[cancel]['style']=='ipod_cancelfocus' and m.nodes[ok]['style']=='s_img_confirmok'
    assert m.call(173)==11 and m.nodes[ok]['style']=='ipod_okfocus' and m.nodes[cancel]['style']=='s_img_confirmcancel'
    assert m.call(173)==11 and m.nodes[dlg]['_ipod_dsel']==1  # stops at the last button
    assert m.call(172)==11 and m.nodes[cancel]['style']=='ipod_cancelfocus'; passed()
    m.call(173); clicked=[]; m.on_click=lambda a,b: clicked.append(a)
    assert m.call(218)==11 and clicked==[ok]; passed()
    # Single-button prompt (scan, auto-shutdown): the button takes the pink pill; centre clicks it.
    m=Machine(); dlg=m.node('dialog','autoshutdown_dialog'); m.top=dlg
    btn=m.entry(dlg); m.nodes[btn].update(type='button',name='btn_cancel'); rect(m,btn,(44,236,287,40))
    m.nodes[dlg]['children']=[btn]; m.paint(dlg); m.idle(); assert m.nodes[btn]['style']=='ipod_sel'
    clicked=[]; m.on_click=lambda a,b: clicked.append(a); assert m.call(218)==11 and clicked==[btn]; passed()
    # The volume pop-up has no buttons: keys stay with stock.
    m=Machine(); dlg=m.node('dialog','volume_dialog',[m.node('slider')]); m.top=dlg
    assert m.call(173)!=11 and m.call(172)!=11; passed()
    # Sort order: the right-hand radio sits in the row, centred, not in its stock 70 px box.
    m=Machine(); w=m.page(); m.word(w+0x0c,150)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    kid(m,btn,'hscroll_label',(72,0,200,70),style='s_scrlabel_white24l')
    radio=kid(m,btn,'image',(276,0,50,70),name='img_choice0',image='select')
    m.paint(w); m.idle(); assert got(radio)==(375-2*E-40,0,32,30-2*ey); passed()
    # Playback speed: its four tappable chips are packed at the row's right, centred in the row, and
    # the title stops before them.
    m=Machine(); w=m.page(); m.word(w+0x0c,150)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_forwardspeed'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    title=kid(m,btn,'hscroll_label',(72,0,200,70),style='s_scrlabel_white20l')
    chips=[]
    for x in (120,177,231,283):
        c=m.entry(btn); m.nodes[c].update(type='image',image='forward_un1'); rect(m,c,(x,9,42,60)); m.word(c+0x48,btn)
        m.nodes[btn]['children'].append(c); chips.append(c)
    m.paint(w); m.idle(); RW=375-2*E; H=30-2*ey; x0=RW-8-4*42-3*4
    assert [got(c) for c in chips]==[(x0+i*46,0,42,H) for i in range(4)], [got(c) for c in chips]
    assert got(title)[2]==x0-12-8 and all(m.nodes[c]['visible'] for c in chips); passed()
    # A pop-up button counts even without a click handler of its own.
    m=Machine(); dlg=m.node('dialog','updatemusic_dialog'); m.top=dlg
    b=m.node('button',name='btn_no'); rect(m,b,(44,266,287,40)); m.nodes[dlg]['children']=[b]
    m.paint(dlg); m.idle(); assert m.nodes[b]['style']=='ipod_sel' and m.call(173)==11; passed()
    # With the USB cable in (link status 2) list pages leave the wheel to stock, but pop-ups
    # (Scan music? after USB storage) still take it.
    m=Machine(); m.byte(syms['g_usblink_status'],2); dlg=m.node('dialog','confirminfo_dialog'); m.top=dlg
    cancel=m.entry(dlg); m.nodes[cancel].update(type='image',name='img_cancel',style='s_img_confirmcancel'); rect(m,cancel,(30,172,150,46))
    ok=m.entry(dlg); m.nodes[ok].update(type='image',name='img_enter',style='s_img_confirmok'); rect(m,ok,(195,172,150,46))
    m.nodes[dlg]['children']=[cancel,ok]; m.paint(dlg); m.idle()
    assert m.nodes[cancel]['style']=='ipod_cancelfocus' and m.call(173)==11 and m.nodes[ok]['style']=='ipod_okfocus'
    m.top=m.node('window','sysset_page',[m.node('scroll_view')]); assert m.call(173)!=11; passed()
    # Playlists: Import | Export share the first row as two side-by-side pills; only the selected one lights.
    m=Machine(); w=m.page(); m.word(w+0x0c,150)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    pair=[]
    for x in (20,191):
        b=m.entry(row); m.nodes[b].update(type='button',style='s_btn_listitem'); rect(m,b,(x,0,164,70))
        lab=kid(m,b,'hscroll_label',(63,21,91,28),style='s_scrlabel_white20l'); icon=kid(m,b,'image',(10,10,50,50),image='playlist_import')
        pair.append((b,lab,icon))
    m.nodes[row]['children']=[p_[0] for p_ in pair]; m.nodes[w]['children']=[row]
    m.paint(w); m.idle(); each=(375-2*E-6)//2; H=30-2*ey
    assert got(pair[0][0])==(E,ey,each,H) and got(pair[1][0])==(E+each+6,ey,each,H)
    assert not m.nodes[pair[0][2]]['visible'] and got(pair[1][1])==(12,0,each-48,H)
    assert m.nodes[pair[0][0]]['style']=='ipod_sel' and m.nodes[pair[1][0]]['style']=='s_btn_listitem'
    m.call(); assert m.nodes[pair[1][0]]['style']=='ipod_sel' and m.nodes[pair[0][0]]['style']=='s_btn_listitem'; passed()
    # Speed chips as the wheel's stops (the row itself is not tappable): the focused chip is bright,
    # the others dimmed, and the row takes no pill (its pink chip would vanish into it).
    m=Machine(); w=m.page(); m.word(w+0x0c,150)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    btn=m.node('button',style='s_btn_forwardspeed'); rect(m,btn,(20,0,335,70)); m.word(btn+0x48,row)
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]; kid(m,btn,'hscroll_label',(72,0,200,70))
    chips=[]
    for x in (120,177,231,283):
        c=m.entry(btn); m.nodes[c].update(type='image',image='forward_un1'); rect(m,c,(x,9,42,60)); m.word(c+0x48,btn)
        m.nodes[btn]['children'].append(c); chips.append(c)
    m.paint(w); m.idle(); assert [m.nodes[c].get('opacity',255) for c in chips]==[255,110,110,110]
    m.call(); assert [m.nodes[c].get('opacity',255) for c in chips]==[110,255,110,110] and m.nodes[btn]['style']=='s_btn_forwardspeed'; passed()
    # Now Playing: "3 of 12" (queue position and size) in the header, and the time left in place of
    # the length, refreshed when the elapsed time repaints; only set when the text changes.
    m=Machine(); count=m.node('label',name='label_npcount',wtext='Now Playing'); rem=m.node('label',name='label_remain_ipod',wtext='')
    title=m.node('hscroll_label',name='scrlabel_title')
    cur=m.node('label',name='label_playtime',wtext='01:23'); length=m.node('label',name='label_playlen',wtext='03:45',visible=0)
    m.top=m.node('window','playing_page',[title,count,cur,length,rem]); m.word(syms['mcl_pdeqplaylist'],0x1234); m.np_pos,m.np_n=2,12
    m.paint(cur); m.idle(); assert m.nodes[count]['wtext']=='3 of 12' and m.nodes[rem]['wtext']=='-02:22'
    assert m.nodes[title]['yoyo']==1  # long titles scroll there and back
    m.nodes[cur]['wtext']='01:24'; m.paint(cur); done=m.idle()
    assert m.nodes[rem]['wtext']=='-02:21' and len([c for c in done if c[0]=='widget_set_text'])==1  # the counter is unchanged
    m.nodes[length]['wtext']='1:02:03'; m.paint(cur); m.idle(); assert m.nodes[rem]['wtext']=='-01:00:39'
    m.word(syms['mcl_pdeqplaylist'],0); m.paint(cur); m.idle(); assert m.nodes[count]['wtext']=='Now Playing'; passed()
    # Home cover after a skip: a new track (queue position) drops the cached cover so it is re-read,
    # retried every 500 ms for 3 s (the app writes the file a moment later), then left alone.
    m=Machine(); pane=m.node('view',name='view_homeart'); m.top=m.node('window','home_page',[pane])
    for j,v in enumerate((221,48,144,204)): m.word(pane+4*j,v)
    state=m.node('image',name='img_state',image='bar_play'); m.nodes[m.wm]['children']=[m.node('system_bar',children=[state])]
    m.bitmaps['file:///tmp/coverpic.jpg']=(500,500); m.word(syms['mcl_pdeqplaylist'],0x1234); m.np_pos,m.np_n=0,13
    unloads=lambda: len([c for c in m.calls if c[0]=='widget_unload_image'])
    tick=lambda: m.run(0,HOOKS['widget_on_paint_border'][0],(pane,m.canvas,0,0),0x114,100)  # a frame 100 ms on
    tick(); first=unloads(); tick(); again=unloads()
    assert first==1 and again==0, (first,again)  # at most one re-read per 500 ms
    m.np_pos=1; tick(); assert unloads()==1
    n=0
    for _ in range(40): tick(); n+=unloads()
    assert 4<=n<=6, n  # retried through the window, then stops
    tick(); assert unloads()==0; passed()
    # Lyrics: the app's scroll (line x 60 px, meant for wrapped lines) is replaced by the real
    # position of the current line, centred, with a 300 ms glide; untimed lyrics are left alone.
    m=Machine(); m.now+=10000; sv=m.node('scroll_view',name='scroll_lrc'); m.word(sv+0x0c,164); m.word(sv+0x7c,600); m.word(sv+0x84,0)
    lines=[]
    for i in range(30):
        l=m.node('label',lrc_time=i*1000+500); rect(m,l,(0,i*20,375,20)); lines.append(l)
    m.nodes[sv]['children']=lines; m.playtime=10600
    assert m.run(0,0x5f0178,(sv,0,6*60,10),0x114,0)==0 and m.scrolls==[(sv,0,10*20+10-82,300)]
    m.scrolls=[]; m.playtime=100; m.run(0,0x5f0178,(sv,0,0,10),0x114,0); assert m.scrolls==[]  # before line 0: already at the top
    m.scrolls=[]; m.playtime=99999; m.run(0,0x5f0178,(sv,0,25*60,10),0x114,0); assert m.scrolls==[(sv,0,600-164,300)]  # clamped at the end
    for l in lines: m.nodes[l]['lrc_time']=0
    m.word(sv+0x84,77); m.scrolls=[]; m.run(0,0x5f0178,(sv,0,240,10),0x114,0); assert m.scrolls==[]  # untimed: user's scroll kept
    other=m.node('scroll_view',name='scroll_view'); m.run(0,0x5f0178,(other,0,123,10),0x114,0); assert m.scrolls==[(other,0,123,10)]; passed()
    # A touch (drag) pauses following for 4 s, so timed lyrics can be read ahead, then it resumes.
    for i,l in enumerate(lines): m.nodes[l]['lrc_time']=i*1000+500
    m.top=m.node('window','playing_page',[]); m.touch(); m.scrolls=[]; m.playtime=10600
    m.run(0,0x5f0178,(sv,0,360,10),0x114,3000); assert m.scrolls==[]
    m.run(0,0x5f0178,(sv,0,360,10),0x114,1500); assert m.scrolls==[(sv,0,128,300)]; passed()
    # Albums: the same 46 px cover rows, from the album list's real row (dump): img_icon holds the
    # album's .sldp cover; album name over artist beside it.
    m=Machine(); w=m.page('album_page'); m.word(w+0x0c,218)
    row=m.node('table_row'); rect(m,row,(0,0,365,46)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    kid(m,btn,'image',(8,0,26,70),name='img_choice',visible=0)
    icon=kid(m,btn,'image',(48,0,50,70),name='img_icon',image='file:///mnt/mmc/.sldp/4b2e2c818be626af0.jpg',visible=0)
    info=kid(m,btn,'view',(72,0,200,70)); name_=kid(m,info,'hscroll_label',(0,14,200,24),style='s_scrlabel_white24l')
    va=kid(m,info,'view',(0,40,200,16)); kid(m,va,'hscroll_label',(0,0,151,16),style='s_scrlabel_white16l')
    arrow=kid(m,btn,'image',(282,0,50,70),image='list_into')
    m.paint(w); m.idle(); H=46-2*ey; TW=365-2*E-48-44
    assert got(icon)==(10,(H-36)//2,36,36) and m.nodes[icon]['visible'] and m.nodes[icon]['opacity']==0
    assert got(info)==(56,0,TW,H) and got(name_)==(0,(H-40)//2+1,TW,22) and m.nodes[btn]['_ipod_art']==1
    assert got(arrow)==(365-2*E-30,0,24,H); passed()
    # Cover rows drop the previous album's cover from the image cache when a recycled row is bound
    # to another album (kept, they filled memory: grey covers, failed writes). Same cover, or the
    # grey placeholder: nothing to drop.
    m=Machine(); w=m.page('album_page','table_client'); m.word(w+0x0c,218); m.word(w+0x48,m.top); m.nodes[m.top]['type']='window'
    APP=0x1100000; m.handlers[APP]='app_load'; m.call(address=0x5ca984,args=(w,APP,0xc7c7,0)); wrapper=m.loaddata[1]
    row=m.node('table_row'); rect(m,row,(0,0,365,46)); m.word(row+0x48,w)
    btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
    m.nodes[row]['children']=[btn]; m.nodes[w]['children']=[row]
    icon=kid(m,btn,'image',(48,0,50,70),name='img_icon',image='file:///mnt/mmc/.sldp/aaa0.jpg')
    def bind(img): m.on_load=lambda ctx,i,r: m.nodes[icon].update(image=img); m.run(0,wrapper,(w,3,row,0),0x114,0)
    bind('file:///mnt/mmc/.sldp/bbb0.jpg'); assert m.unloaded==['file:///mnt/mmc/.sldp/aaa0.jpg']
    bind('file:///mnt/mmc/.sldp/bbb0.jpg'); assert m.unloaded==['file:///mnt/mmc/.sldp/aaa0.jpg']
    bind('default_album_small'); bind('file:///mnt/mmc/.sldp/ccc0.jpg')
    assert m.unloaded==['file:///mnt/mmc/.sldp/aaa0.jpg','file:///mnt/mmc/.sldp/bbb0.jpg']; passed()
    # Album covers past the first screen: after the list moves, covers are requested from just
    # above the first visible row (46 px rows, not the app's 78), and visible rows still on the
    # placeholder are re-bound (every 200 ms) when their album becomes ready, for up to 6 s.
    m=Machine(); tc=m.page('album_page','table_client'); m.word(tc+0x48,m.top); m.nodes[m.top]['type']='window'
    m.word(tc+0x0c,218); m.word(tc+0x78,46); m.word(tc+0x7c,300); m.word(tc+0x80,46*20)
    APP=0x1100000; m.handlers[APP]='app_load'; m.call(address=0x5ca984,args=(tc,APP,0xc7c7,0))
    rows=[]
    for k in range(5):
        row=m.node('table_row'); rect(m,row,(0,46*(20+k),365,46)); m.word(row+0x48,tc); m.word(row+0x78,20+k)
        btn=m.entry(row); m.nodes[btn].update(type='button',style='s_btn_listitem'); rect(m,btn,(20,0,335,70))
        m.nodes[row]['children']=[btn]; icon=kid(m,btn,'image',(48,0,50,70),name='img_icon',image='default_album_small')
        kid(m,btn,'hscroll_label',(72,14,200,24)); rows.append((row,icon))
    m.nodes[tc]['children']=[r for r,_ in rows]
    m.on_load=lambda ctx,i,r: m.nodes[[ic for rr,ic in rows if rr==r][0]].update(image=('file:///mnt/mmc/.sldp/%03d0.jpg'%i) if i in m.cover_ready else 'default_album_small')
    m.paint(tc); m.idle(); assert m.cover_asks==[(18,12)] and m.cover_timer
    m.paint(tc); m.idle(); assert m.cover_asks==[(18,12)]  # same start: not asked again
    m.cover_ready={20,21}; assert m.run(0,m.cover_timer,(0,0,0,0),0x114,200)==8
    assert [m.nodes[ic]['image'] for _,ic in rows]==['file:///mnt/mmc/.sldp/0200.jpg','file:///mnt/mmc/.sldp/0210.jpg']+['default_album_small']*3
    assert m.run(0,m.cover_timer,(0,0,0,0),0x114,11000)==7; passed()  # gives up after the wait
    # Grid view: big covers requested from the row above the first visible one (3 albums a row);
    # a row whose tiles are still grey is re-bound once one of its albums' big cover is done.
    m=Machine(); tc=m.page('album_page','table_client'); m.word(tc+0x48,m.top); m.nodes[m.top]['type']='window'
    m.word(tc+0x0c,218); m.word(tc+0x78,160); m.word(tc+0x7c,100); m.word(tc+0x80,160*10)
    APP=0x1100000; m.handlers[APP]='app_load'; m.call(address=0x5ca984,args=(tc,APP,0xc7c7,0))
    grows=[]
    for k in range(2):
        row=m.node('table_row'); rect(m,row,(0,160*(10+k),365,160)); m.word(row+0x48,tc); m.word(row+0x78,10+k)
        tiles=[]
        for t in range(3):
            b=m.entry(row); m.nodes[b].update(type='button'); rect(m,b,(t*120,0,110,150))
            tiles.append(kid(m,b,'image',(0,0,110,110),name='img_icon%d'%(t+1),image='default_album_big'))
        m.nodes[row]['children']=[m.get(ti+0x48) for ti in tiles]; grows.append((row,tiles))
    m.nodes[tc]['children']=[r for r,_ in grows]
    def gbind(ctx,i,r):
        for t,ti in enumerate(dict(grows)[r]):
            a=i*3+t; m.nodes[ti]['image']='file:///mnt/mmc/.sldp/%03d1.jpg'%a if a in m.big_ready else 'default_album_big'
    m.on_load=gbind; m.paint(tc); m.idle(); assert m.cover_asks==[('big',27,12)]
    m.big_ready={31}; assert m.run(0,m.cover_timer,(0,0,0,0),0x114,200)==8
    assert [m.nodes[ti]['image'] for ti in grows[0][1]]==['default_album_big','file:///mnt/mmc/.sldp/0311.jpg','default_album_big']
    assert [m.nodes[ti]['image'] for ti in grows[1][1]]==['default_album_big']*3; passed()  # row 11 (albums 33-35) not ready
    # Album grid: each of a row's three tiles is its own wheel stop (ids row*3+tile); the selected
    # tile's cover gets a pink 4 px frame; moving past the third tile goes to the next row.
    m=Machine(); tc=m.page('album_page','table_client'); m.word(tc+0x48,m.top); m.nodes[m.top]['type']='window'
    m.word(tc+0x0c,218); m.word(tc+0x78,160); m.word(tc+0x7c,20); m.word(tc+0x80,0)
    tiles=[]
    for k in range(2):
        row=m.node('table_row'); rect(m,row,(0,160*k,365,160)); m.word(row+0x48,tc); m.word(row+0x78,k)
        for t in range(3):
            b=m.entry(row); m.nodes[b].update(type='button'); rect(m,b,(8+t*120,0,110,150)); m.word(b+0x48,row)
            m.nodes[row]['children'].append(b); kid(m,b,'image',(0,0,110,110),name='img_icon%d'%(t+1)); tiles.append(b)
        m.nodes[tc]['children'].append(row)
    m.paint(tc); m.idle(); assert m.selected(tc)==0 and m.nodes[tiles[0]].get('_ipod_gsel')==1
    assert m.call(173)==11 and m.selected(tc)==1 and m.nodes[tiles[1]].get('_ipod_gsel')==1 and m.nodes[tiles[0]].get('_ipod_gsel')==0
    m.call(173); m.call(173); assert m.selected(tc)==3 and m.nodes[tiles[3]].get('_ipod_gsel')==1
    m.fills=[]; m.paint(tiles[3]); assert len(m.fills)==4 and all(f[4]==0xff482dfa for f in m.fills)
    assert (0,0,110,4,0xff482dfa) in m.fills; passed()
    # Play All: from the first song, rest, then one more detent up focuses the bar (its pink pill on,
    # icon white, list pill off); centre plays all; a detent down returns; a fast spin up stops at
    # the first song. The app's 50 px icon and label are fitted to the 40 px bar.
    def playall_page():
        m=Machine(); w=m.page('albuminfo_page'); m.word(w+0x0c,178); m.word(w+0x48,m.top)
        btns=[]
        for i in range(4):
            row=m.node('list_item'); rect(m,row,(0,i*30,375,30)); m.word(row+0x48,w)
            b=m.entry(row); m.nodes[b].update(type='button',style='s_btn_listitem'); rect(m,b,(20,0,335,70))
            m.nodes[row]['children']=[b]; kid(m,b,'hscroll_label',(72,0,200,70)); btns.append(b)
        m.nodes[w]['children']=[m.get(b+0x48) for b in btns]
        bar=m.node('view',name='view_navbar_allplay'); rect(m,bar,(0,42,375,40)); m.word(bar+0x48,m.top)
        allb=m.entry(bar); m.nodes[allb].update(type='image',style='s_img_allplay_navbar'); rect(m,allb,(20,0,100,50))
        lab=m.node('hscroll_label'); rect(m,lab,(70,0,130,50))
        allsel=m.node('view',name='ipod_allsel',visible=0); rect(m,allsel,(6,43,363,38)); m.word(allsel+0x48,m.top)
        order=m.node('image',style='s_img_order_navbar'); rect(m,order,(305,0,50,50)); m.word(order+0x48,bar)
        m.nodes[bar]['children']=[lab,allb,order]; m.word(lab+0x48,bar); m.word(allb+0x48,bar)  # the app's own children only
        m.nodes[m.top]['children'][0:0]=[allsel,bar]; m.paint(w); m.idle()
        m.order=order
        return m,w,btns,bar,allb,allsel,lab
    m,w,btns,bar,allb,allsel,lab=playall_page()
    assert m.call(172,gap=1000)==11 and m.nodes[w].get('_ipod_head')==1  # resting at the first song: one detent up
    assert m.nodes[allsel]['visible']==1 and m.nodes[allb]['style']=='ipod_allplayfocus' and m.nodes[btns[0]]['style']=='s_btn_listitem'
    assert got(allb)==(20,-5,100,50) and got(m.order)==(305,-5,50,50) and got(lab)==(70,0,130,40)  # glyphs centred on the 40 px bar
    assert m.nodes[m.order]['style']=='ipod_orderfocus'  # the sort icon turns white on the pill
    clicked=[]; m.on_click=lambda a,b_: clicked.append(a); assert m.call(218)==11 and clicked==[allb]
    assert m.call(173)==11 and not m.nodes[w].get('_ipod_head') and m.selected(w)==0 and m.nodes[btns[0]]['style']=='ipod_sel'
    assert m.nodes[allsel]['visible']==0 and m.nodes[allb]['style']=='s_img_allplay_navbar'  # pill off, pink icon back
    assert m.nodes[m.order]['style']=='s_img_order_navbar' and got(allb)==(20,-5,100,50)
    def spun_to_top():
        m,w,btns,bar,allb,allsel,lab=playall_page()
        for _ in range(3): m.call(173,gap=1000)
        for _ in range(6): m.call(172,gap=80)  # a spin up: 3 moves, then 3 overshoot detents at the top
        assert not m.nodes[w].get('_ipod_head') and m.selected(w)==0  # the spin stops at the first song
        return m,w
    m,w=spun_to_top(); m.call(172,gap=260); m.call(172,gap=150)  # V9.7d log: a short pause, then a separate turn
    assert m.nodes[w].get('_ipod_head')==1
    m,w=spun_to_top(); m.call(172,gap=25000)  # V9.8d log: a long rest, then a turn whose detents come 73 ms apart
    assert m.nodes[w].get('_ipod_head')==1
    m,w=spun_to_top()
    for _ in range(3): m.call(172,gap=85)  # V9.8d log: turning on at the top; 480 ms after arriving: not yet
    assert not m.nodes[w].get('_ipod_head')
    m.call(172,gap=85); assert m.nodes[w].get('_ipod_head')==1; passed()  # past 500 ms
    # Rows rebuilt in code (Bluetooth while pairing) are restyled right after the stock layout of
    # the page's list, before any paint: no frame of the stock row.
    m=Machine(); w=m.page('bluetooth_page'); m.word(w+0x0c,210); m.word(w+0x48,m.top)
    row=m.node('list_item'); rect(m,row,(0,0,375,30)); m.word(row+0x48,w)
    b=m.entry(row); m.nodes[b].update(type='button',style='s_btn_listitem'); rect(m,b,(20,0,335,70))
    m.nodes[row]['children']=[b]; m.nodes[w]['children']=[row]; lab=kid(m,b,'hscroll_label',(72,0,200,70))
    m.nodes[w]['_ringnav_index']=0; m.nodes[w]['_ringnav_count']=1  # the selection from before the rebuild
    m.nodes[w]['_ipod_styled']=1  # the page was shown (and styled) before the app rebuilt its rows
    assert m.run(0,0x6461b0,(w,0,0,0),0x114,0)==0 and m.layouts==[w]
    assert got(b)==pill(375,30) and m.nodes[b]['style']=='ipod_sel' and not m.idles
    other=m.node('view'); m.run(0,0x6461b0,(other,0,0,0),0x114,0); assert m.layouts[-1]==other; passed()  # others: stock only
    # Home while it is still being built: the full-row tap images have no click handler yet. A
    # layout pass must not style an unstyled page, and styling must never hide those tap images.
    m=Machine(); w=m.page('home_page'); m.word(w+0x0c,218); m.word(w+0x48,m.top)
    rows=[]
    for i in range(3):
        row=m.node('list_item'); rect(m,row,(0,i*30,215,30)); m.word(row+0x48,w)
        btn=m.node('button',style='s_btn_listitem'); rect(m,btn,(0,0,215,30)); m.word(btn+0x48,row)
        m.nodes[row]['children']=[btn]; kid(m,btn,'label',(12,0,155,30),style='s_label_white20l')
        kid(m,btn,'image',(173,0,24,30),image='list_into')
        hit=kid(m,btn,'image',(0,0,215,30),name='img_x%d'%i)  # no emitter: not clickable yet
        rows.append((row,btn,hit))
    m.nodes[w]['children']=[r[0] for r in rows]
    m.run(0,0x6461b0,(w,0,0,0),0x114,0); assert all(m.nodes[h]['visible'] for _,_,h in rows) and 'style' in m.nodes[rows[0][1]] and m.nodes[rows[0][1]]['style']=='s_btn_listitem'
    assert not m.calls or not [c for c in m.calls if c[0] in ('widget_move_resize','widget_use_style','widget_set_prop_int')]  # untouched
    m.paint(w); m.idle(); assert all(m.nodes[h]['visible'] for _,_,h in rows)  # tap images kept
    for _,_,h in rows:  # the app attaches its handlers
        em=m.alloc(4); it=m.alloc(0x28); m.word(h+0x60,em); m.word(em,it); m.word(it+8,0x10c)
    m.paint(w); m.idle(); assert m.nodes[rows[0][1]]['style']=='ipod_sel'
    assert m.call()==11 and m.nodes[rows[1][1]]['style']=='ipod_sel'; passed()
    # DVC-style Bluetooth volume: with a headset streaming and taking absolute volume (AirPods), the
    # player's stream stays at full scale and the level (0-100 -> 0-127) goes to the headset; the
    # same level is not re-sent; otherwise the stock gain path is untouched.
    m=Machine(); bt=0x5accec
    m.run(0,bt,(40,40,0,0),0x114,0); assert m.btvols==[(40,40)] and not m.bt_sets  # Bluetooth off
    for g in ('g_bluetoothflag','bt_linkstatus'): m.byte(syms[g],1)
    m.word(syms['bt_showcoding'],2); m.bt_abs=64
    m.run(0,bt,(40,40,0,0),0x114,0); assert m.btvols[-1]==(100,100) and m.bt_sets==[51]
    m.run(0,bt,(40,40,0,0),0x114,0); assert m.bt_sets==[51] and m.btvols[-1]==(100,100)  # unchanged: not re-sent
    m.run(0,bt,(100,100,0,0),0x114,0); m.run(0,bt,(0,0,0,0),0x114,0); assert m.bt_sets==[51,127,0]
    m.bt_abs=0xff; m.run(0,bt,(30,30,0,0),0x114,0); assert m.btvols[-1]==(30,30)  # no absolute volume
    m.bt_abs=10; m.word(syms['bt_showcoding'],0); m.run(0,bt,(30,30,0,0),0x114,0); assert m.btvols[-1]==(30,30); passed()
    # Headset connect card: when a Bluetooth headset links, a card shows its picture (AirPods art for
    # an AirPods name), name and "Connected"; not again while it stays linked; a key or the timer
    # closes it (the key is taken); another headset gets the headphones art.
    m=Machine(); w=m.page(); m.paint(w); assert m.bt_poll
    def pair(name,mac):
        it=m.alloc(0x80); m.u.mem_write(it+4,mac.encode()+b'\0'); m.u.mem_write(it+0x24,name.encode()+b'\0'); return it
    m.bt_pairs=[pair('Other','11:22'),pair("Sam's AirPods Pro",'AA:BB')]; m.word(syms['pdeq_btpairlist'],0x2222)
    m.bt_links=[(3,'AA:BB')]
    tick=lambda: m.run(0,m.bt_poll,(0,0,0,0),0x114,1000)
    m.byte(syms['g_bluetoothflag'],1)
    assert tick()==8 and not [c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_btcard']  # not linked yet
    for g in ('g_bluetoothflag','bt_linkstatus'): m.byte(syms[g],1)
    tick()  # linked (bt_connectstatus stays 0, as logged on the device)
    AAPTH=int(manifest['patch_symbols']['ringnav_aap_thread'],16); AVTH=int(manifest['patch_symbols']['ringnav_avrcp_thread'],16)
    assert m.threads.count(AAPTH)==1 and m.threads.count(AVTH)==1  # AirPods: a battery reader and a button reader per link
    cards=[c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_btcard']; assert len(cards)==1
    assert got(cards[0])==(0,96,375,224) and m.nodes[cards[0]].get('style:normal:round_radius')=='40'  # a bottom sheet with the screen's corners
    kids=m.nodes[cards[0]]['children']
    assert [m.nodes[k].get('image') for k in kids if m.nodes[k]['type']=='image']==['tidal_shangling_big']
    assert [m.nodes[k].get('wtext') for k in kids if m.nodes[k]['type']=='label']==["Sam's AirPods Pro",'Connected']
    tick(); assert len([c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_btcard'])==1  # still linked: no second card
    assert m.call(173)==11 and m.closed==[cards[0]]  # a key closes it and is taken
    m.byte(syms['bt_linkstatus'],0); tick(); m.bt_links=[(3,'11:22')]; m.byte(syms['bt_linkstatus'],1); tick()
    card=[c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_btcard'][0]
    assert [m.nodes[k].get('image') for k in m.nodes[card]['children'] if m.nodes[k]['type']=='image']==['tidal_shanling']
    assert m.threads.count(AAPTH)==1  # not AirPods: no battery read
    # Battery (stage 2): once the AirPods report, the grey line shows the parts present, ⚡ when
    # charging; the card closes itself after 5 s.
    aap=int(manifest['patch_symbols']['aap'],16)
    sub=[k for k in m.nodes[card]['children'] if m.nodes[k].get('name')=='ipod_btcard_sub'][0]
    assert m.run(0,m.card_tick,(0,0,0,0),0x114,300)==8 and m.nodes[sub]['wtext']=='Connected'  # no report yet
    for i,(lv,st) in enumerate([(100,1),(97,2),(90,2)]): m.word(aap+8+4*i,lv); m.word(aap+20+4*i,st)
    m.word(aap+4,1)
    assert m.run(0,m.card_tick,(0,0,0,0),0x114,300)==8 and m.nodes[sub]['wtext']=='L 100%\u26a1  \u00b7  R 97%  \u00b7  Case 90%', m.nodes[sub]['wtext']
    m.word(aap+20+4*2,4); m.word(aap+4,2)  # case absent
    m.run(0,m.card_tick,(0,0,0,0),0x114,300); assert m.nodes[sub]['wtext']=='L 100%\u26a1  \u00b7  R 97%'
    assert m.run(0,m.card_tick,(0,0,0,0),0x114,5000)==7 and m.closed[-1]==card; passed()
    # Ear detection: one AirPod out pauses, back in resumes; both out, then both back, resumes too; a
    # play or pause by hand wins; the first report after linking is only the starting state.
    m=Machine(); w=m.page(); m.paint(w)
    m.bt_pairs=[pair("AirPods Pro",'AA:BB')]; m.word(syms['pdeq_btpairlist'],0x2222); m.bt_links=[(3,'AA:BB')]
    for g in ('g_bluetoothflag','bt_linkstatus'): m.byte(syms[g],1)
    tick=lambda: m.run(0,m.bt_poll,(0,0,0,0),0x114,400)
    tick(); assert m.threads.count(AAPTH)==1
    def ear(a,b): m.word(aap+32,a); m.word(aap+36,b); m.word(aap+40,m.get(aap+40)+1); tick()
    ear(1,0); assert m.toggles==0  # starting state: one bud in
    ear(0,0); assert m.toggles==0  # putting one in never starts playback
    ear(0,1); assert m.toggles==1 and m.play_status==3  # one out: paused
    ear(0,2); assert m.toggles==1  # into the case: still out
    ear(0,0); assert m.toggles==2 and m.play_status==2  # back in: resumed
    ear(1,0); ear(1,1); assert m.toggles==3 and m.play_status==3  # both out: paused
    ear(1,0); assert m.toggles==3; ear(0,0); assert m.toggles==4 and m.play_status==2  # both back: resumed
    m.play_status=2; tick(); ear(0,1); m.play_status=2; ear(0,0); assert m.toggles==5  # played by hand: no resume toggle
    m.play_status=3; ear(1,0); ear(0,0); assert m.toggles==5  # paused by hand: left alone
    # The AirPods pause by themselves (AVRCP) before their ear report arrives: still resumed, even
    # after both came out.
    avr=int(manifest['patch_symbols']['avrcp'],16); AVIDLE=int(manifest['patch_symbols']['avrcp_idle'],16)
    m.play_status=2; hd=m.get(avr+4); m.word(avr+12+4*(hd%8),201); m.word(avr+4,hd+1)
    m.run(0,AVIDLE,(0,0,0,0),0x114,0); assert m.toggles==6 and m.play_status==3
    ear(0,1); ear(1,1); assert m.toggles==6; ear(0,0); assert m.toggles==7 and m.play_status==2
    # The headset going (AirPods into the case) pauses, so a reconnect in the open case stays quiet.
    m.byte(syms['bt_linkstatus'],0); tick(); assert m.toggles==8 and m.play_status==3
    m.byte(syms['bt_linkstatus'],1); tick()
    m.play_status=2; ear(0,1); assert m.toggles==8  # relinked: the first report is the state
    m.play_status=3; m.byte(syms['bt_linkstatus'],0); tick(); assert m.toggles==8  # already paused: left
    # Connecting in the case: the stock resumes on connect, but with no bud in an ear it is paused as
    # soon as the AirPods say so (also later, whatever starts it); one bud in an ear plays.
    m.byte(syms['bt_linkstatus'],1); tick(); m.play_status=2
    ear(2,2); assert m.toggles==9 and m.play_status==3  # both in the case
    m.play_status=2; tick(); assert m.toggles==10 and m.play_status==3  # started again: paused again
    ear(0,2); assert m.toggles==10 and m.play_status==3  # one in an ear: no auto-start...
    m.play_status=2; tick(); assert m.toggles==10; passed()  # ...but playing is allowed
    # Headset buttons: per link a thread finds the "(AVRCP)" input device BlueZ makes, reads key
    # presses and queues them to the UI thread: next/previous, and play/pause only when it changes.
    m=Machine(); th=int(manifest['patch_symbols']['ringnav_avrcp_thread'],16); avr=int(manifest['patch_symbols']['avrcp'],16)
    m.byte(syms['bt_linkstatus'],1); m.word(avr,1)
    m.inputs={'/dev/input/event1':(31,'gpio-keys'),'/dev/input/event4':(34,'AirPods Pro (AVRCP)')}
    ev=lambda code,val: struct.pack('<IIHHi',0,0,1,code,val)
    m.evq=[ev(163,1)+ev(163,0)+struct.pack('<IIHHi',0,0,0,0,0), ev(200,1)+ev(200,0), ev(201,1), ev(165,1)+ev(164,1)]
    m.run(0,th,(0,0,0,0),0x114,0)
    assert '/dev/input/event1' in m.opened and m.inputs_closed[0]==31 and m.inputs_closed[-1]==34  # event1 checked and left; event4 read, closed at the end
    assert m.get(avr)==0 and len(m.queued)==4 and m.get(avr+4)==5  # 5 presses queued, releases ignored; running cleared
    m.play_status=2; m.run(0,m.queued[0],(0,0,0,0),0x114,0)
    assert m.player==['next','prev'] and m.toggles==2 and m.play_status==2 and m.get(avr+8)==5
    # play while playing does nothing; pause pauses; play resumes (whatever the second path did)
    idle=m.queued[0]; m=Machine(); m.word(avr+4,4); [m.word(avr+12+4*i,c) for i,c in enumerate((200,201,201,200))]; m.play_status=2
    m.run(0,idle,(0,0,0,0),0x114,0); assert m.toggles==2 and m.play_status==2 and m.get(avr+8)==4
    passed()
    # Boot to Home: the resume call in home_page_init is pointed at ringnav_boot_play, which starts
    # the remembered queue the way Now Playing's init would (and sets the same two globals).
    assert manifest['hooks']['boot_resume']['address']=='0x523de0' and manifest['hooks']['boot_resume']['original']=='09f82003'
    m=Machine(); bp=int(manifest['patch_symbols']['ringnav_boot_play'],16)
    ctx=m.alloc(16); [m.word(ctx+4*i,v) for i,v in enumerate((0x5550,12,7,2))]  # stock would resume playing (2): paused instead
    m.run(0,bp,(0x777,ctx,0,0),0x114,0)
    assert m.player==[('start',0x5550,12,7,3)] and m.u.mem_read(0xa3a6c1,1)==b'\0' and m.u.mem_read(0x99f660,1)==b'\x28'
    m.player=[]; m.word(ctx+8,0xff); m.run(0,bp,(0x777,ctx,0,0),0x114,0); assert m.player==[]; passed()
    # Theme colour: pink blends map to the accent (style colours as returned, and images as decoded,
    # not file:// covers or immutable ones); other colours are untouched. System Setting gets a
    # "Theme Colour" row cycling the accents, saving the choice and reloading images; a saved choice
    # applies from the first colour looked up.
    acc=int(manifest['patch_symbols']['accent'],16)
    def colour(m,c):
        m.style_color=c; out=m.alloc(4); m.run(0,0x649f6c,(out,0x1234,0x5678,0),0x114,0); return m.get(out)
    near=lambda x,y,t=2: all(abs(((x>>s_)&255)-((y>>s_)&255))<=t for s_ in (0,8,16,24))
    m=Machine()
    assert colour(m,0xff482dfa)==0xff482dfa and m.get(acc+4)==1 and m.unloads==0  # pink: as is; nothing saved
    m.word(acc,6)  # blue
    assert near(colour(m,0xff482dfa),0xffff840a) and near(colour(m,0x80482dfa),0x80ff840a)  # alpha kept
    assert near(colour(m,0xffa496fc),0xffffc184)  # a pink/white blend: the blue/white blend
    assert [colour(m,c) for c in (0xffffffff,0xff0000ff,0xff2e2c2c,0xff000000,0x00000000)]==[0xffffffff,0xff0000ff,0xff2e2c2c,0xff000000,0x00000000]
    bm=m.alloc(32); data=m.alloc(16); nm=m.alloc(40)
    def img(name,fmt,px,flags=0):
        m.word(bm,4); m.word(bm+4,1); m.word(bm+8,16); m.u.mem_write(bm+0xc,struct.pack('<HH',flags,fmt)); m.word(bm+20,data)
        m.u.mem_write(data,bytes(px)); m.u.mem_write(nm,name.encode()+b'\0'); m.run(0,0x6445d4,(0x1000900,nm,bm),0x114,0)
        return list(m.u.mem_read(data,16))
    px=img('navbar_home',1,[250,45,72,255, 255,255,255,255, 255,0,0,255, 125,22,36,128])
    assert abs(px[0]-10)<=2 and abs(px[1]-132)<=2 and px[2]>=253 and px[3]==255, px  # pink -> blue
    assert px[4:12]==[255,255,255,255, 255,0,0,255]  # white and red untouched
    assert abs(px[12]-5)<=2 and abs(px[13]-66)<=2 and abs(px[14]-128)<=2 and px[15]==128, px  # premultiplied half pink
    assert m.imgadds[-1]==('navbar_home',bm)
    px=img('switch_on',3,[72,45,250,255]+[0]*12); assert px[0]>=253 and abs(px[1]-132)<=2 and abs(px[2]-10)<=2  # BGRA
    assert img('file:///tmp/coverpic.jpg',1,[250,45,72,255]+[0]*12)[:4]==[250,45,72,255]  # album art: never
    px=img('navbar_home',1,[250,45,72,255]+[0]*12,flags=2); assert abs(px[0]-10)<=2  # 'immutable', as every decoded image is
    # Display setting gets a "Theme Colour" row (once) that opens the picker: a page of the nine
    # accents, the current one selected; picking applies and saves; picking the current one again, or
    # the back arrow, closes it; each row's dot is drawn in its own colour, the current one ringed.
    m=Machine(); items=[m.node('list_item',name=str(i)) for i in range(3)]
    sv=m.node('scroll_view',name='scroll_view_display',children=items); lv=m.node('list_view',name='list_view_display',children=[sv])
    win=m.node('window',name='display_page',children=[lv]); m.word(sv+0x48,lv); m.top=win
    m.run(0,0x682ee8,(0x3000,0x3004,0,win),0x114,0); m.run(0,0x682ee8,(0x3000,0x3004,0,win),0x114,0)
    rows=m.nodes[sv]['children']; assert len(rows)==4 and m.nodes[rows[3]]['style']=='s_listitem_black' and got(rows[3])[1]==90
    btn=m.nodes[rows[3]]['children'][0]; kids=m.nodes[btn]['children']
    assert m.nodes[btn]['name']=='ipod_accent' and m.nodes[btn]['style']=='s_btn_listitem'
    assert [m.nodes[k].get('wtext') for k in kids if m.nodes[k]['type']=='hscroll_label']==['Theme Colour']
    assert [m.nodes[k].get('image') for k in kids if m.nodes[k]['type']=='image']==['tidal_album']
    on=[o for o in m.ons if o[0]==btn and o[1]==0x10c]; assert len(on)==1
    m.word(acc+4,1); m.word(acc,2)  # orange now
    m.run(0,on[0][2],(0,0,0,0),0x114,0); m.run(0,on[0][2],(0,0,0,0),0x114,0)
    pages=[c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_accent_page']; assert len(pages)==1  # opened once
    page=pages[0]; assert got(page)==(0,30,375,290) and m.nodes[page].get('open_anim_hint','').startswith('htranslate')
    def walk(n):
        for c in m.nodes[n]['children']: yield c; yield from walk(c)
    psv=[c for c in walk(page) if m.nodes[c]['type']=='scroll_view'][0]
    assert m.nodes[psv].get('yslidable')=='true' and m.nodes[psv].get('_ringnav_index')==2  # the current colour selected
    pbtns=[c for c in walk(psv) if m.nodes[c]['type']=='button']
    assert [m.nodes[[k for k in m.nodes[b]['children'] if m.nodes[k]['type']=='hscroll_label'][0]]['wtext'] for b in pbtns]==\
        ['Pink','Red','Orange','Green','Seafoam','Teal','Blue','Indigo','Purple']
    assert [m.nodes[b].get('_ipod_swatch') for b in pbtns]==list(range(1,10))
    title=[c for c in walk(page) if m.nodes[c]['type']=='hscroll_label' and m.nodes[c].get('wtext')=='Theme Colour']; assert len(title)==1
    picks={o[0]:o for o in m.ons if o[1]==0x10c}
    blue=picks[pbtns[6]]; m.run(0,blue[2],(blue[3],0,0,0),0x114,0)
    assert m.get(acc)==6 and m.files['/mnt/data/ipod_accent']=='6' and m.unloads==1 and page not in m.closed  # applied, saved, still open
    m.vg=[]; m.paint(pbtns[6])
    assert ('vgcanvas_set_fill_color',0xffff840a) in m.vg and ('vgcanvas_stroke',) in m.vg  # its blue dot, ringed: current
    m.vg=[]; m.paint(pbtns[0]); assert ('vgcanvas_set_fill_color',0xff482dfa) in m.vg and ('vgcanvas_stroke',) not in m.vg  # pink, exactly
    m.run(0,blue[2],(blue[3],0,0,0),0x114,0); assert m.closed[-1]==page and m.get(acc)==6  # the current again: back
    def reopen():
        m.run(0,on[0][2],(0,0,0,0),0x114,0)
        return [c for c in m.nodes[m.wm]['children'] if m.nodes[c].get('name')=='ipod_accent_page'][-1]
    page=reopen(); back=[c for c in walk(page) if m.nodes[c].get('style')=='s_img_return'][0]
    picks={o[0]:o for o in m.ons if o[1]==0x10c}; n=len(m.closed)
    m.run(0,picks[back][2],(0,0,0,0),0x114,0); assert m.closed[-1]==page and len(m.closed)==n+1  # the back arrow
    page=reopen(); keyup=[o for o in m.ons if o[0]==page and o[1]==0x114]; assert len(keyup)==1  # the wheel's back key
    m.run(0xab,keyup[0][2],(0,m.event,0,0),0x114,0); assert len(m.closed)==n+1  # play/pause: not back
    m.run(0xaa,keyup[0][2],(0,m.event,0,0),0x114,0); assert m.closed[-1]==page and len(m.closed)==n+2
    lst=[c for c in walk(page) if m.nodes[c]['type']=='list_view'][0]; assert got(lst)==(0,42,375,232)  # clear of the corners
    # Backgrounds (widget_fill_rect) come as gradients: style_get_gradient jumps to the patch, which
    # calls the style's own get_gradient and maps the stops in the caller's copy.
    m=Machine(); m.word(acc+4,1)
    style=m.alloc(8); vt=m.alloc(0x20); m.word(style,vt); m.word(vt+0x18,0x1000840); out=m.alloc(0x50)
    grad=lambda: m.run(0,0x649f3c,(style,0x5678,out,0),0x114,0)
    m.grad=[0xff482dfa,0xffffffff]; assert grad()==out and m.get(out+0xc)==0xff482dfa  # pink theme: as is
    m.word(acc,6); assert grad()==out and m.get(out+8)==2 and near(m.get(out+0xc),0xffff840a) and m.get(out+0x14)==0xffffffff
    m.grad=None; assert grad()==0x1000860  # not the caller's copy: returned, untouched
    assert m.run(0,0x649f3c,(0,0x5678,out,0),0x114,0)==0  # no style
    m=Machine(); m.files['/mnt/data/ipod_accent']='6'
    assert near(colour(m,0xff482dfa),0xffff840a) and m.unloads==0  # saved blue: from the start
    m=Machine(); m.files['/mnt/data/ipod_accent']='6'; bm=m.alloc(32); data=m.alloc(16); nm=m.alloc(40)
    px=img('navbar_home',1,[250,45,72,255]+[0]*12); assert abs(px[0]-10)<=2; passed()  # an image first: also blue
    # Headset volume (AirPods swipes): the Q2 follows. The first read on a link is the starting point;
    # a change sets the app's level byte and calls device_set_volume; with the screen on the volume
    # HUD opens, or its slider moves if it is open; with the screen off it only follows.
    m=Machine(); w=m.page(); m.paint(w)
    for g in ('g_bluetoothflag','bt_linkstatus','g_backlight_status'): m.byte(syms[g],1)
    m.word(syms['bt_showcoding'],2); m.bt_abs=100
    tick=lambda: m.run(0,m.bt_poll,(0,0,0,0),0x114,400)
    tick(); assert m.volsets==[] and m.navs==[]
    m.bt_abs=76; tick()
    assert m.u.mem_read(0xa38c41,1)==bytes([60]) and m.volsets==[(60,1)] and m.navs==['dialog/volume_dialog'], (m.volsets,m.navs)
    tick(); assert len(m.volsets)==1  # no change: nothing
    slider=m.node('slider',name='slider_vol'); m.top=m.node('dialog','volume_dialog',[slider])
    m.bt_abs=124; tick(); assert m.volsets[-1]==(98,1) and len(m.navs)==1 and m.nodes[slider].get('value')==98
    m.byte(syms['g_backlight_status'],0); m.top=w; m.bt_abs=40; tick()
    assert m.volsets[-1]==(31,1) and len(m.navs)==1  # screen off: follows, no HUD
    m.byte(syms['bt_linkstatus'],0); tick(); m.byte(syms['bt_linkstatus'],1); m.bt_abs=90; tick()
    assert m.volsets[-1]==(31,1); passed()  # a new link starts from the headset's level
    # AirPods battery and ear detection: the thread connects L2CAP PSM 0x1001 to the linked AirPods,
    # sends the handshake and notification request (no feature flags), and keeps reading battery and
    # ear reports until the headset goes.
    m=Machine(); th=int(manifest['patch_symbols']['ringnav_aap_thread'],16)
    m.bt_links=[(3,'AA:BB:CC:DD:EE:0F')]; m.byte(syms['bt_linkstatus'],1)
    rep=bytes([4,0,4,0,4,0,3, 0x04,1,80,2,1, 0x02,1,75,2,1, 0x08,1,40,1,1])
    setup=[bytes([4,0,4,0,0x09,0,0x0d,3,0,0,0])]*12  # as logged: a dozen setup packets come first
    m.rx=[bytes([4,0,4,0,0x2b,0,1,2])]+setup+[bytes([4,0,4,0,6,0,0,1]), rep, bytes([4,0,4,0,4,0,1, 0x04,1,10,2,1])]
    m.run(0,th,(0,0,0,0),0x114,0)
    assert not m.rx  # read on while linked
    assert m.sock==(31,5,0) and m.sock_addr[:4]==bytes([31,0,0x01,0x10]) and m.sock_addr[4:10]==bytes([0x0f,0xee,0xdd,0xcc,0xbb,0xaa])
    assert m.sent==[bytes([0,0,4,0,1,0,2,0]+[0]*8), bytes([4,0,4,0,0x4d,0,0xd7]+[0]*7), bytes([4,0,4,0,0x0f,0,0xff,0xff,0xff,0xff])]  # feature flags: ear reports
    aap=int(manifest['patch_symbols']['aap'],16)
    lv=[m.get(aap+8+4*i) for i in range(3)]; stt=[m.get(aap+20+4*i) for i in range(3)]
    assert lv==[10,75,40] and stt==[2,2,1] and m.socks_closed==[7] and m.get(aap)==0, (lv,stt)  # the latest report
    assert [m.get(aap+32),m.get(aap+36),m.get(aap+40)]==[0,1,1]  # ear: one in, one out
    if DUMP:  # the thread only records; the UI thread's Bluetooth poll writes the file
        assert '/mnt/mmc/q2aap.txt' not in m.files
        m.paint(m.node('view')); m.run(0,m.bt_poll,(0,0,0,0),0x114,1000)
        assert 'battery L80/2 R75/2 C40/1' in m.files['/mnt/mmc/q2aap.txt'] and '8:04000400' in m.files['/mnt/mmc/q2aap.txt']
    # Quiet AirPods: it waits while linked and closes when the link drops.
    m=Machine(); m.bt_links=[(3,'AA:BB:CC:DD:EE:0F')]; m.byte(syms['bt_linkstatus'],1); m.link_left=10
    m.run(0,th,(0,0,0,0),0x114,0); assert m.socks_closed==[7] and m.get(aap)==0 and m.selects==10
    passed()
    # The tinted background follows the cover art (file:// only), without re-setting it each sync.
    m=Machine(); cover=m.node('image',name='img_cover',image='file:///tmp/coverpic.jpg')
    bg=m.node('image',name='img_artbg',image=''); bar=m.node('slider',name='slider_play')
    m.top=m.node('window','playing_page',[bg,cover,bar])
    m.paint(bar); m.idle(); assert m.nodes[bg]['image']=='file:///tmp/coverpic.jpg'
    m.paint(bar); assert not [c for c in m.idle() if c[0]=='widget_set_prop_str']
    m.nodes[cover]['image']='play_defaultcover'; m.paint(bar); m.idle(); assert m.nodes[bg]['image']==''; passed()
print(f'{checks} MIPS execution scenarios passed; toolkit services mocked, stock lock filter executed.')
