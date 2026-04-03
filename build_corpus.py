#!/usr/bin/env python3
import os
import sys
import argparse

HEADER_SIZE = 128

def make_fuzz_input(shader_src: bytes) -> bytes:
    header = b"\x00" * HEADER_SIZE
    return header + shader_src + b"\x00"

def strip_comments(data: bytes) -> str:
    lines = data.decode("utf-8", errors="ignore").splitlines()

    out = []
    for line in lines:
        line = line.strip()

        # skip full-line comments
        if line.startswith("//"):
            continue

        # remove inline comments
        if "//" in line:
            line = line.split("//", 1)[0].rstrip()

        if line:
            out.append(line)

    return "\n".join(out)

def process_file(in_path, out_path):
    try:
        with open(in_path, "rb") as f:
            data = f.read()

        if not data.strip():
            return

        cleaned = strip_comments(data)

        if not cleaned.strip():
            return

        out = make_fuzz_input(cleaned.encode("utf-8"))

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
