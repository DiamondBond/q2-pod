"""patch/btmeta.c: with Bluetooth on, /tmp/q2-bt/nowplaying holds the record q2mpris sends (patch/mpris.c, whose
test/mpris.py writes the same lines), written whole when the track, the status or the position changes."""
import ctypes as C
import struct

from conftest import O, Files
from test_onlinematch import Queue, records  # noqa: F401  the play queue and its songs

FILE = '/tmp/q2-bt/nowplaying'
PLAYING, PAUSED = 2, 3  # mclGetPlayStatus
ARTIST = 'Tran' + 'é' * 97  # 'Tran' and 100 é cut at 199 bytes, then back to a whole character


def record(status, position, now, title='Moment s Notice', track=1):
    return (f'status={status}\ntitle={title}\nartist={ARTIST}\nalbum=Blue Train\ngenre=Jazz\n'
            f'duration=200000\ntrack={track}\nposition={position}\nnow={now}\n').encode()


def test_the_record_is_written_whole_on_a_change(fw, mcl, records):
    files, now = Files(fw), {'ms': 10000, 'status': PLAYING, 'sec': 5}
    fw.mock('time_now_ms', lambda *_: now['ms'])
    fw.mock('fw_clock_gettime', lambda which, t, *_: struct.pack_into('<qq', (C.c_char * 16).from_address(t), 0,
                                                                        now['ms'] // 1000, now['ms'] % 1000 * 1000000))
    fw.mock('mclGetPlayStatus', lambda *_: now['status'])
    fw.mock('player_playtime_and_length', lambda s, t, *_: C.memmove(s, struct.pack('<i', now['sec']), 4)
            and C.memmove(t, struct.pack('<i', 200), 4) and 0)
    info = fw.var('fw_ctx_g_play_id3_info', C.c_char * 2716)
    for field, text in ((O['ID3_TITLE'], 'Moment\x02s Notice'), (O['ID3_ARTIST'], 'Tran' + 'é' * 100),
                        (O['ID3_ALBUM'], 'Blue Train'), (0x604, 'Jazz')):
        C.memmove(C.addressof(info) + field, text.encode() + b'\0', len(text.encode()) + 1)
    Queue(fw, mcl, [records.song(b'/mnt/mmc/A/01 Blue Train.flac'), records.song(b'/mnt/mmc/A/02 Moment.flac')])
    bt = fw.var('g_bluetoothflag', C.c_ubyte)
    poll, seek = fw.fn('btmeta_poll', None), fw.fn('btmeta_seek', None, C.c_int)

    def look(ms=250, **change):
        now.update(change)
        now['ms'] += ms
        poll()
        return files.files.pop(FILE, None)

    assert look() is None  # Bluetooth off
    bt.value = 1
    assert look() == record('Playing', 5000, 10500)
    assert look(ms=100) is None  # four a second at most
    assert look(ms=1900, sec=7) is None  # playing on as expected
    assert look(sec=12) == record('Playing', 12000, 12750)  # a seek
    assert look(status=PAUSED) == record('Paused', 12000, 13000)
    assert look(ms=5000) is None  # paused: the position stays
    seek(60)
    assert look() == record('Paused', 60000, 18250)  # stock still reports 12 until Play
    assert look() is None
    assert look(status=PLAYING, sec=60) == record('Playing', 60000, 18750)
    info[O['ID3_TITLE']] = b'\0'
    mcl.pos = 1
    assert look(sec=0) == record('Playing', 0, 19000, title='02 Moment.flac', track=2)  # no title: the file's name
    bt.value = 0
    assert look() is None
    bt.value = 1
    assert look() == record('Playing', 0, 19500, title='02 Moment.flac', track=2)  # written again on Bluetooth's return
