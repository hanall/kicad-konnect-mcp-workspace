#!/usr/bin/env python3
"""libngspice 공유 라이브러리로 넷리스트 하나를 배치 실행하고 모든 출력을 stdout에 쓴다.

사용법: python3 -I scripts/ngspice_shared_batch.py <libngspice.so> <netlist.cir>

KiCad 10 AppImage가 번들한 libngspice(45.2)를 GUI 없이 그대로 쓰기 위한 보조 도구다.
.meas 결과는 ngspice가 "name = value" 줄로 출력하므로 호출자가 그대로 파싱한다.
"""
import ctypes
import os
import sys


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    libpath, cir = sys.argv[1], os.path.abspath(sys.argv[2])
    lib = ctypes.CDLL(libpath)

    SendChar = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    SendStat = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    ControlledExit = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
    SendData = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
    SendInitData = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
    BGThread = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

    def send_char(text, _ident, _user):
        line = text.decode("utf-8", "replace")
        for prefix in ("stdout ", "stderr "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        print(line)
        return 0

    callbacks = [
        SendChar(send_char),
        SendStat(lambda *_: 0),
        ControlledExit(lambda *_: 0),
        SendData(lambda *_: 0),
        SendInitData(lambda *_: 0),
        BGThread(lambda *_: 0),
    ]
    lib.ngSpice_Init.restype = ctypes.c_int
    lib.ngSpice_Command.restype = ctypes.c_int
    lib.ngSpice_Init(*callbacks, None)
    lib.ngSpice_Command(b"version -s")
    lib.ngSpice_Command(f"cd {os.path.dirname(cir)}".encode())
    rc = lib.ngSpice_Command(f"source {cir}".encode())
    if rc != 0:
        print(f"source failed rc={rc}", file=sys.stderr)
        return 1
    rc = lib.ngSpice_Command(b"run")
    if rc != 0:
        print(f"run failed rc={rc}", file=sys.stderr)
        return 1
    sys.stdout.flush()
    # quit은 호출하지 않는다(공유 라이브러리가 프로세스를 종료시킬 수 있다).
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
