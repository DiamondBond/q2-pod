#!/usr/bin/env python3
"""Offline update-guard tests. All device operations use an in-memory fake."""
import hashlib
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import q2update as q

def tar(kernel=b"kernel", rootfs=b"rootfs", version="V001i", extra=None, bad_md5=False):
    details = (f"Shanling Q2\n{version}\n" +
               hashlib.md5(kernel).hexdigest() + "  " + q.MEMBERS[2] + "\n" +
               hashlib.md5(rootfs).hexdigest() + "  " + q.MEMBERS[3] + "\n").encode()
    if bad_md5:
        details = details.replace(hashlib.md5(kernel).hexdigest().encode(), b"0" * 32)
    data = {q.MEMBERS[0]: details, q.MEMBERS[2]: kernel, q.MEMBERS[3]: rootfs}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name in (*q.MEMBERS, *((extra,) if extra else ())):
            entry = tarfile.TarInfo(name)
            if name == q.MEMBERS[1]:
                entry.type = tarfile.DIRTYPE
                archive.addfile(entry)
            else:
                blob = data.get(name, b"extra")
                entry.size = len(blob)
                archive.addfile(entry, io.BytesIO(blob))
    return stream.getvalue()

class Remote:
    def __init__(self):
        self.capacity, self.status, self.usb, self.mounted = 90, "Charging", 3, True
        self.boot = "11111111-1111-1111-1111-111111111111"
        self.uptime = 200.0
        self.files = {q.REMOTE_UPDATE: b"previous update"}
        self.installed, self.pushes, self.promotions = {}, [], []
        self.bad_readback, self.collide = False, False

    @property
    def update(self):
        return self.files.get(q.REMOTE_UPDATE)

    @update.setter
    def update(self, data):
        if data is None:
            self.files.pop(q.REMOTE_UPDATE, None)
        else:
            self.files[q.REMOTE_UPDATE] = data

    def state(self):
        return {"usb": self.usb, "uptime": self.uptime}

    def run(self, script, timeout):
        if script == q.BATTERY_SCRIPT:
            return f"{self.capacity}\n{self.status}\n{self.boot}\n".encode(), 0 if self.mounted else 1
        if script == q.OLD_SCRIPT:
            return b"present" if self.update is not None else b"absent", 0
        if script == q.INSTALLED_SCRIPT:
            return "".join(f"{v}  /{k}\n" for k, v in self.installed.items()).encode(), 0
        if script.startswith("# q2update reserve "):
            path = script.splitlines()[0].split()[-1]
            return b"", 1 if self.collide or path in self.files or path + ".part" in self.files else 0
        if script.startswith("# q2update promote "):
            path = script.splitlines()[0].split()[-1]
            self.promotions.append(path)
            self.update = self.files.pop(path)
            return b"", 0
        if script.startswith("sha256sum "):
            path = script.split()[1]
            raw = b"corrupt" if self.bad_readback and self.pushes else self.files[path]
            return (q.sha(raw) + "  " + path + "\n" +
                    hashlib.md5(raw).hexdigest() + "  " + path + "\n").encode(), 0
        raise AssertionError(script)

    def pull(self, remote, local):
        assert remote == q.REMOTE_UPDATE
        pathlib.Path(local).write_bytes(self.update)

    def push(self, local, remote):
        assert remote.startswith("/mnt/mmc/.q2-update-") and remote.endswith(".tar")
        self.pushes.append((str(local), remote))
        self.files[remote] = pathlib.Path(local).read_bytes()
        return hashlib.md5(self.files[remote]).hexdigest()

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="q2update-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.candidate, self.work = self.base / "candidate", self.base / "work"
        self.candidate.mkdir()
        self.work.mkdir()
        self.zip = self.base / "stock.zip"
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("Q2 Firmware V1.32/update.tar",
                             tar(rootfs=b"stock" * 100, version="V1.32"))
        self.pin = patch.object(q, "ZIP_SHA", q.sha(self.zip.read_bytes()))
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.hashes = {"usr/bin/hciplayer": q.sha(b"player"),
                       "release/bin/demo": q.sha(b"demo"),
                       "usr/bin/q2remote": q.sha(b"remote")}
        self.rootfs = patch.object(q, "rootfs_hashes", return_value=dict(self.hashes))
        self.rootfs.start()
        self.addCleanup(self.rootfs.stop)
        self.write_candidate()

    def write_candidate(self, raw=None, **changes):
        raw = tar() if raw is None else raw
        (self.candidate / "update.tar").write_bytes(raw)
        m = dict(input_zip_sha256=q.ZIP_SHA, stock_demo_sha256=q.DEMO_SHA,
                 source_sha256=q.sha(b"source"), update_sha256=q.sha(raw), version="V001i",
                 dev=1, variant="ipod", kernel_sha256=q.sha(b"kernel"),
                 rootfs_sha256=q.sha(b"rootfs"), demo_sha256=self.hashes["release/bin/demo"],
                 q2remote_sha256=self.hashes["usr/bin/q2remote"],
                 peq={"sha256": self.hashes["usr/bin/hciplayer"]})
        m.update(changes)
        (self.candidate / "manifest.json").write_text(json.dumps(m))

    def inspect(self):
        return q.inspect(self.candidate, self.zip, self.work)

    def staged(self):
        r = Remote()
        package = self.inspect()
        result = q.stage(self.candidate, package, self.work, r)
        return r, package, pathlib.Path(result["journal"])

    def test_valid_package(self):
        self.assertEqual(self.inspect()["installed"], self.hashes)

    def test_hash_and_stock_identity(self):
        for changes in ({"update_sha256": "0" * 64}, {"source_sha256": "missing"},
                        {"input_zip_sha256": "0" * 64}, {"stock_demo_sha256": "0" * 64}):
            with self.subTest(changes=changes):
                self.write_candidate(**changes)
                with self.assertRaises(ValueError):
                    self.inspect()
        self.write_candidate()
        self.zip.write_bytes(b"wrong zip")
        with self.assertRaisesRegex(ValueError, "stock ZIP"):
            self.inspect()

    def test_kernel_md5_and_members(self):
        cases = [tar(kernel=b"other"), tar(bad_md5=True), tar(extra="../escape"),
                 tar(extra=q.MEMBERS[0]), tar(version="V002i"), tar() + tar(),
                 tar() + b"hidden trailing data", tar()[:3584]]
        for raw in cases:
            with self.subTest(sha=q.sha(raw)):
                self.write_candidate(raw)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_dev_remote_and_rootfs_required(self):
        for changes in ({"dev": False}, {"dev": 0}, {"version": "V146I"},
                        {"q2remote_sha256": None}, {"rootfs_sha256": "0" * 64}):
            with self.subTest(changes=changes):
                self.write_candidate(**changes)
                with self.assertRaises(ValueError):
                    self.inspect()
        self.write_candidate()
        with patch.object(q, "rootfs_hashes", return_value={}):
            with self.assertRaisesRegex(ValueError, "packed"):
                self.inspect()

    def test_ready_threshold_and_charging(self):
        r = Remote()
        for capacity, status, expected in ((79, "Charging", False), (80, "Charging", True),
                                           (100, "Full", True), (99, "Discharging", False),
                                           (99, "Unknown", False)):
            r.capacity, r.status = capacity, status
            self.assertEqual(q.ready(q.device(r))["ready"], expected)

    def test_custom_battery_threshold_and_record(self):
        r, package, journal = self.staged()
        for capacity, expected in ((19, False), (20, True)):
            r.capacity = capacity
            result = q.ready_check(package, journal, r, min_battery=20)
            self.assertEqual(result["ready"], expected)
            self.assertEqual(q.read_journal(journal)["readiness"]["min_battery"], 20)
        for threshold in (-1, 101, 20.5, True):
            with self.assertRaises(ValueError):
                q.ready(q.device(r), threshold)
        r.status = "Discharging"
        self.assertFalse(q.ready(q.device(r), 20)["ready"])

    def test_usb_unmounted_and_unknown_fail_closed(self):
        for usb, mounted in ((2, True), (3, False), (None, True), (9, True)):
            r = Remote()
            r.usb, r.mounted = usb, mounted
            with self.assertRaises(ValueError):
                q.stage(self.candidate, self.inspect(), self.work, r)
            self.assertEqual(r.pushes, [])

    def test_invalid_boot_id_fails_closed(self):
        r = Remote()
        r.boot = "-" * 36
        with self.assertRaisesRegex(ValueError, "boot ID"):
            q.device(r)

    def test_low_battery_stage_backups_and_readback(self):
        r = Remote()
        r.capacity = 23
        old = r.update
        result = q.stage(self.candidate, self.inspect(), self.work, r)
        self.assertTrue(result["staged"])
        self.assertFalse(result["ready"])
        journal = pathlib.Path(result["journal"])
        record = q.read_journal(journal)
        self.assertEqual((journal.parent / "previous-update.tar").read_bytes(), old)
        self.assertEqual(record["backup"]["sha256"], q.sha(old))
        q.read_journal(journal.parent / "previous-update.manifest.json")
        self.assertEqual(r.update, (self.candidate / "update.tar").read_bytes())

    def test_readback_corruption_fails(self):
        r = Remote()
        r.bad_readback = True
        with self.assertRaisesRegex(ValueError, "readback"):
            q.stage(self.candidate, self.inspect(), self.work, r)
        records = list(self.work.glob("stage-*/journal.json"))
        self.assertEqual(q.read_journal(records[0])["state"], "failed")
        self.assertEqual(r.update, b"previous update")
        self.assertEqual(r.promotions, [])

    def test_upload_path_collision_blocks_before_push(self):
        r = Remote()
        r.collide = True
        with self.assertRaises(ValueError):
            q.stage(self.candidate, self.inspect(), self.work, r)
        self.assertEqual(r.pushes, [])
        self.assertEqual(r.update, b"previous update")

    def test_ready_requires_same_staged_file(self):
        r, package, journal = self.staged()
        r.update = b"wrong update"
        with self.assertRaisesRegex(ValueError, "card update"):
            q.ready_check(package, journal, r)

    def test_verify_requires_ready_reboot_and_hashes(self):
        r, package, journal = self.staged()
        with self.assertRaisesRegex(ValueError, "ready"):
            q.verify(package, journal, r)
        q.ready_check(package, journal, r)
        r.installed = dict(self.hashes)
        self.assertFalse(q.verify(package, journal, r)["verified"])
        r.boot = "22222222-2222-2222-2222-222222222222"
        r.uptime = 10
        r.installed["usr/bin/hciplayer"] = q.sha(b"wrong")
        self.assertFalse(q.verify(package, journal, r)["verified"])
        r.installed = dict(self.hashes)
        result = q.verify(package, journal, r)
        self.assertTrue(result["verified"])
        self.assertTrue(result["uptime_reset"])
        self.assertEqual(q.read_journal(journal)["state"], "verified")

    def test_journal_tampering_rejected(self):
        r, package, journal = self.staged()
        record = json.loads(journal.read_text())
        record["state"] = "ready"
        journal.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "journal hash"):
            q.ready_check(package, journal, r)

