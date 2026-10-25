#!/usr/bin/env python3
"""Guard and stage a Q2 development TF update; never flash or press UI controls.

inspect validates the package locally. check/ready also require the configured battery threshold (80% by default),
Charging/Full, a mounted card and no USB storage. stage only copies a validated
package (low charge is allowed), preserving the previous card update locally.
verify checks installed binary hashes and a different boot ID after the normal
TF-update menu has completed. A successful ready check is not a flash command.
"""
import argparse
import datetime
import hashlib
import io
import json
import math
import pathlib
import re
import shutil
import shlex
import subprocess
import tarfile
import tempfile
import uuid
import zipfile

from build import ZIP_SHA, DEMO_SHA, REMOTE_HOOK, dev_tag
import q2remote

MEMBERS = ("firmware_v20.info", "recovery-update",
           "recovery-update/xImage", "recovery-update/rootfs.squashfs")
REMOTE_UPDATE = "/mnt/mmc/update.tar"
BATTERY_SCRIPT = """set -e
cat /sys/devices/i2c-0/0-0062/cw2015_capacity
printf '\\n'
cat /sys/class/power_supply/battery/status
cat /proc/sys/kernel/random/boot_id
mountpoint -q /mnt/mmc
"""
DIGEST_SCRIPT = "sha256sum {path} && md5sum {path}"
OLD_SCRIPT = ("if [ -L /mnt/mmc/update.tar ]; then exit 2; "
              "elif [ -f /mnt/mmc/update.tar ]; then echo present; "
              "elif [ -e /mnt/mmc/update.tar ]; then exit 2; else echo absent; fi")
