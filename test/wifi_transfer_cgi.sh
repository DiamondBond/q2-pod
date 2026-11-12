#!/bin/bash
# Exercise assets/web/q2cgi — the safe Wi-Fi transfer file manager (docs/internals.md#safe-file-
# manager) — under the stock busybox ash with synthetic CGI requests. /mnt/mmc is a tmpfs, so the
# mount check and the filesystem boundary are real. Needs root (to mount the tmpfs) and busybox;
# run it in the q2pod-dev container, e.g. `q2dev.ps1 run bash /work/test/wifi_transfer_cgi.sh`.
# No network. Every payload is benign (markers under /tmp or the card tmpfs; nothing destructive).
set -u
CGI="$(cd "$(dirname "$0")/.." && pwd)/assets/web/q2cgi"
SH="busybox ash"
command -v busybox >/dev/null || { echo "SKIP: busybox not found (run in the q2pod-dev container)"; exit 0; }
if ! grep -q ' /mnt/mmc ' /proc/mounts 2>/dev/null; then
  mkdir -p /mnt/mmc 2>/dev/null
  mount -t tmpfs tmpfs /mnt/mmc 2>/dev/null || { echo "SKIP: cannot mount a tmpfs at /mnt/mmc (need root)"; exit 0; }
  trap 'umount /mnt/mmc 2>/dev/null' EXIT
fi
rm -rf /mnt/mmc/* /mnt/mmc/.[!.]* 2>/dev/null
# Reproduce the Q2's applet set: a PATH with ONLY the applets the stock rootfs symlinks to busybox
# (notably NO bare `stat`), so a reliance on a tool the device lacks fails here too.
BB=$(command -v busybox)
DEV=/tmp/devbin; rm -rf "$DEV"; mkdir -p "$DEV"
for a in sh ash sed tr grep awk tail head cat ls date mkdir rm rmdir mv cut printf dd mountpoint realpath busybox; do ln -sf "$BB" "$DEV/$a"; done
DEVPATH="$DEV"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  PASS: $1"; }
bad() { fail=$((fail+1)); echo "  FAIL: $1"; }

# run <name> <method> <query> <contenttype> <bodyfile|-> -> sets $OUT and $RC
run() {
  local nm=$1 meth=$2 q=$3 ct=$4 bf=$5 len=0 src=/dev/null
  [ "$bf" != "-" ] && { len=$(stat -c %s "$bf"); src=$bf; }
  OUT=$(env -i PATH="$DEVPATH" SCRIPT_NAME="/$nm" REQUEST_METHOD="$meth" \
        QUERY_STRING="$q" CONTENT_TYPE="$ct" CONTENT_LENGTH="$len" \
        $SH "$CGI" < "$src" 2>/dev/null); RC=$?
}
# POST a urlencoded path in the body (realistic for create/delete)
post() { local nm=$1 p=$2; printf 'path=%s' "$p" > /tmp/b.$$; run "$nm" POST '' 'application/x-www-form-urlencoded' /tmp/b.$$; rm -f /tmp/b.$$; }
status() { printf '%s' "$OUT" | sed -n 's/^Status: \([0-9]*\).*/\1/p' | head -1; }
body()   { printf '%s' "$OUT" | awk 'b{print} /^\r?$/{b=1}'; }

echo "=== busybox ash case [[:cntrl:]] support"; busybox ash -c 'case "$(printf a\\tb)" in *[[:cntrl:]]*) echo yes;; *) echo NO;; esac'
rm -rf /tmp/pwned* 2>/dev/null

