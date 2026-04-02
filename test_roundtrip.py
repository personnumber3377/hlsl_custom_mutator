from __future__ import annotations
import argparse
import difflib
import subprocess
import tempfile
from pathlib import Path

from hlsl_input_format import unpack_blob, pack_blob
from hlsl_parser import parse_to_tree
from hlsl_unparser import unparse_tu


def run_fuzzer_once(bin_path: str, blob_path: str) -> tuple[int, str, str]:
    p = subprocess.run(
        [bin_path, "-runs=1", blob_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return p.returncode, p.stdout, p.stderr


def normalize_stderr(s: str) -> str:
    keep = []
    for line in s.splitlines():
        if "INFO: Seed:" in line:
            continue
        if "artifact_prefix" in line:
            continue
        if "Test unit written to" in line:
            continue
        keep.append(line)
    return "\n".join(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fuzzer_bin", help="path to your libFuzzer-linked dxc binary")
    ap.add_argument("input_blob", help="path to a single header+source test file")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    blob = Path(args.input_blob).read_bytes()
    header, src_bytes = unpack_blob(blob)
    src = src_bytes.decode("utf-8", errors="ignore")

    try:
        tu = parse_to_tree(src)
    except Exception as e:
        print("[FAIL] parse(original) failed")
        print(e)
        raise SystemExit(1)

    rebuilt_src = unparse_tu(tu)

    try:
        tu2 = parse_to_tree(rebuilt_src)
    except Exception as e:
        print("[FAIL] parse(unparsed(original)) failed")
        print(e)
        diff = "\n".join(difflib.unified_diff(
            src.splitlines(),
            rebuilt_src.splitlines(),
            fromfile="original",
            tofile="rebuilt",
            lineterm="",
        ))
        print(diff)
        raise SystemExit(1)

    rebuilt_blob = pack_blob(header, rebuilt_src.encode("utf-8", errors="ignore"))

    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "orig.bin"
        p2 = Path(td) / "rebuilt.bin"
        p1.write_bytes(blob)
        p2.write_bytes(rebuilt_blob)

        rc1, out1, err1 = run_fuzzer_once(args.fuzzer_bin, str(p1))
        rc2, out2, err2 = run_fuzzer_once(args.fuzzer_bin, str(p2))

    nerr1 = normalize_stderr(err1)
    nerr2 = normalize_stderr(err2)

    if rc1 != rc2 or nerr1 != nerr2:
        print("[FAIL] binary behavior changed after round-trip")
        print(f"original rc={rc1}, rebuilt rc={rc2}")
        print("---- original stderr ----")
        print(nerr1)
        print("---- rebuilt stderr ----")
        print(nerr2)

        diff = "\n".join(difflib.unified_diff(
            src.splitlines(),
            rebuilt_src.splitlines(),
            fromfile="original",
            tofile="rebuilt",
            lineterm="",
        ))
        print("---- source diff ----")
        print(diff)
        raise SystemExit(1)

    if src != rebuilt_src:
        print("[FAIL] textual round-trip changed source, even though behavior matched")
        diff = "\n".join(difflib.unified_diff(
            src.splitlines(),
            rebuilt_src.splitlines(),
            fromfile="original",
            tofile="rebuilt",
            lineterm="",
        ))
        print(diff)
        raise SystemExit(1)

    print("[OK] round-trip preserved parseability and binary behavior")


if __name__ == "__main__":
    main()
