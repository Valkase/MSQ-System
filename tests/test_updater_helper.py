"""
Tests for the swap helper (updater/updater_helper/main.py) and the app-side
updater/apply.py: successful swap, backup, rollback when the new version dies,
abort paths that must leave the old install untouched. No real processes are started.
"""

import hashlib
import os
import time

import pytest

from updater import apply as apply_mod
from updater.updater_helper import main as helper

OLD, NEW = b"old-exe", b"new-exe"
NEW_SHA = hashlib.sha256(NEW).hexdigest()


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class FakePopen:
    def __init__(self, procs):
        self.procs = list(procs)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return self.procs.pop(0)


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture()
def install(tmp_path):
    target = tmp_path / "app" / "HealthCenterSystem.exe"
    target.parent.mkdir()
    target.write_bytes(OLD)
    new_exe = tmp_path / "stage" / "HealthCenterSystem.exe"
    new_exe.parent.mkdir()
    new_exe.write_bytes(NEW)
    return target, new_exe


def run(install, popen, *, exists=lambda pid: False, replace=helper.replace_with_retry, sha=NEW_SHA, wait=5.0):
    target, new_exe = install
    t = FakeTime()
    code = helper.perform_update(
        pid=123,
        target=target,
        new_exe=new_exe,
        expected_sha256=sha,
        wait_timeout=wait,
        grace=3.0,
        popen=popen,
        exists=exists,
        sleep=t.sleep,
        clock=t.clock,
        replace=replace,
    )
    return code


# --- apply_update / rollback -----------------------------------------------------


def test_apply_update_swaps_and_keeps_a_backup(install):
    target, new_exe = install
    backup = helper.apply_update(target, new_exe, NEW_SHA)

    assert target.read_bytes() == NEW
    assert backup.read_bytes() == OLD
    assert not target.with_name(target.name + ".new").exists()


def test_apply_update_rejects_a_checksum_mismatch_and_changes_nothing(install):
    target, new_exe = install
    with pytest.raises(helper.UpdateFailed):
        helper.apply_update(target, new_exe, hashlib.sha256(b"other").hexdigest())
    assert target.read_bytes() == OLD
    assert not target.with_name(target.name + ".new").exists()


def test_failed_replace_leaves_the_old_exe_in_place(install):
    target, new_exe = install

    def boom(src, dst):
        raise PermissionError("locked")

    with pytest.raises(helper.UpdateFailed):
        helper.apply_update(target, new_exe, NEW_SHA, replace=boom)
    assert target.read_bytes() == OLD
    assert not target.with_name(target.name + ".new").exists()