echo; echo "############ SECURITY: command injection must NOT execute (both POST body and GET query, raw and encoded)"
post create 'path=/mnt/mmc/a$(id>/tmp/pwned1)b' ; # note: this double 'path=' is intentional dup test below; real injection:
printf 'path=/mnt/mmc/a$(id>/tmp/pwned1)b' > /tmp/b1; run create POST '' 'application/x-www-form-urlencoded' /tmp/b1
[ -e /tmp/pwned1 ] && bad "POST dollar-paren executed" || ok "POST \$() injection inert"
run create GET 'path=/mnt/mmc/a`id>/tmp/pwned2`b' '' -
[ -e /tmp/pwned2 ] && bad "GET backtick executed" || ok "GET backtick injection inert"
printf 'path=%%2Fmnt%%2Fmmc%%2Fa%%24%%28id%%3E%%2Ftmp%%2Fpwned3%%29b' > /tmp/b3; run create POST '' 'application/x-www-form-urlencoded' /tmp/b3
[ -e /tmp/pwned3 ] && bad "encoded injection executed" || ok "URL-encoded \$() injection inert (decode-then-argv)"

echo; echo "############ SECURITY: traversal / NUL / scope / duplicate-field must be rejected"
run download GET 'path=/mnt/mmc/../../etc/hostname' '' -
{ [ "$(status)" = 400 ] && ! printf '%s' "$OUT" | grep -q "$(cat /etc/hostname)"; } && ok "download ../ rejected, no leak" || bad "download ../ (status $(status))"
run download GET 'path=/mnt/mmc/..%2f..%2fetc%2fhostname' '' -
[ "$(status)" = 400 ] && ok "download encoded ../ rejected" || bad "download encoded ../ ($(status))"
run list GET 'path=/mnt/mmc/../..' '' -; [ "$(status)" = 400 ] && ok "list ../ rejected" || bad "list ../ ($(status))"
post create '/etc/evil' 2>/dev/null; printf 'path=/etc/evil' > /tmp/be; run create POST '' 'application/x-www-form-urlencoded' /tmp/be
[ "$(status)" = 400 ] && ok "non-/mnt/mmc path rejected" || bad "non-card path ($(status))"
run download GET 'path=/mnt/mmc/a%00.txt' '' -; [ "$(status)" = 400 ] && ok "NUL byte rejected" || bad "NUL ($(status))"
printf 'path=/mnt/mmc/ok&path=/etc/evil' > /tmp/bd; run create POST '' 'application/x-www-form-urlencoded' /tmp/bd
[ "$(status)" = 400 ] && ok "duplicate path field rejected" || bad "duplicate path not rejected ($(status))"

echo; echo "############ FUNCTIONAL: create / list / download / delete / upload (confined to /mnt/mmc)"
printf 'path=/mnt/mmc/My Folder' > /tmp/bf; run create POST '' 'application/x-www-form-urlencoded' /tmp/bf
[ -d "/mnt/mmc/My Folder" ] && ok "create 'My Folder' (POST body, literal space)" || bad "create plain folder ($(status))"
run create GET 'path=/mnt/mmc/From+Query' '' -
[ -d "/mnt/mmc/From Query" ] && ok "create via GET query (+ = space)" || bad "create via GET"
printf 'path=/mnt/mmc/M%%C3%%BAsica %%26 Caf%%C3%%A9 (2024)' > /tmp/bu; run create POST '' 'application/x-www-form-urlencoded' /tmp/bu
[ -d "/mnt/mmc/Música & Café (2024)" ] && ok "create Unicode+&() folder preserved (not mangled)" || bad "create special folder"

B=/tmp/mp_text; BND=----q2t
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"hello world.txt\"\r\nContent-Type: text/plain\r\n\r\nSYNTHETIC-DATA\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
[ "$(cat "/mnt/mmc/hello world.txt" 2>/dev/null)" = "SYNTHETIC-DATA" ] && ok "upload text 'hello world.txt'" || bad "upload text ($(status); file='$(cat "/mnt/mmc/hello world.txt" 2>/dev/null | head -c40)')"