class RootfsTests(unittest.TestCase):
    def test_fixed_file_extraction_metadata_and_startup(self):
        with tempfile.TemporaryDirectory(prefix="q2-rootfs-test-") as tmp:
            names = ("usr/bin/hciplayer", "release/bin/demo", "usr/bin/q2remote", "etc/init.d/S90play")
            good_listing = "".join("-rwxr-xr-x root/root 12 2026-01-01 00:00 squashfs-root/" +
                                   name + "\n" for name in names).encode()
            for problem in ("none", "mode", "symlink", "hook", "duplicate", "empty", "corrupt"):
                with self.subTest(problem=problem):
                    def output(command, **kwargs):
                        if problem == "corrupt":
                            raise q.subprocess.CalledProcessError(1, command)
                        if command[1] == "-ll":
                            if problem == "mode":
                                return good_listing.replace(b"-rwxr-xr-x", b"-rw-r--r--")
                            if problem == "symlink":
                                return good_listing.replace(b"-rwxr-xr-x", b"lrwxrwxrwx")
                            return good_listing
                        if command[-1] == names[-1]:
                            return b"no hook" if problem == "hook" else q.REMOTE_HOOK[1] * (
                                2 if problem == "duplicate" else 1)
                        return b"" if problem == "empty" else command[-1].encode()
                    with patch.object(q.subprocess, "check_output", side_effect=output):
                        if problem == "none":
                            self.assertEqual(len(q.rootfs_hashes(b"image", tmp)), 3)
                        else:
                            with self.assertRaises((ValueError, q.subprocess.CalledProcessError)):
                                q.rootfs_hashes(b"image", tmp)

if __name__ == "__main__":
    unittest.main()