def test_replace_with_retry_eventually_succeeds(tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_bytes(b"x")
    calls = {"n": 0}
    real = os.replace

    def flaky(s, d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("busy")
        real(s, d)

    orig, helper.os.replace = helper.os.replace, flaky
    try:
        helper.replace_with_retry(src, dst, attempts=5, delay=0, sleep=lambda s: None)
    finally:
        helper.os.replace = orig
    assert dst.read_bytes() == b"x" and calls["n"] == 3


# --- wait_for_exit / launch_and_watch ---------------------------------------------


def test_wait_for_exit_returns_once_the_process_is_gone():
    t = FakeTime()
    states = iter([True, True, False])
    assert helper.wait_for_exit(1, 10, exists=lambda p: next(states), sleep=t.sleep, clock=t.clock)


def test_wait_for_exit_times_out():
    t = FakeTime()
    assert not helper.wait_for_exit(1, 2, exists=lambda p: True, sleep=t.sleep, clock=t.clock)


@pytest.mark.parametrize("code,healthy", [(None, True), (0, True), (1, False)])
def test_launch_and_watch(tmp_path, code, healthy):
    t = FakeTime()
    ok = helper.launch_and_watch(
        tmp_path / "x.exe", 3.0, popen=FakePopen([FakeProc(code)]), sleep=t.sleep, clock=t.clock
    )
    assert ok is healthy


# --- perform_update (whole flow) ---------------------------------------------------


def test_successful_update(install):
    target, new_exe = install
    popen = FakePopen([FakeProc(None)])

    assert run(install, popen) == helper.EXIT_OK
    assert target.read_bytes() == NEW
    assert len(popen.calls) == 1
    assert not new_exe.exists()  # staged file cleaned up


def test_new_version_crashing_triggers_rollback_and_relaunch_of_old(install):
    target, _ = install
    popen = FakePopen([FakeProc(1), FakeProc(None)])  # new crashes, old stays up

    assert run(install, popen) == helper.EXIT_ROLLED_BACK
    assert target.read_bytes() == OLD
    assert len(popen.calls) == 2


def test_app_that_never_exits_aborts_without_touching_anything(install):
    target, new_exe = install
    popen = FakePopen([])

    assert run(install, popen, exists=lambda pid: True, wait=2.0) == helper.EXIT_FAILED
    assert target.read_bytes() == OLD
    assert new_exe.exists()
    assert popen.calls == []


def test_failed_install_relaunches_the_old_version(install):
    target, _ = install
    popen = FakePopen([FakeProc(None)])

    def boom(src, dst):
        raise PermissionError("no write access")

    assert run(install, popen, replace=boom) == helper.EXIT_FAILED
    assert target.read_bytes() == OLD
    assert len(popen.calls) == 1  # the old app is started again


def test_tampered_staged_file_is_refused(install):
    target, _ = install
    popen = FakePopen([FakeProc(None)])
    assert run(install, popen, sha=hashlib.sha256(b"something else").hexdigest()) == helper.EXIT_FAILED
    assert target.read_bytes() == OLD


# --- app-side apply.py ---------------------------------------------------------------


def test_start_update_refuses_outside_a_frozen_build(tmp_path):
    staged = tmp_path / "s.exe"
    staged.write_bytes(NEW)
    with pytest.raises(apply_mod.UpdateApplyError):
        apply_mod.start_update(staged, frozen=False)


def test_start_update_copies_helper_and_passes_the_right_arguments(tmp_path):
    staged = tmp_path / "stage" / "HealthCenterSystem.exe"
    staged.parent.mkdir()
    staged.write_bytes(NEW)
    helper_src = tmp_path / "bundled" / apply_mod.HELPER_NAME
    helper_src.parent.mkdir()
    helper_src.write_bytes(b"helper")
    target = tmp_path / "app" / "HealthCenterSystem.exe"
    seen = {}

    def fake_popen(args, **kwargs):
        seen["args"] = args

    copy = apply_mod.start_update(
        staged,
        pid=42,
        target=target,
        helper_source=helper_src,
        log_path=tmp_path / "updater.log",
        popen=fake_popen,
        frozen=True,
    )

    assert copy == staged.parent / apply_mod.HELPER_NAME and copy.read_bytes() == b"helper"
    args = seen["args"]
    assert args[0] == str(copy)
    assert args[args.index("--pid") + 1] == "42"
    assert args[args.index("--target") + 1] == str(target)
    assert args[args.index("--new") + 1] == str(staged)
    assert args[args.index("--sha256") + 1] == NEW_SHA


def test_start_update_reports_a_missing_helper(tmp_path):
    staged = tmp_path / "s.exe"
    staged.write_bytes(NEW)
    with pytest.raises(apply_mod.UpdateApplyError):
        apply_mod.start_update(staged, helper_source=tmp_path / "nope.exe", frozen=True)


def test_cleanup_removes_only_old_update_folders(tmp_path):
    old = tmp_path / "hcs-update-old"
    fresh = tmp_path / "hcs-update-fresh"
    other = tmp_path / "unrelated-folder"
    for d in (old, fresh, other):
        d.mkdir()
    ancient = time.time() - 10_000
    os.utime(old, (ancient, ancient))
    os.utime(other, (ancient, ancient))

    assert apply_mod.cleanup_stale_staging(tmp_root=tmp_path) == 1
    assert not old.exists() and fresh.exists() and other.exists()