python3 -c "
bnd=b'----q2b'; content=bytes(range(256))*4 + b'\r\n--not-boundary--' + bytes(range(200))
open('/tmp/expect.bin','wb').write(content)
body=(b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/sub\r\n'
      b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"clip.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n'+content+b'\r\n--'+bnd+b'--\r\n')
open('/tmp/mp_bin','wb').write(body)"
run upload POST '' 'multipart/form-data; boundary=----q2b' /tmp/mp_bin
cmp -s "/mnt/mmc/sub/clip.bin" /tmp/expect.bin && ok "upload BINARY byte-exact (NUL + CRLF + boundary-like content; nested dir)" || bad "upload binary mismatch (size $(stat -c %s /mnt/mmc/sub/clip.bin 2>/dev/null) vs $(stat -c %s /tmp/expect.bin))"

# (a) a $()-bearing filename WITHOUT a slash -> stored literally, no execution. Run with cwd /mnt/mmc
#     so that if $(touch pwned4y) DID execute it would drop /mnt/mmc/pwned4y, which we then check for.
B=/tmp/mp_evil; BND=----q2e
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"x\$(touch pwned4y).mp3\"\r\nContent-Type: audio/mpeg\r\n\r\nAUDIOBYTES\r\n--$BND--\r\n"; } > "$B"
L=$(stat -c %s "$B")
OUT=$( cd /mnt/mmc && env -i PATH="$DEVPATH" SCRIPT_NAME=/upload REQUEST_METHOD=POST \
       CONTENT_TYPE="multipart/form-data; boundary=$BND" CONTENT_LENGTH="$L" busybox ash "$CGI" < "$B" 2>/dev/null )
[ -e /mnt/mmc/pwned4y ] && bad "upload filename injection executed" || ok "upload filename \$() injection inert"
[ "$(cat "/mnt/mmc/x\$(touch pwned4y).mp3" 2>/dev/null)" = "AUDIOBYTES" ] && ok "upload stored literal \$()-name file safely (preserved, not executed)" || bad "upload literal-name content wrong"
# (b) a filename with a slash (traversal) -> rejected, nothing written outside
B=/tmp/mp_trav; BND=----q2v
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"../../../tmp/escaped\"\r\nContent-Type: application/octet-stream\r\n\r\nX\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
{ [ "$(status)" = 400 ] && [ ! -e /tmp/escaped ]; } && ok "upload traversal filename rejected, no escape" || bad "upload traversal filename ($(status), escaped=$([ -e /tmp/escaped ] && echo yes))"

run list GET 'path=/mnt/mmc' '' -
body | python3 -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d,list) and len(d)>=4; ns=[e['name'] for e in d]; assert 'My Folder' in ns and 'hello world.txt' in ns; assert all('ctime' in e for e in d); assert any('size' in e for e in d); print('list ok:',len(d),'entries')" && ok "list valid JSON array with names/ctime/size" || bad "list JSON/fields wrong"

run download GET 'path=/mnt/mmc/hello world.txt' '' -
[ "$(body)" = "SYNTHETIC-DATA" ] && ok "download returns content" || bad "download content"
printf '%s' "$OUT" | grep -qi 'filename="hello world.txt"' && ok "download Content-Disposition" || bad "download header"

printf 'path=/mnt/mmc/My Folder' > /tmp/bdel; run delete POST '' 'application/x-www-form-urlencoded' /tmp/bdel
[ -d "/mnt/mmc/My Folder" ] && bad "delete left folder" || ok "delete removed folder"
printf 'path=/mnt/mmc' > /tmp/broot; run delete POST '' 'application/x-www-form-urlencoded' /tmp/broot
[ "$(status)" = 400 ] && ok "delete of card root refused" || bad "delete root ($(status))"

# a boundary containing regex metacharacters (+ .) must still parse (RS escaping)
B=/tmp/mp_meta; BND='x+y.z--Boundary9'
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"meta.txt\"\r\nContent-Type: text/plain\r\n\r\nMETABODY\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
[ "$(cat "/mnt/mmc/meta.txt" 2>/dev/null)" = "METABODY" ] && ok "upload with regex-metachar boundary (+ .) parses" || bad "metachar boundary upload ($(status))"