INSTALLED_SCRIPT = "sha256sum /usr/bin/hciplayer /release/bin/demo /usr/bin/q2remote"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(value, name):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value),
            f"missing or invalid {name}")
    return value

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def members(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        entries = archive.getmembers()
        require(tuple(m.name for m in entries) == MEMBERS, "unexpected/duplicate package members")
        require(entries[1].isdir() and all(m.isfile() for m in (entries[0], *entries[2:])),
                "package members must be ordinary files and the recovery directory")
        end = max(m.offset_data + ((m.size + 511) // 512) * 512 for m in entries)
        require(len(raw) % 512 == 0 and len(raw) - end >= 1024 and not raw[end:].strip(b"\0"),
                "missing, nonzero or partial tar trailer")
        return {m.name: archive.extractfile(m).read() for m in entries if m.isfile()}

def info(blobs):
    lines = blobs[MEMBERS[0]].decode("ascii").splitlines()
    require(len(lines) == 4 and lines[0] == "Shanling Q2", "wrong model or firmware info")
    for line, name in zip(lines[2:], MEMBERS[2:]):
        require(line == hashlib.md5(blobs[name]).hexdigest() + "  " + name,
                f"embedded MD5 mismatch: {name}")
    return lines[1]

def rootfs_hashes(raw, work):
    # Never extract arbitrary paths from an update. unsquashfs -cat reads only
    # these three fixed files; temporary image storage stays under --work.
    with tempfile.TemporaryDirectory(prefix="q2-rootfs-", dir=work) as temporary:
        image = pathlib.Path(temporary) / "rootfs.squashfs"
        image.write_bytes(raw)
        names = ("usr/bin/hciplayer", "release/bin/demo", "usr/bin/q2remote", "etc/init.d/S90play")
        listing = subprocess.check_output(["unsquashfs", "-ll", str(image), *names],
                                          stderr=subprocess.DEVNULL).decode("utf-8")
        modes = {}
        for line in listing.splitlines():
            fields = line.split()
            if fields and fields[-1].startswith("squashfs-root/"):
                name = fields[-1][len("squashfs-root/"):]
                if name in names:
                    require(name not in modes, "duplicate rootfs inode listing")
                    modes[name] = fields[0]
        require(set(modes) == set(names) and all(len(mode) == 10 and mode[0] == "-" and
                mode[3] == "x" for mode in modes.values()), "remote/player startup files must be executable regular files")
        startup = subprocess.check_output(["unsquashfs", "-cat", str(image), names[-1]],
                                          stderr=subprocess.DEVNULL)
        require(startup.count(REMOTE_HOOK[1]) == 1 and startup.count(b"/usr/bin/q2remote") == 1,
                "missing or duplicate q2remote startup hook")
        result = {}
        for name in names[:-1]:
            data = subprocess.check_output(["unsquashfs", "-cat", str(image), name],
                                           stderr=subprocess.DEVNULL)
            require(bool(data), f"empty rootfs file: {name}")
            result[name] = sha(data)
        return result

def inspect(candidate, stock_zip, work):
    candidate, stock_zip, work = map(pathlib.Path, (candidate, stock_zip, work))
    work.mkdir(parents=True, exist_ok=True)
    manifest_raw = (candidate / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    require(isinstance(manifest, dict), "manifest is not an object")
    raw = (candidate / "update.tar").read_bytes()
    require(sha(raw) == digest(manifest.get("update_sha256"), "update_sha256"),
            "update.tar SHA-256 mismatch")
    require(manifest.get("input_zip_sha256") == ZIP_SHA, "manifest stock ZIP mismatch")
    require(manifest.get("stock_demo_sha256") == DEMO_SHA, "manifest stock demo mismatch")
    digest(manifest.get("source_sha256"), "source_sha256")
    dev, variant = manifest.get("dev"), manifest.get("variant")
    require(type(dev) is int and dev > 0 and variant in ("stock", "ipod"),
            "a development manifest is required")
    require(manifest.get("version") == dev_tag(dev, "I" if variant == "ipod" else "S"),
            "development tag mismatch")
    packed = members(raw)
    require(info(packed) == manifest["version"], "package/manifest version mismatch")
    original_zip = stock_zip.read_bytes()
    require(sha(original_zip) == ZIP_SHA, "unsupported stock ZIP SHA-256")
    with zipfile.ZipFile(io.BytesIO(original_zip)) as archive:
        original = members(archive.read("Q2 Firmware V1.32/update.tar"))
    require(info(original) == "V1.32", "stock package version mismatch")
    require(packed[MEMBERS[2]] == original[MEMBERS[2]], "kernel differs from pinned stock")
    require(len(packed[MEMBERS[3]]) <= len(original[MEMBERS[3]]), "rootfs exceeds stock size")
    for key, name in (("kernel_sha256", MEMBERS[2]), ("rootfs_sha256", MEMBERS[3])):
        require(sha(packed[name]) == digest(manifest.get(key), key), f"{key} mismatch")
    peq = manifest.get("peq")
    require(isinstance(peq, dict), "missing player manifest")
    expected = {
        "usr/bin/hciplayer": digest(peq.get("sha256"), "peq.sha256"),
        "release/bin/demo": digest(manifest.get("demo_sha256"), "demo_sha256"),
        "usr/bin/q2remote": digest(manifest.get("q2remote_sha256"), "q2remote_sha256"),
    }
    require(rootfs_hashes(packed[MEMBERS[3]], work) == expected,
            "packed player/demo/q2remote hashes differ from manifest")
    return dict(model="Shanling Q2", version=manifest["version"], dev=dev, variant=variant,
                sha256=sha(raw), md5=hashlib.md5(raw).hexdigest(), size=len(raw),
                manifest_sha256=sha(manifest_raw), source_sha256=manifest["source_sha256"],
                kernel_sha256=sha(packed[MEMBERS[2]]), installed=expected)

def remote_run(remote, script, timeout=30):
    output, status = remote.run(script, timeout)
    require(status == 0, "device check failed (missing data, unmounted card or command failure)")
    return output.decode("ascii").strip()

def device(remote=q2remote):
    state = remote.state()
    parts = [line for line in remote_run(remote, BATTERY_SCRIPT).splitlines() if line]
    require(len(parts) == 3, "unexpected battery/boot response")
    require(parts[0].isdigit() and 0 <= int(parts[0]) <= 100, "invalid battery percentage")
    require(parts[1] in ("Charging", "Full", "Discharging", "Not charging", "Unknown"),
            "invalid battery status")
    require(re.fullmatch("[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", parts[2]), "invalid boot ID")
    require(type(state.get("usb")) is int and state["usb"] in range(4), "unknown USB mode")
    require(state["usb"] != 2, "USB storage is active")
    require(isinstance(state.get("uptime"), (int, float)) and
            math.isfinite(state["uptime"]) and state["uptime"] >= 0, "invalid uptime")
    return dict(battery_percent=int(parts[0]), status=parts[1], boot_id=parts[2],
                uptime_seconds=state["uptime"], usb_mode=state["usb"],
                card_mount="/mnt/mmc", observed_at=now())

def ready(snapshot, min_battery=80):
    require(type(min_battery) is int and 0 <= min_battery <= 100,
            "minimum battery must be an integer from 0 to 100")
    reasons = []
    if snapshot["battery_percent"] < min_battery:
        reasons.append(f"battery is below {min_battery}%")
    if snapshot["status"] not in ("Charging", "Full"):
        reasons.append("battery must report Charging or Full")
    return dict(ready=not reasons, reasons=reasons, min_battery=min_battery)

def remote_digests(remote, path):
    lines = remote_run(remote, DIGEST_SCRIPT.format(path=shlex.quote(path)), 120).splitlines()
    require(len(lines) == 2, "unexpected remote digest response")
    values = [line.split()[0] for line in lines]
    digest(values[0], "remote SHA-256")
    require(re.fullmatch("[0-9a-f]{32}", values[1]), "invalid remote MD5")
    return dict(sha256=values[0], md5=values[1])

def save_journal(path, record):
    record = dict(record)
    record.pop("journal_sha256", None)
    record["journal_sha256"] = sha(json.dumps(record, sort_keys=True,
                                            separators=(",", ":")).encode())
    part = path.with_suffix(".part")
    part.write_text(json.dumps(record, indent=2) + "\n")
    part.replace(path)
    return record

def read_journal(path):
    record = json.loads(path.read_text())
    recorded = record.pop("journal_sha256")
    require(recorded == sha(json.dumps(record, sort_keys=True,
                                      separators=(",", ":")).encode()), "journal hash mismatch")
    record["journal_sha256"] = recorded
    return record

def stage(candidate, package, work, remote=q2remote):
    # --work is an explicit local backup destination (use E: for this workflow).
    snapshot = device(remote)
    directory = pathlib.Path(work) / ("stage-" + uuid.uuid4().hex)
    directory.mkdir()
    journal = directory / "journal.json"
    record = dict(state="prepared", created_at=now(), package=package,
                  before=snapshot, backup=None)
    save_journal(journal, record)
    try:
        old = remote_run(remote, OLD_SCRIPT)
        require(old in ("present", "absent"), "unexpected existing-update response")
        if old == "present":
            before = remote_digests(remote, REMOTE_UPDATE)
            backup = directory / "previous-update.tar"
            remote.pull(REMOTE_UPDATE, str(backup))
            raw = backup.read_bytes()
            require(sha(raw) == before["sha256"] and hashlib.md5(raw).hexdigest() == before["md5"],
                    "previous update backup differs from device")
            record["backup"] = dict(before, size=len(raw), path=backup.name)
            save_journal(directory / "previous-update.manifest.json",
                         dict(record["backup"], copied_at=now(), remote_path=REMOTE_UPDATE))
        snapshot_file = directory / "candidate-update.tar"
        shutil.copyfile(pathlib.Path(candidate) / "update.tar", snapshot_file)
        shutil.copyfile(pathlib.Path(candidate) / "manifest.json", directory / "candidate-manifest.json")
        require(sha(snapshot_file.read_bytes()) == package["sha256"], "candidate changed before staging")
        require(sha((directory / "candidate-manifest.json").read_bytes()) == package["manifest_sha256"],
                "manifest changed before staging")
        record["state"] = "backed_up"
        save_journal(journal, record)
        device(remote)  # Recheck mount/USB after the backup, immediately before writing.
        temporary = "/mnt/mmc/.q2-update-" + uuid.uuid4().hex + ".tar"
        quoted = shlex.quote(temporary)
        # q2remote.push promotes its .part before reporting MD5. Upload to a
        # fresh name so a truncated transfer cannot replace update.tar.
        remote_run(remote, f"# q2update reserve {temporary}\n"
                   f"test ! -e {quoted} && test ! -L {quoted} && "
                   f"test ! -e {quoted}.part && test ! -L {quoted}.part")
        record["upload_path"] = temporary
        save_journal(journal, record)
        require(remote.push(snapshot_file, temporary) == package["md5"], "upload MD5 mismatch")
        readback = remote_digests(remote, temporary)
        require(readback == {k: package[k] for k in ("sha256", "md5")}, "staged file readback mismatch")
        device(remote)
        # Recheck the hashes and original destination in the promotion script.
        # This preserves an independently changed card update instead of replacing it.
        guard = (f'test "$(sha256sum {REMOTE_UPDATE} | cut -d " " -f1)" = '
                 f'{record["backup"]["sha256"]}' if record["backup"] else
                 f"test ! -e {REMOTE_UPDATE}")
        promote = (f"# q2update promote {temporary}\nset -e\nmountpoint -q /mnt/mmc\n"
                   f"test ! -L {quoted}\ntest -f {quoted}\n"
                   f'test "$(sha256sum {quoted} | cut -d " " -f1)" = {package["sha256"]}\n'
                   f'test "$(md5sum {quoted} | cut -d " " -f1)" = {package["md5"]}\n'
                   f"test ! -L {REMOTE_UPDATE}\n{guard}\n"
                   f"mv {quoted} {REMOTE_UPDATE}\nsync\n")
        remote_run(remote, promote, 120)
        require(remote_digests(remote, REMOTE_UPDATE) == readback, "promoted file readback mismatch")
        record.update(state="staged", staged_at=now(), readback=readback)
        saved = save_journal(journal, record)
        return dict(journal=str(journal), journal_sha256=saved["journal_sha256"],
                    staged=True, package=package, device=snapshot, **ready(snapshot))
    except Exception:
        record["state"] = "failed"
        save_journal(journal, record)
        raise

def ready_check(package, journal, remote=q2remote, min_battery=80):
    record = read_journal(journal)
    require(record["state"] in ("staged", "ready"), "journal is not a completed stage")
    require(record["package"] == package, "journal/candidate mismatch")
    require(remote_digests(remote, REMOTE_UPDATE) == {k: package[k] for k in ("sha256", "md5")},
            "card update differs from candidate")
    snapshot = device(remote)
    result = ready(snapshot, min_battery)
    record.update(state="ready" if result["ready"] else "staged",
                  before=snapshot, readiness=result)
    saved = save_journal(journal, record)
    return dict(package=package, device=snapshot, journal=str(journal),
                journal_sha256=saved["journal_sha256"], **result)

def verify(package, journal, remote=q2remote):
    record = read_journal(journal)
    require(record["state"] == "ready", "a successful ready check must precede verification")
    require(record["package"] == package, "journal/candidate mismatch")
    snapshot = device(remote)
    actual = {}
    for line in remote_run(remote, INSTALLED_SCRIPT, 120).splitlines():
        fields = line.split()
        require(len(fields) == 2, "invalid installed hash response")
        actual[fields[1].lstrip("/")] = digest(fields[0], "installed SHA-256")
    matches = actual == package["installed"]
    rebooted = snapshot["boot_id"] != record["before"]["boot_id"]
    result = dict(verified=matches and rebooted, installed_match=matches,
                  reboot_observed=rebooted, before_uptime_seconds=record["before"]["uptime_seconds"],
                  after_uptime_seconds=snapshot["uptime_seconds"],
                  uptime_reset=snapshot["uptime_seconds"] < record["before"]["uptime_seconds"],
                  installed=actual)
    record.update(verification=result, after=snapshot)
    if result["verified"]:
        record["state"] = "verified"
    saved = save_journal(journal, record)
    return dict(result, journal=str(journal), journal_sha256=saved["journal_sha256"])

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("inspect", "check", "ready", "stage", "verify"))
    p.add_argument("candidate", type=pathlib.Path)
    p.add_argument("--stock-zip", type=pathlib.Path, required=True)
    p.add_argument("--work", type=pathlib.Path, required=True,
                   help="local scratch/backup destination; use a directory on E: in the Q2 workflow")
    p.add_argument("--journal", type=pathlib.Path, help="stage journal; required for ready/verify")
    p.add_argument("--min-battery", type=int, default=80,
                   help="check/ready threshold, 0..100 (default: 80); the stock updater guard remains active")
    a = p.parse_args()
    try:
        require(0 <= a.min_battery <= 100, "--min-battery must be 0..100")
        package = inspect(a.candidate, a.stock_zip, a.work)
        if a.action == "inspect":
            result = dict(valid=True, package=package)
        elif a.action == "stage":
            result = stage(a.candidate, package, a.work)
        elif a.action in ("ready", "verify"):
            require(a.journal is not None, "--journal is required")
            result = (ready_check(package, a.journal, min_battery=a.min_battery)
                      if a.action == "ready" else verify(package, a.journal))
        else:
            snapshot = device()
            result = dict(package=package, device=snapshot, **ready(snapshot, a.min_battery))
        print(json.dumps(result, indent=2))
        return 0 if a.action == "stage" or (result.get("ready", True) and result.get("verified", True)) else 2
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        print(json.dumps(dict(valid=False, error=str(error))))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
