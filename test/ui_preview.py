#!/usr/bin/env python3
"""Compose native-size review sheets; these are layout illustrations, not AWTK captures.
Usage: python3 test/ui_preview.py BEFORE_BUILD AFTER_BUILD OUTPUT BEFORE_CF AFTER_CF
Uses the existing ImageMagick dependency and the original firmware's native font/assets.
"""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
sys.path.insert(0, sys.path[0] + '/../tools')
from ipod import (decode, walk, imagemagick, png_header, HOME_TEXT_X, HOME_LIST_W,
                  HOME_LABEL_END, HOME_ROW, HOME_TOP, inc)

before, after, out, before_cf, after_cf = map(pathlib.Path, sys.argv[1:])
out.mkdir(parents=True, exist_ok=True)
before_accents = [(0x424242, 0x424242, 0x6e6e6e), (0xe8123f, 0xa60025, 0xeb2f56),
           (0x13838d, 0x095158, 0x30929b), (0x8c732c, 0x5d4a18, 0x9a8446)]

accents = [(top, top, light) for top, _, light in before_accents]

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
    def selection(args, y, h, width, palette):
        top, bottom, _ = palette
        args += ['(', '-size', f'{width}x{h}', f'gradient:#{top:06x}-#{bottom:06x}',
                 ')', '-gravity', 'NorthWest', '-geometry', f'+0+{y}', '-composite']
        rect(args, 0, y, width, 1, '#555555' if palette[2]==0x6e6e6e else f'#{palette[2]:06x}')
    bright, dark = tmp/'bright.png', tmp/'dark.png'
    render(['-size','166x166','gradient:#FCE6AF-#2C7E93'], bright)
    render(['-size','166x166','gradient:#10131D-#423459'], dark)
    cases = ['Home Split / bright art', 'Home Full / long labels / no Rockbox', 'Home Settings Full',
             'Local Now Playing / paused / dark art', 'Spotify / missing art / scrub',
             'Library / added media', 'Folders / long labels', 'Display settings',
             'Quick settings / active, inactive, disabled', 'Confirmation / Cancel focused']
    for accent, name in enumerate(('Graphite','Crimson','Tidal','Champagne')):
        tiles=[]
        for case, title in enumerate(cases):
            for old, build in ((True,before),(False,after)):
                palette = (before_accents if old else accents)[accent]
                a=['-size','375x320','xc:black']
                if case<8:
                    rect(a,0,0,375,30,'#161616')
                    text(a,'Ⅱ' if case==3 else '▶',54,5,22,20,16)
                    text(a,'12:59 PM',151,5,74,20,16)
                    text(a,'88%',280,5,40,20,16)
                if case<3:
                    full=case!=0; width=inc('HOME_FULL_ROW') if full else HOME_LIST_W
                    labels = ['Now Playing','Library','Coverflow','Folders','Rockbox','Streaming','Settings']
                    if case==1: labels=['Now Playing','Library — a very long music collection','Coverflow','音楽フォルダー','Streaming','Settings']
                    if case==2: labels=['Playback','System']
                    if not full: image(a,bright,187,30,188,290)
                    selected=1 if case!=2 else 0
                    for i,value in enumerate(labels):
                        y=30+HOME_TOP+i*HOME_ROW
                        if i==selected: selection(a,y,HOME_ROW,375 if full else width,palette)
                        label_width=(HOME_LIST_W if old else width)-HOME_TEXT_X-HOME_LABEL_END
                        text(a,value,HOME_TEXT_X,y,label_width,HOME_ROW)
                        if i==selected: image(a,asset(build,'images/xx/list_into.png'),width-inc('CHEVRON_W'),y+(HOME_ROW-50)//2,50,50)
                elif case in (3,4):
                    nodes={n[2].get('name'):n for n in walk(decode((build/'ui/playing_page.bin').read_bytes()))}
                    text(a,'3 of 12' if case==3 else 'Spotify',16,30,180,40,16,'#AAAAAA')
                    art=dark if case==3 else asset(build,'images/xx/default_album_big.png')
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
                    if case==3: text(a,'Ⅱ',82,146,34,44,30)
                    if case==3: text(a,'•  ·  ·',168,258,70,12,12,'#AAAAAA')
                    else: text(a,'▶',337,43,14,14,12,'#AAAAAA')
                    rect(a,21,281,333,8,'#1C1C1C'); rect(a,21,281,132,8,'#FFFFFF' if case==4 else f'#{palette[2]:06x}')
                    text(a,'01:23',46,295,80,16,14,'#AAAAAA'); text(a,'-02:34',249,295,80,16,14,'#AAAAAA')
                elif case<8:
                    rows = [('Shuffle','local_shuffle'),('Most Played','local_frequentplay'),('Audiobooks','local_audiobooks'),('Podcasts','local_podcasts')]
                    if case==6: rows=[('Albums','list_folder'),('音楽 — 長いフォルダー名','list_folder'),('A very long track title','local_frequentplay'),('Live recordings','list_folder')]
                    if case==7: rows=[('Backlight','display_backlight'),('Accent: '+name,'system_display'),('Home: Full','playset_covermode'),('Battery: Icon','system_powermanager')]
                    for i,(label,icon) in enumerate(rows):
                        y=30+i*72
                        if i==1: selection(a,y,72,375,palette)
                        p=build/(icon+'.png')
                        if not p.exists():
                            p=asset(build,'images/xx/'+icon+'.png')
                        image(a,p,16,y+14,40,40); text(a,label,72,y,245,68,24)
                        if case!=7 or i==0: image(a,asset(build,'images/xx/list_into.png'),317,y+9,50,50)
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
                                if icon.startswith(('confirm_','drop_')): p=tinted(p,icon,accent)
                                iw,ih=png_header(p.read_bytes())[:2]
                                image(a,p,x+(w-iw)//2,y+(h-ih)//2,iw,ih)
                        if kind=='label': text(a,props.get('text') or props.get('tr_text',''),x,y,w,h,16)
                        for c in children: controls(c,x,y)
                    root[1][:2]=[0,0]
                    controls(root)
                p=tmp/f'{case}-{old}.png'; assert render(a,p)==(375,320)
                tile=tmp/f'tile-{case}-{old}.png'
                assert render(['-size','375x354','xc:#202020',p,'-gravity','NorthWest','-geometry','+0+34','-composite',
                               '-font',font,'-pointsize','12','-fill','white','-gravity','NorthWest',
                               '-annotate','+5+8',('Before' if old else 'After')+' (composed) | '+title],tile)==(375,354)
                tiles.append(tile)
        args=[]
        for i in range(0,len(tiles),2): args+=['(',tiles[i],tiles[i+1],'+append',')']
        render(args+['-append'],out/(name.lower()+'.png'))
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
        'screen_size':[375,320], 'renderer_size':[375,210]},indent=2)+'\n')
print('Composed sheets: native font and current assets; every screen is 375x320. Coverflow frames are actual host renderer output.')