# a large file (> the 64 KB header-parse window) must extract byte-exact (content beyond the prefix)
python3 -c "
import os
bnd=b'----q2big'; content=os.urandom(300000)
open('/tmp/expect.big','wb').write(content)
body=(b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n'
      b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"big.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n'+content+b'\r\n--'+bnd+b'--\r\n')
open('/tmp/mp_big','wb').write(body)"
run upload POST '' 'multipart/form-data; boundary=----q2big' /tmp/mp_big
cmp -s "/mnt/mmc/big.bin" /tmp/expect.big && ok "upload 300 KB binary byte-exact (content beyond the 64 KB prefix)" || bad "upload large binary mismatch (size $(busybox stat -c %s /mnt/mmc/big.bin 2>/dev/null) vs 300000)"

echo; echo "############ REGRESSION: list emits directory paths WITH a trailing slash (client contract)"
run create GET 'path=/mnt/mmc/SubDir' '' -
run list GET 'path=/mnt/mmc/' '' -        # the real client lists the home path WITH a trailing slash
body | python3 -c "import json,sys
d=json.load(sys.stdin); e=[x for x in d if x['name']=='SubDir'][0]
assert 'size' not in e, 'dir must have no size'
assert e['path']=='/mnt/mmc/SubDir/', e['path']
print('dir path ok:', e['path'])" && ok "list dir path has one clean trailing slash" || bad "list dir trailing slash"
# The client builds the create path as <dirpath>+<name>; with the slash that is /mnt/mmc/SubDir/Child
run create GET 'path=/mnt/mmc/SubDir/Child' '' -
{ [ -d "/mnt/mmc/SubDir/Child" ] && [ ! -e "/mnt/mmc/SubDirChild" ]; } && ok "create inside a subfolder lands there (no mangled top-level sibling)" || bad "subfolder create mangled"

echo; echo "############ SECURITY: a card-root delete (trailing slash / dot / double slash) must NOT wipe the card"
printf keep > /mnt/mmc/keepme
post delete '/mnt/mmc/'
{ [ "$(status)" = 400 ] && [ -e /mnt/mmc/keepme ]; } && ok "delete '/mnt/mmc/' refused, card intact" || bad "delete trailing-slash root ($(status), keepme=$([ -e /mnt/mmc/keepme ] && echo yes))"
post delete '/mnt/mmc//'
{ [ "$(status)" = 400 ] && [ -e /mnt/mmc/keepme ]; } && ok "delete '/mnt/mmc//' refused, card intact" || bad "delete double-slash root ($(status))"
post delete '/mnt/mmc/.'
{ [ "$(status)" = 400 ] && [ -e /mnt/mmc/keepme ]; } && ok "delete '/mnt/mmc/.' refused, card intact" || bad "delete dot root ($(status))"

echo; echo "############ PRIVACY: hidden files are not listed and not directly reachable"
printf 'SECRETKEY' > /mnt/mmc/.scrobble.ini; mkdir -p /mnt/mmc/.spotify
run list GET 'path=/mnt/mmc' '' -
body | python3 -c "import json,sys
ns=[e['name'] for e in json.load(sys.stdin)]
assert '.scrobble.ini' not in ns and '.spotify' not in ns, ns
print('hidden not listed ok')" && ok "dotfiles (.scrobble.ini/.spotify) absent from listing" || bad "dotfiles listed"
run download GET 'path=/mnt/mmc/.scrobble.ini' '' -
{ [ "$(status)" = 400 ] && ! printf '%s' "$OUT" | grep -q SECRETKEY; } && ok "direct download of .scrobble.ini refused, no key leak" || bad "dotfile download ($(status))"
run list GET 'path=/mnt/mmc/.spotify' '' -
[ "$(status)" = 400 ] && ok "direct list of .spotify refused" || bad "dotfile list ($(status))"
post delete '/mnt/mmc/.scrobble.ini'
{ [ "$(status)" = 400 ] && [ -e /mnt/mmc/.scrobble.ini ]; } && ok "direct delete of .scrobble.ini refused" || bad "dotfile delete ($(status))"

echo; echo "############ PARITY: System Volume Information is hidden (as stock does)"
mkdir -p "/mnt/mmc/System Volume Information"
run list GET 'path=/mnt/mmc' '' -
body | python3 -c "import json,sys
ns=[e['name'] for e in json.load(sys.stdin)]
assert 'System Volume Information' not in ns, ns
print('svi hidden ok')" && ok "System Volume Information hidden from listing" || bad "SVI listed"

echo; echo "############ DoS: upload CONTENT_LENGTH must be a positive integer (no unbounded head -c)"
B=/tmp/mp_cl; BND=----q2cl
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"cl.txt\"\r\nContent-Type: text/plain\r\n\r\nX\r\n--$BND--\r\n"; } > "$B"
clbad=0
for badlen in -1 abc ""; do
  O=$(env -i PATH="$DEVPATH" SCRIPT_NAME=/upload REQUEST_METHOD=POST \
      CONTENT_TYPE="multipart/form-data; boundary=$BND" CONTENT_LENGTH="$badlen" \
      busybox ash "$CGI" < "$B" 2>/dev/null)
  st=$(printf '%s' "$O" | sed -n 's/^Status: \([0-9]*\).*/\1/p' | head -1)
  [ "$st" = 400 ] || { bad "upload CONTENT_LENGTH='$badlen' not rejected (status '$st')"; clbad=1; }
