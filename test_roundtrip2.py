#!/usr/bin/env python3
import subprocess
import sys
import os

HEADER_SIZE = 128

def strip(buf: bytes) -> bytes:
    return buf[HEADER_SIZE:].rstrip(b"\x00")

def run_dxc(bin_path, file_path):
    try:
        subprocess.check_output([bin_path, file_path], stderr=subprocess.STDOUT)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.output.decode(errors="ignore")

def run_one(dxc, path, data, fn):
    # 1. run original
    ok1, err1 = run_dxc(dxc, path)

    # 2. parse → unparse
    try:
        src = strip(data).decode("utf-8", errors="ignore")

        import hlsl_parser, hlsl_unparser

        tu = hlsl_parser.parse_to_tree(src)
        out = hlsl_unparser.unparse_tu(tu)

    except Exception as e:
        print(f"[PARSE FAIL] {fn}: {e}")
        return
    else:
        print(f"[PARSE SUCCESS] {fn}")
    # 3. rebuild input
    new_data = b"\x00"*HEADER_SIZE + out.encode() + b"\x00"

    tmp = "/tmp/test_shader.bin"
    with open(tmp, "wb") as f:
        f.write(new_data)

    # 4. run again
    ok2, err2 = run_dxc(dxc, tmp)

    if ok1 != ok2:
        print(f"[MISMATCH] {fn}")
        print("Before:", ok1)
        print("After :", ok2)
        print("----")
        print(err2)
        # break

def main():
    if len(sys.argv) != 3:
        print("usage: test_roundtrip.py <dxc_binary> <input_dir/input_file>")
        return

    dxc = sys.argv[1]
    indir = sys.argv[2]

    if os.path.isfile(indir): # Specified a file?
        with open(indir, "rb") as f:
            data = f.read()
        run_one(dxc, indir, data, indir)
    else:
        for fn in os.listdir(indir):
            path = os.path.join(indir, fn)

            with open(path, "rb") as f:
                data = f.read()

            run_one(dxc, path, data, fn)

    print("[+] Done")


if __name__ == "__main__":
    main()