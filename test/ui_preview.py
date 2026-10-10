#!/usr/bin/env python3
"""Compose native-size review sheets; these are layout illustrations, not AWTK captures.
Usage: python3 test/ui_preview.py [--themes BEFORE,AFTER] BEFORE_BUILD AFTER_BUILD OUTPUT [BEFORE_CF AFTER_CF]
Each side is drawn in an iPod Theme, classic or minimal (default classic,minimal); one build passed
twice compares its two themes. Uses the existing ImageMagick dependency and the original firmware's
native font/assets.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, sys.path[0] + '/../tools')
from ipod import (decode, walk, imagemagick, png_header, HOME_TEXT_X, HOME_LIST_W,
                  HOME_LABEL_END, HOME_ROW, HOME_TOP, INC, inc)

argv = sys.argv[1:]
themes = ['classic', 'minimal']
if argv[:1] == ['--themes']: themes, argv = argv[1].split(','), argv[2:]
assert len(themes) == 2 and set(themes) <= {'classic', 'minimal'}
before, after, out = map(pathlib.Path, argv[:3])
cf_paths = list(map(pathlib.Path, argv[3:]))
assert len(cf_paths) in (0, 2)
out.mkdir(parents=True, exist_ok=True)
# Classic: patch/offsets.inc ACCENTS (top, bottom, light); Minimal has no accent.
classic_accents = [tuple(int(v, 16) for v in g) for g in re.findall(r'\{ 0x(\w+), 0x(\w+), 0x(\w+), 0x\w+, 0x\w+ \}', INC)]
minimal = (0xeeeeec, 0xeeeeec, inc('MINIMAL_FILL'))

with tempfile.TemporaryDirectory(prefix='q2-ui-preview-') as tmp:
    tmp = pathlib.Path(tmp)
    def asset(build, name):
        p = tmp/(build.name + '-' + pathlib.Path(name).name)
        if not p.exists():
            p.write_bytes(subprocess.check_output(['unsquashfs', '-cat', str(build/'rootfs.squashfs'),
                          'release/assets/default/raw/' + name]))
        return p
    font = asset(before, 'fonts/default.ttf')
    assert font.read_bytes() == asset(after, 'fonts/default.ttf').read_bytes()
    assert hashlib.sha256(font.read_bytes()).hexdigest() == 'b87b5af98e4e35e1ff6b5b8b4300cac81a3ede39a38b402ea792cb04838638f3'
    def tinted(p, name, accent):
        dest=tmp/(str(accent)+'-'+p.name)
        if dest.exists(): return dest
        w,h=png_header(p.read_bytes())[:2]
        pixels=bytearray(imagemagick(p,'-depth','8','rgba:-',data=b''))
        tone=0x2b2b2b if name.startswith('confirm_') else (0xd8d8d8,0xff1448,0x30929b,0x9a8446)[accent]
        glyph=0x2b2b2b if accent==0 and name=='drop_wifiopen' else 0xffffff
        red=(255,20,72); total=sum(red); delta=[3*c-total for c in red]; dd=sum(d*d for d in delta)
        for i in range(0,len(pixels),4):
            rgb=pixels[i:i+3]; sm=sum(rgb)
            t=int(sum((3*c-sm)*d for c,d in zip(rgb,delta))*4096/dd)
            if t<256 and glyph!=0xffffff: t=0
            k=int((sm*4096-t*total)/(3*4096))
            if (t and t<256) or t>4352 or k < -inc('RED_TOLERANCE'): continue
            if any(abs(c-(int(t*r/4096)+k))>inc('RED_TOLERANCE') for c,r in zip(rgb,red)): continue
            for j,shift in enumerate((16,8,0)):
                pixels[i+j]=max(0,min(255,int(t*(tone>>shift&255)/4096)+int(k*(glyph>>shift&255)/255)))
        dest.write_bytes(imagemagick('-size',f'{w}x{h}','-depth','8','rgba:-','png:-',data=bytes(pixels)))
        return dest
    def render(args, path):
        data = imagemagick(*map(str, args), '-strip', '-define', 'png:exclude-chunks=date,time', 'png:-', data=b'')
        path.write_bytes(data)
        return png_header(data)[:2]
    def text(args, value, x, y, width, height, size=20, color='#FFFFFF'):
        # Clip the first scrolling frame to the widget's real bounds, without wrapping.
        args += ['(', '+size', '-background', 'none', '-fill', color, '-font', font, '-pointsize', size,
                 'label:'+value, '-gravity', 'West', '-crop', f'{width}x{height}+0+0', '+repage',
                 '-extent', f'{width}x{height}', ')', '-gravity', 'NorthWest', '-geometry', f'+{x}+{y}', '-composite']
    def image(args, p, x, y, w, h):
        args += ['(', '-background', 'none', p, '-resize', f'{w}x{h}^', '-gravity', 'Center', '-extent', f'{w}x{h}',
                 ')', '-gravity', 'NorthWest', '-geometry', f'+{x}+{y}', '-composite']
    def rect(args, x, y, w, h, color):
        args += ['-fill', color, '-draw', f'rectangle {x},{y} {x+w-1},{y+h-1}']
    def recolour(p, minimal_ink=None):
        """Minimal's runtime image work (navigation.c ringnav_image_add): a settings icon greyed
        (Rec. 709 luma in 1/256) or list_into's ink set to MINIMAL_CHEVRON, alpha kept."""
        dest=tmp/(('ink-' if minimal_ink else 'grey-')+p.parent.name+'-'+p.name)
        if dest.exists(): return dest
        w,h=png_header(p.read_bytes())[:2]
        px=bytearray(imagemagick(p,'-depth','8','rgba:-',data=b''))
        for i in range(0,len(px),4):
            px[i:i+3]=bytes([minimal_ink if minimal_ink else (px[i]*54+px[i+1]*183+px[i+2]*19)>>8])*3
        dest.write_bytes(imagemagick('-size',f'{w}x{h}','-depth','8','rgba:-','-define','png:color-type=6','png:-',data=bytes(px)))
        return dest
    def selection(args, y, h, width, palette):
        top, bottom, _ = palette
        args += ['(', '-size', f'{width}x{h}', f'gradient:#{top:06x}-#{bottom:06x}',
                 ')', '-gravity', 'NorthWest', '-geometry', f'+0+{y}', '-composite']
        rect(args, 0, y, width, 1, '#eeeeec' if top==0xeeeeec else ('#555555' if palette[2]==0x6e6e6e else f'#{palette[2]:06x}'))
    def backdrop(source, dest):
        # coverflow.c ipod_backdrop_set: the centre crop averaged to a 20x16 grid, softened (two [1 2 1]
        # passes, about a one-cell Gaussian), scaled up bilinearly and dimmed to one-fifth.
        render([source,'-resize','375x290^','-gravity','Center','-extent','375x290','-filter','Box','-resize','20x16!',
                '-virtual-pixel','Edge','-gaussian-blur','0x1','-filter','Triangle','-resize','375x290!',
                '-channel','RGB','-evaluate','Multiply','0.2','+channel'],dest)
        return dest
    bright, dark = tmp/'bright.png', tmp/'dark.png'
    render(['-size','166x166','gradient:#FCE6AF-#2C7E93'], bright)
    render(['-size','166x166','gradient:#10131D-#423459'], dark)
    cases = ['Home Artwork / bright art', 'Home Plain / long labels / no Rockbox', 'Home Settings Plain',
             'Local Now Playing / paused / dark art', 'Spotify / missing art / scrub',
             'Library / added media', 'Folders / long labels', 'Display settings',
             'Quick settings / active, inactive, disabled', 'Confirmation / Cancel focused',
             'Home Artwork / dark art', 'Home Artwork / missing art',
             'Now Playing / bright art / seeking', 'PEQ / focus and untouched plot', 'Media browser / multilingual names']
    for accent, name in enumerate(('Graphite','Crimson','Tidal','Champagne')):
        tiles=[]
        for case, title in enumerate(cases):
            for side, (theme, build) in enumerate(zip(themes, (before, after))):
                old = theme == 'classic'  # Classic draws the pre-1.0.1 look
                palette = classic_accents[accent] if old else minimal
                tint = accent if old else 0  # Minimal's images take Graphite's greys
                a=['-size','375x320','xc:black']
                if case<8 or case>=10:
                    rect(a,0,0,375,30,f'#{inc("BAR_CLASSIC") if old else inc("BAR_COLOR"):06x}')
                    text(a,'Ⅱ' if case==3 else '▶',54,5,22,20,16)
                    text(a,'12:59 PM',151,5,74,20,16)
                    text(a,'88%',280,5,40,20,16)
                if case<3 or case in (10,11):
                    full=case in (1,2); width=(inc('HOME_CLASSIC_ROW') if full else inc('HOME_SPLIT_W')) if old else HOME_LIST_W
                    labels = ['Now Playing','Library','Coverflow','Folders','Rockbox','Streaming','Settings']
                    if case==1: labels=['Now Playing','Library — a very long music collection','Coverflow','音楽フォルダー','Streaming','Settings']
                    if case==2: labels=['Playback','System']
                    if not full and case!=11:
                        source = dark if case==10 else bright
                        if old: image(a,source,inc('HOME_SPLIT_W'),30,375-inc('HOME_SPLIT_W'),290)
                        else:
                            image(a,backdrop(source,tmp/'home-background.png'),0,30,375,290)
                    elif not full and old: image(a,asset(build,'images/xx/default_album_home.png'),inc('HOME_SPLIT_W'),30,375-inc('HOME_SPLIT_W'),290)
                    selected=1 if case!=2 else 0
                    for i,value in enumerate(labels):
                        y=30+HOME_TOP+i*HOME_ROW
                        if i==selected:
                            if old: selection(a,y,HOME_ROW,375 if full else width,palette)
                            else: a+=['-fill','white','-draw',f'circle {inc("HOME_DOT_X")+3},{y+HOME_ROW//2} {inc("HOME_DOT_X")+6},{y+HOME_ROW//2}']
                        x0=inc('HOME_CLASSIC_TEXT_X') if old else HOME_TEXT_X
                        label_width=width-x0-(inc('CHEVRON_W')-10 if old else HOME_LABEL_END)
                        text(a,value,x0,y,label_width,HOME_ROW,color='#FFFFFF' if old or i==selected else '#AAAAAA')
                        if old and i==selected: image(a,asset(build,'images/xx/list_into.png'),width-inc('CHEVRON_W'),y+(HOME_ROW-50)//2,50,50)
                elif case in (3,4,12):
                    nodes={n[2].get('name'):n for n in walk(decode((build/'ui/playing_page.bin').read_bytes()))}
                    art=dark if case==3 else (bright if case==12 else asset(build,'images/xx/default_album_big.png'))
                    if not old and case!=4:  # the whole window under the status bar
                        image(a,backdrop(art,tmp/'np-background.png'),0,30,375,290)
                    text(a,'3 of 12' if case==3 else 'Spotify',16,30,180,40,16,'#AAAAAA')
                    # The real art mask is rounded in the payload; compose the same 12px radius.
                    cover=tmp/'cover.png'
                    render([art,'-resize','166x166!','(', '-size','166x166','xc:black','-fill','white',
                            '-draw','roundrectangle 0,0 165,165 12,12',')','-alpha','off','-compose','CopyOpacity','-composite'],cover)
                    image(a,cover,16,80,166,166)
                    for node,value in [('scrlabel_title','A long title — 夜の音楽'),('scrlabel_artist','Artist / アーティスト'),('label_ipod_album','Album / Collection')]:
                        n=nodes[node]; x,y,w,h=n[1]
                        text(a,value,x,y+70,w,h,int(n[2].get('style:normal:font_size',16)),n[2].get('style:normal:text_color','#FFFFFF'))
                    for i,icon in enumerate(('play_unfav.png','play_more.png','play_order.png') if case==3 else ()):
                        image(a,asset(build,'images/xx/'+icon),214+i*50,36,28,28)
                    if old and case==3: text(a,'Ⅱ',82,146,34,44,30)
                    if case==3: text(a,'•  ·  ·',168,258,70,12,12,'#AAAAAA')
                    else: text(a,'▶',337,43,14,14,12,'#AAAAAA')
                    bh=inc('NP_BAR_CLASSIC') if old else inc('NP_BAR_MINIMAL'); by=251 if case==4 else 270+(30-bh)//2
                    rect(a,21,by,333,bh,'#1C1C1C'); rect(a,21,by,132,bh,'#FFFFFF' if case in (4,12) else f'#{palette[2]:06x}')
                    text(a,'01:23',46,295,80,16,14,'#AAAAAA'); text(a,'-02:34',249,295,80,16,14,'#AAAAAA')
                elif case<8:
                    rows = [('Shuffle','local_shuffle'),('Most Played','local_frequentplay'),('Audiobooks','local_audiobooks'),('Podcasts','local_podcasts')]
                    if case==6: rows=[('Albums','list_folder'),('音楽 — 長いフォルダー名','list_folder'),('A very long track title','local_frequentplay'),('Live recordings','list_folder')]
                    if case==7: rows=[('Backlight','display_backlight'),('Theme: Classic','system_display'),('Accent: '+name,'system_display'),('Home: Full','playset_covermode')] if old else \
                        [('Backlight','display_backlight'),('Theme: Minimal','system_display'),('Home: Plain','playset_covermode'),('Battery: Icon','system_powermanager')]
                    for i,(label,icon) in enumerate(rows):
                        y=30+i*72
                        if i==1: selection(a,y,72,375,palette)
                        p=build/(icon+'.png')
                        if not p.exists():
                            p=asset(build,'images/xx/'+icon+'.png')
                            if not old and case==7: p=recolour(p)
                        image(a,p,16,y+14,40,40); text(a,label,72,y,245,68,24,'#171717' if not old and i==1 else '#FFFFFF')
                        into=asset(build,'images/xx/list_into.png')
                        if case!=7 or i==0: image(a,into if old else recolour(into,inc('MINIMAL_CHEVRON')&255),317,y+9,50,50)
                elif case in (13,14):
                    if case==13:
                        text(a,'Parametric EQ',33,34,310,32,22)
                        rect(a,24,76,327,70,'#111111')
                        a+=['-stroke','#444444','-strokewidth','1','-draw','line 24,111 351,111',
                            '-stroke',f'#{palette[2]:06x}','-draw','path "M24,111 C110,111 130,82 187,98 S270,116 351,111"','+stroke']
                        rows=['Preamp              −3.0 dB','Band 1              100 Hz','Gain                  +2.0 dB']
                        top=150; height=44
                    else:
                        rows=['Albums / アルバム','A long concert recording.mp4','夜の写真.jpg','Books / Reading list']
                        top=38; height=68
                    for i,label in enumerate(rows):
                        y=top+i*height
                        if i==1: selection(a,y,height,375,palette)
                        text(a,label,33,y,309,height,20,'#171717' if not old and i==1 else '#FFFFFF')
                else:
                    page='dialog/statusbar_dialog.bin' if case==8 else 'dialog/confirminfo_dialog.bin'
                    root=decode((build/'ui'/page).read_bytes())
                    if case==9:
                        text(a,'Remove this playlist?',54,80,267,40,20)
                        x,y,w,h=root[3][0][1]
                        rect(a,x-2,y-2,w+4,h+4,'#FFFFFF'); rect(a,x,y,w,h,f'#{palette[0]:06x}')
                    def controls(n,ox=0,oy=0):
                        kind,(x,y,w,h),props,children=n; x+=ox; y+=oy
                        if kind=='slider':
                            rect(a,x,y+h//2-3,w,6,'#3A3A3A'); rect(a,x,y+h//2-3,w*2//5,6,'#FFFFFF')
                        if kind=='image':
                            icon=props.get('image') or props.get('style:normal:bg_image')
                            if not icon:
                                style=props.get('style','')
                                icon={'s_img_confirmcancel':'confirm_cancel','s_img_confirmok':'confirm_ok'}.get(style)
                            icon={'drop_wifi':'drop_wifiopen','drop_lowgain':'drop_lowgaindisable'}.get(icon,icon)
                            if icon:
                                p=asset(build,'images/xx/'+icon+'.png')
                                if icon.startswith(('confirm_','drop_')): p=tinted(p,icon,tint)
                                iw,ih=png_header(p.read_bytes())[:2]
                                image(a,p,x+(w-iw)//2,y+(h-ih)//2,iw,ih)
                        if kind=='label': text(a,props.get('text') or props.get('tr_text',''),x,y,w,h,16)
                        for c in children: controls(c,x,y)
                    root[1][:2]=[0,0]
                    controls(root)
                a+=['(', '-size','375x320','xc:black','-fill','white','-draw','roundrectangle 0,0 374,319 80,80',')',
                    '-alpha','off','-compose','CopyOpacity','-composite','-background','black','-alpha','remove','-compose','Over']
                p=tmp/f'{case}-{side}.png'; assert render(a,p)==(375,320)
                tile=tmp/f'tile-{case}-{side}.png'
                assert render(['-size','375x354','xc:#202020',p,'-gravity','NorthWest','-geometry','+0+34','-composite',
                               '-font',font,'-pointsize','12','-fill','white','-gravity','NorthWest',
                               '-annotate','+5+8',('Before' if side==0 else 'After')+f' {theme.title()} (composed) | '+title],tile)==(375,354)
                tiles.append(tile)
        args=[]
        for i in range(0,len(tiles),2): args+=['(',tiles[i],tiles[i+1],'+append',')']
        render(args+['-append'],out/(name.lower()+'.png'))
    if cf_paths:
        before_cf, after_cf = cf_paths
        frames=[]
        for name in ('rest','quarter','half','three-quarter','one-album'):
            row=tmp/(name+'.png')
            a=['-size','750x238','xc:#202020','(',before_cf/(name+'.png'),after_cf/(name+'.png'),'+append',')',
               '-gravity','NorthWest','-geometry','+0+28','-composite']
            text(a,'Before renderer | '+name,5,0,365,28,12)
            text(a,'After renderer | '+name,380,0,365,28,12)
            assert render(a,row)==(750,238)
            frames.append(row)
        render(frames+['-append'],out/'coverflow-renderer.png')
    (out/'provenance.json').write_text(json.dumps({
        'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),
        'before_source_sha256':json.loads((before/'manifest.json').read_text())['source_sha256'],
        'after_source_sha256':json.loads((after/'manifest.json').read_text())['source_sha256'],
        'screen_size':[375,320], 'kind':'composed illustrations, not firmware captures',
        'artwork':'synthetic bright/dark gradients; missing art uses packaged placeholder or black',
        'themes':themes, 'cases':cases, 'renderer_size':[375,210] if cf_paths else None},indent=2)+'\n')
print('Composed sheets: native font and packaged assets; every screen is 375x320. These are not firmware captures.')