done
[ "$clbad" = 0 ] && ok "upload rejects negative / non-numeric / empty CONTENT_LENGTH"

echo; echo "############ ROBUST: a crafted body with two file parts is refused, nothing written"
B=/tmp/mp_two; BND=----q2two
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"one.txt\"\r\nContent-Type: text/plain\r\n\r\nAAA\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"two.txt\"\r\nContent-Type: text/plain\r\n\r\nBBB\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
{ [ "$(status)" = 400 ] && [ ! -e /mnt/mmc/one.txt ] && [ ! -e /mnt/mmc/two.txt ]; } && ok "two-file-part upload refused, nothing written" || bad "two-part upload ($(status), one=$([ -e /mnt/mmc/one.txt ] && echo y))"

echo; echo "############ SYMLINK: no op may follow a symlink off the card (NTFS / reformatted card)"
mkdir -p /tmp/offcard; printf SECRET > /tmp/offcard/secret
ln -sf /etc /mnt/mmc/evil 2>/dev/null
ln -sf /tmp/offcard /mnt/mmc/elink 2>/dev/null
if [ -L /mnt/mmc/evil ]; then
  run list GET 'path=/mnt/mmc/evil' '' -
  [ "$(status)" = 400 ] && ok "list via off-card symlink refused" || bad "symlink list ($(status))"
  run download GET 'path=/mnt/mmc/evil/hostname' '' -
  { [ "$(status)" = 400 ] && ! printf '%s' "$OUT" | grep -q "$(cat /etc/hostname)"; } && ok "download through off-card symlink refused, no leak" || bad "symlink download ($(status))"
  post delete '/mnt/mmc/evil/zzz_nonexistent'      # confine resolves the existing parent (/etc) and refuses before rm
  [ "$(status)" = 400 ] && ok "delete through off-card symlink refused (no rm off-card)" || bad "symlink delete ($(status))"
  run create GET 'path=/mnt/mmc/elink/plantdir' '' -
  { [ "$(status)" = 400 ] && [ ! -e /tmp/offcard/plantdir ]; } && ok "create through off-card symlink refused (nothing created off-card)" || bad "symlink create ($(status))"
  B=/tmp/mp_sl; BND=----q2sl
  { printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/elink\r\n"
    printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"planted.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\nX\r\n--$BND--\r\n"; } > "$B"
  run upload POST '' "multipart/form-data; boundary=$BND" "$B"
  { [ "$(status)" = 400 ] && [ ! -e /tmp/offcard/planted.mp3 ]; } && ok "upload through off-card symlink refused, nothing written off-card" || bad "symlink upload ($(status))"
  [ "$(cat /tmp/offcard/secret)" = SECRET ] && ok "off-card data untouched by all symlink ops" || bad "off-card data changed!"
  rm -f /mnt/mmc/evil /mnt/mmc/elink
else
  echo "  SKIP: this filesystem did not allow creating a symlink (cannot exercise confine here)"
fi
rm -rf /tmp/offcard

