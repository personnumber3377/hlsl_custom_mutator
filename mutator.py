#!/usr/bin/env python3
from __future__ import annotations

import random
import traceback
import sys

import hlsl_parser
import hlsl_mutator
import hlsl_unparser

from header_mutator import mutate_header_precise

HEADER_SIZE = 8 # 128
ENABLE_FALLBACK = False

_initialized = False


# -----------------------------
# Init
# -----------------------------

def init(seed: int):
    global _initialized
    if _initialized:
        return
    random.seed(seed)
    _initialized = True


def deinit():
    global _initialized
    _initialized = False


# -----------------------------
# Generic fallback
# -----------------------------

def mutate_bytes_generic(b: bytes, rng: random.Random) -> bytes:
    if not b:
        return bytes([rng.randrange(256)])

    op = rng.randrange(3)

    if op == 0 and len(b) > 1:
        a = rng.randrange(len(b) - 1)
        c = rng.randrange(a + 1, len(b))
        return b[:a] + b[c:]

    if op == 1:
        pos = rng.randrange(len(b))
        return b[:pos] + bytes([rng.randrange(256)]) + b[pos:]

    pos = rng.randrange(len(b))
    return b[:pos] + bytes([b[pos] ^ (1 << rng.randrange(8))]) + b[pos + 1:]

def mutate_bytes_generic_constant_length(b: bytes, rng: random.Random) -> bytes: # Constant length mutations for mutating the header and stuff...
    if not b:
        return b # bytes([rng.randrange(256)])
    orig_len = len(b)

    pos = rng.randrange(len(b))
    res = b[:pos] + bytes([b[pos] ^ (1 << rng.randrange(8))]) + b[pos + 1:]
    assert orig_len == len(res) # Should stay constant length...
    return res

# -----------------------------
# Structural mutation
# -----------------------------

def mutate_shader_structural(shader_bytes: bytes, max_size: int, rng: random.Random) -> bytearray:
    src = shader_bytes.decode("utf-8", errors="ignore")

    tu = hlsl_parser.parse_to_tree(src)
    mutated = hlsl_mutator.mutate_translation_unit(tu, rng)
    out_src = hlsl_unparser.unparse_tu(mutated)

    return bytearray(out_src.encode("utf-8")[:max_size])


# -----------------------------
# AFL entrypoint
# -----------------------------

def fuzz(buf: bytearray, add_buf, max_size: int) -> bytearray:
    if not _initialized:
        init(0)

    rng = random.Random(random.randrange(1 << 30))

    try:
        if len(buf) <= HEADER_SIZE:
            # raise AttributeError # Just do some bullshit here...
            return bytearray(mutate_bytes_generic_constant_length(bytes(buf), rng))

        header = bytes(buf[:HEADER_SIZE])
        body = bytes(buf[HEADER_SIZE:])

        # strip trailing null
        if body and body[-1] == 0:
            body = body[:-1]

        # mutate header (rarely)
        if rng.random() < 0.1:
            header = mutate_header_precise(header, rng)

        # structural mutation
        mutated_body = mutate_shader_structural(body, max_size - HEADER_SIZE, rng)

        out = bytearray()
        out.extend(header)
        out.extend(mutated_body)
        # out.append(0)

        return out[:max_size]

    except Exception:
        if not ENABLE_FALLBACK:
            raise

        mutated = mutate_bytes_generic(bytes(buf), rng)
        return bytearray(mutated[:max_size])


# -----------------------------
# libFuzzer hook
# -----------------------------

def custom_mutator(buf: bytearray, add_buf, max_size: int, callback=None) -> bytearray:
    try:
        return fuzz(buf, add_buf, max_size)

    except Exception as e:
        
        '''
        import traceback
        import time

        with open("/home/oof/mutator_log.txt", "a") as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"[TIME] {time.time()}\n")
            f.write(f"[EXCEPTION] {repr(e)}\n")
            f.write("[TRACEBACK]\n")
            f.write(traceback.format_exc())
            f.write("\n[INPUT]\n")
            f.write(repr(bytes(buf)))
            f.write("\n" + "="*80 + "\n")
        '''

        return buf  # keep corpus stable
