#!/usr/bin/env python3
# 용도: ACUW 격리 레인의 정확한 KiCad 창을 정상 종료하고 다시 연다.
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import json

from konnect_gui_sync import SyncError


ACUW = Path("/home/hanol/ai-computer-use-workspace/scripts")
EDITOR_SUFFIXES = (" — 회로도 편집기", " — Schematic Editor")
GUI_ENV_KEYS = {"XDG_CONFIG_HOME", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR",
                "KICAD10_3DMODEL_DIR", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "LANG", "LC_ALL"}


def run(argv, *, env=None, timeout=20):
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise SyncError("desktop_command_failed", "공유 화면 명령이 실패했습니다.",
                        command=str(argv[0]), returncode=result.returncode,
                        stderr=result.stderr[-2000:])
    return result.stdout


def process_matches_schematic(argv, cwd, schematic):
    if not argv or Path(argv[0]).name not in {"kicad", "eeschema"}:
        return False
    designs = [Path(value) for value in argv[1:] if Path(value).suffix in {".kicad_pro", ".kicad_sch"}]
    if len(designs) != 1:
        return False
    target = designs[0] if designs[0].is_absolute() else Path(cwd) / designs[0]
    return target.resolve() in {schematic, schematic.with_suffix(".kicad_pro")}