echo; echo "############ PRIVACY+: upload must not create a hidden (leading-dot) file nor clobber a dir"
printf 'OLD' > /mnt/mmc/.scrobble.ini        # known value; the earlier direct-delete was refused so it persists
B=/tmp/mp_dot; BND=----q2dot
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\".scrobble.ini\"\r\nContent-Type: text/plain\r\n\r\nATTACKER\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
{ [ "$(status)" = 400 ] && [ "$(cat /mnt/mmc/.scrobble.ini)" = OLD ]; } && ok "upload of a leading-dot filename refused (.scrobble.ini not overwritten)" || bad "upload dotfile overwrite ($(status), now='$(cat /mnt/mmc/.scrobble.ini 2>/dev/null)')"
mkdir -p "/mnt/mmc/ClashDir"
B=/tmp/mp_cd; BND=----q2cd
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"ClashDir\"\r\nContent-Type: application/octet-stream\r\n\r\nX\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
{ [ "$(status)" = 400 ] && [ -d /mnt/mmc/ClashDir ]; } && ok "upload onto an existing directory name refused" || bad "upload dir-clash ($(status))"

echo; echo "############ PATH ROBUSTNESS: sibling-prefix, double-encoding, mid-name dot"
run create GET 'path=/mnt/mmcEVIL' '' -
{ [ "$(status)" = 400 ] && [ ! -e /mnt/mmcEVIL ]; } && ok "sibling-prefix /mnt/mmcEVIL rejected" || bad "sibling-prefix ($(status))"
run create GET 'path=/mnt/mmc/%252e%252e' '' -
[ -d "/mnt/mmc/%2e%2e" ] && ok "double-encoded dots stay literal, no traversal" || bad "double-encoding (dir not literal)"
run create GET 'path=/mnt/mmc/2024.Album' '' -
[ -d "/mnt/mmc/2024.Album" ] && ok "mid-name dot folder created (no dot-rule false positive)" || bad "mid-name dot wrongly rejected"

echo; echo "############ MULTIPART EDGES: zero-byte, content ending in the boundary token, quoted boundary"
B=/tmp/mp_zero; BND=----q2z
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"zero.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=$BND" "$B"
{ [ -f /mnt/mmc/zero.bin ] && [ ! -s /mnt/mmc/zero.bin ]; } && ok "zero-byte upload stored as an empty file" || bad "zero-byte upload ($(status))"
python3 -c "
bnd=b'----q2end'; content=b'AUDIO--'+bnd        # content literally ENDS with the boundary token
open('/tmp/expect.end','wb').write(content)
body=(b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n'
      b'--'+bnd+b'\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"ends.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n'+content+b'\r\n--'+bnd+b'--\r\n')
open('/tmp/mp_end','wb').write(body)"
run upload POST '' 'multipart/form-data; boundary=----q2end' /tmp/mp_end
cmp -s /mnt/mmc/ends.bin /tmp/expect.end && ok "content ending in the boundary token is byte-exact" || bad "content-ends-in-boundary mismatch"
B=/tmp/mp_q; BND=----q2quoted
{ printf -- "--$BND\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n/mnt/mmc/\r\n"
  printf -- "--$BND\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"q.txt\"\r\nContent-Type: text/plain\r\n\r\nQBODY\r\n--$BND--\r\n"; } > "$B"
run upload POST '' "multipart/form-data; boundary=\"$BND\"" "$B"
[ "$(cat /mnt/mmc/q.txt 2>/dev/null)" = QBODY ] && ok "quoted boundary accepted (RFC-legal)" || bad "quoted boundary ($(status))"

echo; echo "############ DEVICE APPLET: no dependency on 'stat' (absent on device busybox 1.31.1)"
grep -qE 'stat -c|busybox stat' "$CGI" && bad "q2cgi invokes the 'stat' applet, which the device busybox lacks" || ok "no 'stat' applet dependency (size via ls -ln, mtime via date -r)"

echo; echo "############ FILESYSTEM BOUNDARY"
ls /tmp/pwned* 2>/dev/null && bad "markers leaked" || ok "no injection markers anywhere"

echo; echo "============ RESULT: $pass passed, $fail failed"; [ "$fail" = 0 ]
