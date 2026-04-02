#!/usr/bin/env python3
import os
import sys
import argparse

HEADER_SIZE = 128

def make_fuzz_input(shader_src: bytes) -> bytes:
    header = b"\x00" * HEADER_SIZE
    return header + shader_src + b"\x00"

def process_file(in_path, out_path):
    try:
        with open(in_path, "rb") as f:
            data = f.read()

        # skip empty
        if not data.strip():
            return

        out = make_fuzz_input(data)

        with open(out_path, "wb") as f:
            f.write(out)

    except Exception as e:
        print(f"[!] Failed {in_path}: {e}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("output_dir")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    count = 0

    for root, _, files in os.walk(args.input_dir):
        for fn in files:
            if not fn.endswith((".hlsl", ".fx", ".fxh")):
                continue

            in_path = os.path.join(root, fn)
            out_path = os.path.join(args.output_dir, f"{count}.bin")

            process_file(in_path, out_path)
            count += 1

    print(f"[+] Generated {count} corpus files")

if __name__ == "__main__":
    main()