class LinuxDesktop:
    def _lane(self, lane):
        state = json.loads(run(["bash", str(ACUW / "instance.sh"), "status", lane, "--json"]))
        display = state.get("display", "")
        if state.get("name") != lane or state.get("state") not in {"busy", "idle"} or not re.fullmatch(r":\d+", display) or int(display[1:]) < 100:
            raise SyncError("unsafe_lane", "실행 중인 명명된 격리 ACUW 레인만 지원합니다.")
        # env 출력은 절대로 eval하지 않는다. 관측된 DISPLAY와 환경 선언을 대조만 한다.
        declared = {}
        for line in run(["bash", str(ACUW / "instance.sh"), "env", lane]).splitlines():
            tokens = shlex.split(line)
            if len(tokens) == 2 and tokens[0] == "export" and "=" in tokens[1]:
                key, value = tokens[1].split("=", 1)
                declared[key] = value
        if declared.get("ACUW_DISPLAY") != display or declared.get("ACUW_BACKEND") != "visible-xvfb":
            raise SyncError("unsafe_lane", "레인의 실제 화면과 선언 환경이 다릅니다.")
        return display, {**os.environ, "DISPLAY": display}

    def _windows(self, env):
        windows = []
        for line in run(["wmctrl", "-lpGx"], env=env).splitlines():
            fields = line.split(None, 9)
            if len(fields) == 10:
                windows.append({"window_id": fields[0], "pid": int(fields[2]),
                                "geometry": [int(value) for value in fields[3:7]],
                                "wm_class": fields[7], "title": fields[9]})
        return windows

    def _process(self, pid, schematic):
        proc = Path("/proc") / str(pid)
        if proc.stat().st_uid != os.getuid():
            raise SyncError("wrong_owner", "KiCad 프로세스의 소유자가 다릅니다.")
        argv = [value.decode() for value in (proc / "cmdline").read_bytes().split(b"\0") if value]
        if not process_matches_schematic(argv, (proc / "cwd").resolve(), schematic):
            raise SyncError("wrong_document", "창의 실제 프로세스 인자가 지정 프로젝트와 다릅니다.")
        executable = (proc / "exe").resolve()
        if executable.name not in {"kicad", "eeschema"}:
            raise SyncError("wrong_editor", "실행 파일이 KiCad 편집기가 아닙니다.")
        start_time = (proc / "stat").read_text().rsplit(") ", 1)[1].split()[19]
        gui_env = {}
        for value in (proc / "environ").read_bytes().split(b"\0"):
            if b"=" in value:
                key, data = value.split(b"=", 1)
                if key.decode() in GUI_ENV_KEYS:
                    gui_env[key.decode()] = data.decode()
        return start_time, gui_env

    def observe(self, lane, schematic):
        display, env = self._lane(lane)
        windows = self._windows(env)
        candidates = []
        for window in windows:
            suffix = next((suffix for suffix in EDITOR_SUFFIXES if window["title"].endswith(suffix)), None)
            if suffix is None:
                continue
            title_name = window["title"][:-len(suffix)].lstrip("*")
            if title_name != schematic.stem:
                continue
            try:
                start_time, gui_env = self._process(window["pid"], schematic)
            except (OSError, ValueError, SyncError):
                continue
            candidates.append({**window, "start_time": start_time, "display": display,
                               "lane": lane, "dirty": window["title"].startswith("*"), "_gui_env": gui_env})
        if len(candidates) != 1:
            raise SyncError("ambiguous_editor", "지정 루트 회로도가 보이는 정확한 편집기 창 하나가 필요합니다.", count=len(candidates))
        editor = candidates[0]
        for window in windows:
            if window["pid"] == editor["pid"] and window["window_id"] != editor["window_id"]:
                transient = run(["xprop", "-id", window["window_id"], "WM_TRANSIENT_FOR"], env=env)
                ids = re.findall(r"0x[0-9a-fA-F]+", transient)
                if any(int(value, 16) == int(editor["window_id"], 16) for value in ids):
                    raise SyncError("editor_dialog_open", "KiCad 대화상자를 먼저 처리해야 합니다.")
        lock = schematic.with_name("~" + schematic.name + ".lck")
        if not lock.is_file() or lock.is_symlink():
            raise SyncError("missing_editor_lock", "편집기가 소유한 회로도 잠금을 확인할 수 없습니다.")
        return editor

    def close(self, observation, schematic):
        current = self.observe(observation["lane"], schematic)
        if current != observation or current["dirty"]:
            raise SyncError("stale_editor", "종료 직전 GUI 상태가 달라졌습니다.")
        _, env = self._lane(observation["lane"])
        run(["wmctrl", "-ic", observation["window_id"]], env=env)
        deadline = time.monotonic() + 12
        lock = schematic.with_name("~" + schematic.name + ".lck")
        exists = True
        while time.monotonic() < deadline:
            exists = any(window["window_id"] == observation["window_id"] for window in self._windows(env))
            if not exists and not os.path.lexists(lock):
                return
            time.sleep(0.1)
        # 저장 확인 창을 누르거나 잠금을 삭제하지 않는다.
        raise SyncError("close_refused", "편집기 또는 잠금이 남았습니다. 저장/폐기 대화상자를 자동 승인하지 않았습니다.", editor_closed=not exists)

    def reopen(self, observation, schematic):
        lane = observation["lane"]
        self._lane(lane)
        try:
            existing = self.observe(lane, schematic)
        except SyncError as error:
            if error.kind != "ambiguous_editor" or error.evidence.get("count") != 0:
                raise
        else:
            raise SyncError("foreign_editor", "재열기 전에 다른 편집기 창이 생겼습니다. 임의로 사용하지 않습니다.", editor=existing["window_id"])
        executable = shutil.which("eeschema")
        if not executable:
            raise SyncError("missing_editor", "eeschema 실행기를 찾을 수 없습니다.")
        command = ["bash", str(ACUW / "instance.sh"), "run", lane, "--", "run-in-workspace.sh", "--", "env"]
        command += [f"{key}={value}" for key, value in observation["_gui_env"].items()]
        command += [executable, str(schematic)]
        run(command, timeout=45)
        deadline = time.monotonic() + 20
        last_error = None
        stable_since = None
        while time.monotonic() < deadline:
            try:
                current = self.observe(lane, schematic)
                if current["dirty"]:
                    raise SyncError("unexpected_dirty_editor", "재열기 직후 GUI가 수정 상태입니다.")
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 1:
                    run(["bash", str(ACUW / "instance.sh"), "run", lane, "--", "window-control.sh", "maximize", current["window_id"]])
                    return current
            except SyncError as error:
                last_error = error
                stable_since = None
            time.sleep(0.2)
        raise SyncError("reopen_unconfirmed", "회로도 재열기의 정상 상태를 확인하지 못했습니다.", reason=str(last_error))

    def capture(self, lane):
        output = run(["bash", str(ACUW / "instance.sh"), "run", lane, "--", "capture.sh"])
        path = Path(output.strip().splitlines()[-1])
        if not path.is_file() or path.suffix != ".png":
            raise SyncError("capture_failed", "공유 화면 캡처를 확인할 수 없습니다.")
        return str(path)
