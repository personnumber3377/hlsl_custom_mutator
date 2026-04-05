#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional

# ----------------------------------------
# Config
# ----------------------------------------

HEADER_SIZE = 8
MUTATE_HEADER_PROB = 0.10
MAX_TOPLEVEL_SPLICE = 3
MAX_STATEMENT_SPLICE = 8

_initialized = False

# Optional: use your precise header mutator if available
try:
    from header_mutator import mutate_header_precise
except Exception:
    def mutate_header_precise(h: bytes, rng: random.Random) -> bytes:
        if not h:
            return h
        b = bytearray(h)
        pos = rng.randrange(len(b))
        b[pos] ^= 1 << rng.randrange(8)
        return bytes(b)

# ----------------------------------------
# Helpers
# ----------------------------------------

def init(seed: int):
    global _initialized
    if _initialized:
        return
    random.seed(seed)
    _initialized = True

def deinit():
    global _initialized
    _initialized = False

def strip_blob(buf: bytes) -> Tuple[bytes, bytes]:
    """
    Split into header/body.
    If buffer doesn't look like a fuzz blob, treat entire thing as source.
    """
    if len(buf) >= HEADER_SIZE:
        header = buf[:HEADER_SIZE]
        body = buf[HEADER_SIZE:]
        return header, body.rstrip(b"\x00")
    return b"", buf.rstrip(b"\x00")

def pack_blob(header: bytes, body: bytes, max_size: int) -> bytearray:
    out = bytearray()
    out.extend(header)
    out.extend(body)
    return out[:max_size]

def mutate_bytes_constant_length(b: bytes, rng: random.Random) -> bytes:
    if not b:
        return b
    x = bytearray(b)
    pos = rng.randrange(len(x))
    x[pos] ^= 1 << rng.randrange(8)
    return bytes(x)

def maybe_mutate_header(header: bytes, rng: random.Random) -> bytes:
    if not header:
        return header
    if rng.random() < MUTATE_HEADER_PROB:
        try:
            return mutate_header_precise(header, rng)
        except Exception:
            return mutate_bytes_constant_length(header, rng)
    return header

# ----------------------------------------
# Tokenization
# ----------------------------------------

_TOKEN_RE = re.compile(
    r"""
    //.*?$                              | # line comment
    /\*.*?\*/                           | # block comment
    "(?:\\.|[^"\\])*"                   | # string
    '(?:\\.|[^'\\])*'                   | # char
    \b[0-9]+(?:\.[0-9]*)?(?:[eE][+\-]?[0-9]+)?[fFuUlL]*\b | # number
    \b[A-Za-z_][A-Za-z0-9_]*\b          | # identifier / keyword
    ::|->|\+\+|--|<<=|>>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|==|!=|<=|>=|&&|\|\||<<|>> |
    [(){}\[\];,.:?~+\-*/%<>=!&|^#]        # punctuation/operators
    """,
    re.VERBOSE | re.MULTILINE | re.DOTALL,
)

@dataclass
class Tok:
    text: str

def remove_comments(src: str) -> str:
    src = re.sub(r"//.*?$", "", src, flags=re.MULTILINE)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return src

def lex(src: str) -> List[Tok]:
    toks: List[Tok] = []
    for m in _TOKEN_RE.finditer(src):
        text = m.group(0)
        # skip comments entirely
        if text.startswith("//") or text.startswith("/*"):
            continue
        toks.append(Tok(text))
    return toks

def untok(tokens: List[Tok]) -> str:
    """
    Reconstruct approximately-valid HLSL text from tokens.
    Spacing is heuristic, not perfect.
    """
    if not tokens:
        return ""

    out: List[str] = []
    prev = ""

    def is_identlike(s: str) -> bool:
        return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s)) or bool(re.match(r"^[0-9]", s))

    no_space_before = {")", "]", "}", ";", ",", ".", ":", "::"}
    no_space_after = {"(", "[", "{", ".", "::", "#"}
    binaryish = {
        "+", "-", "*", "/", "%", "=", "+=", "-=", "*=", "/=", "%=",
        "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^",
        "<<", ">>", "&=", "|=", "^=", "<<=", ">>=", "?", ":"
    }

    for t in tokens:
        cur = t.text

        if not out:
            out.append(cur)
            prev = cur
            continue

        need_space = True

        if cur in no_space_before:
            need_space = False
        if prev in no_space_after:
            need_space = False
        if cur == "(" and is_identlike(prev):
            need_space = False
        if prev == ")" and cur == "{":
            need_space = True
        if prev in binaryish or cur in binaryish:
            need_space = True
        if prev == "#" or cur == "#":
            need_space = True
        if prev == ":" and cur == ":":
            need_space = False
        if prev == "." or cur == ".":
            need_space = False
        if prev == "::" or cur == "::":
            need_space = False

        if need_space:
            out.append(" ")
        out.append(cur)
        prev = cur

    s = "".join(out)

    # pretty-ish formatting
    s = s.replace("{", "{\n")
    s = s.replace(";", ";\n")
    s = s.replace("}", "\n}\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"

# ----------------------------------------
# Rough structural splitting
# ----------------------------------------

def split_top_level(tokens: List[Tok]) -> List[List[Tok]]:
    """
    Split top-level chunks roughly by brace depth and ';'
    Good enough for:
      - global decls
      - function defs
      - struct/class/enum declarations
      - attributes attached before decls
    """
    chunks: List[List[Tok]] = []
    cur: List[Tok] = []
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0

    for t in tokens:
        cur.append(t)
        x = t.text

        if x == "(":
            depth_paren += 1
        elif x == ")":
            depth_paren = max(0, depth_paren - 1)
        elif x == "[":
            depth_brack += 1
        elif x == "]":
            depth_brack = max(0, depth_brack - 1)
        elif x == "{":
            depth_brace += 1
        elif x == "}":
            depth_brace = max(0, depth_brace - 1)
            if depth_brace == 0 and depth_paren == 0 and depth_brack == 0:
                chunks.append(cur)
                cur = []
                continue
        elif x == ";" and depth_brace == 0 and depth_paren == 0 and depth_brack == 0:
            chunks.append(cur)
            cur = []

    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]

def find_first_outer_block(tokens: List[Tok]) -> Optional[Tuple[int, int]]:
    """
    Return span [l, r] inclusive of first outermost {...}
    """
    depth = 0
    start = None
    for i, t in enumerate(tokens):
        if t.text == "{":
            if depth == 0:
                start = i
            depth += 1
        elif t.text == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return start, i
    return None

def split_block_statements(block_tokens: List[Tok]) -> List[List[Tok]]:
    """
    Input should be tokens *inside* a block, not including outer braces.
    Split by ';' and by nested brace blocks at depth 0.
    """
    out: List[List[Tok]] = []
    cur: List[Tok] = []
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0

    for t in block_tokens:
        cur.append(t)
        x = t.text

        if x == "(":
            depth_paren += 1
        elif x == ")":
            depth_paren = max(0, depth_paren - 1)
        elif x == "[":
            depth_brack += 1
        elif x == "]":
            depth_brack = max(0, depth_brack - 1)
        elif x == "{":
            depth_brace += 1
        elif x == "}":
            depth_brace = max(0, depth_brace - 1)
            if depth_brace == 0 and depth_paren == 0 and depth_brack == 0:
                out.append(cur)
                cur = []
        elif x == ";" and depth_brace == 0 and depth_paren == 0 and depth_brack == 0:
            out.append(cur)
            cur = []

    if cur:
        out.append(cur)
    return [x for x in out if x]

# ----------------------------------------
# Mutation primitives
# ----------------------------------------

HLSL_KEYWORD_POOL = [
    "float", "float2", "float3", "float4",
    "int", "int2", "int3", "int4",
    "uint", "uint2", "uint3", "uint4",
    "bool", "true", "false",
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue",
    "struct", "cbuffer", "tbuffer",
    "Texture2D", "Texture1D", "RWBuffer", "RWStructuredBuffer",
    "SamplerState", "groupshared", "static", "const", "in", "out", "inout",
    "numthreads", "register",
]

PUNCT_POOL = [
    "{", "}", "(", ")", "[", "]", ";", ",", ".", ":", "::",
    "+", "-", "*", "/", "%", "=",
    "==", "!=", "<", ">", "<=", ">=",
    "&&", "||", "&", "|", "^", "<<", ">>",
    "+=", "-=", "*=", "/=", "%=",
]

LITERAL_POOL = [
    "0", "1", "2", "3", "4",
    "0.0", "0.5", "1.0", "2.0", "-1.0",
    "\"\"", "\"foo\"", "'a'",
]

def random_token(rng: random.Random) -> Tok:
    roll = rng.random()
    if roll < 0.45:
        return Tok(rng.choice(HLSL_KEYWORD_POOL))
    if roll < 0.80:
        return Tok(rng.choice(PUNCT_POOL))
    return Tok(rng.choice(LITERAL_POOL))

def mutate_tokens_locally(tokens: List[Tok], rng: random.Random, max_edits: int = 8) -> List[Tok]:
    toks = list(tokens)
    if not toks:
        return toks

    edits = 1 + rng.randrange(max_edits)

    for _ in range(edits):
        op = rng.randrange(7)

        # replace token
        if op == 0 and toks:
            i = rng.randrange(len(toks))
            toks[i] = random_token(rng)

        # insert token
        elif op == 1:
            i = rng.randrange(len(toks) + 1)
            toks[i:i] = [random_token(rng)]

        # delete token
        elif op == 2 and len(toks) > 1:
            i = rng.randrange(len(toks))
            del toks[i]

        # duplicate token run
        elif op == 3 and len(toks) > 1:
            a = rng.randrange(len(toks))
            b = min(len(toks), a + 1 + rng.randrange(min(6, len(toks) - a)))
            ins = rng.randrange(len(toks) + 1)
            toks[ins:ins] = toks[a:b]

        # swap token runs
        elif op == 4 and len(toks) > 4:
            a1 = rng.randrange(len(toks) - 1)
            b1 = min(len(toks), a1 + 1 + rng.randrange(min(5, len(toks) - a1)))
            a2 = rng.randrange(len(toks) - 1)
            b2 = min(len(toks), a2 + 1 + rng.randrange(min(5, len(toks) - a2)))
            seg1 = toks[a1:b1]
            seg2 = toks[a2:b2]
            if a1 < a2:
                toks = toks[:a1] + seg2 + toks[b1:a2] + seg1 + toks[b2:]
            else:
                toks = toks[:a2] + seg1 + toks[b2:a1] + seg2 + toks[b1:]

        # mutate identifier-ish token into another identifier/keyword
        elif op == 5 and toks:
            id_positions = [i for i, t in enumerate(toks) if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t.text)]
            if id_positions:
                i = rng.choice(id_positions)
                toks[i] = Tok(rng.choice(HLSL_KEYWORD_POOL))

        # duplicate punctuation around something
        elif op == 6 and toks:
            i = rng.randrange(len(toks))
            wrapper = rng.choice([
                [Tok("("), toks[i], Tok(")")],
                [Tok("{"), toks[i], Tok("}")],
                [Tok("["), toks[i], Tok("]")],
            ])
            toks[i:i+1] = wrapper

    return toks

def mutate_top_level_chunks(tokens: List[Tok], rng: random.Random) -> List[Tok]:
    chunks = split_top_level(tokens)
    if not chunks:
        return mutate_tokens_locally(tokens, rng)

    op = rng.randrange(5)

    # mutate one chunk internally
    if op == 0:
        i = rng.randrange(len(chunks))
        chunks[i] = mutate_tokens_locally(chunks[i], rng, max_edits=6)

    # duplicate one chunk
    elif op == 1:
        i = rng.randrange(len(chunks))
        ins = rng.randrange(len(chunks) + 1)
        chunks.insert(ins, list(chunks[i]))

    # delete one chunk
    elif op == 2 and len(chunks) > 1:
        i = rng.randrange(len(chunks))
        del chunks[i]

    # swap chunks
    elif op == 3 and len(chunks) > 1:
        a = rng.randrange(len(chunks))
        b = rng.randrange(len(chunks))
        chunks[a], chunks[b] = chunks[b], chunks[a]

    # splice multiple chunks together
    elif op == 4 and len(chunks) > 1:
        a = rng.randrange(len(chunks))
        b = rng.randrange(len(chunks))
        merged = chunks[a] + chunks[b]
        chunks[a] = mutate_tokens_locally(merged, rng, max_edits=4)
        if a != b and b < len(chunks):
            del chunks[b]

    out: List[Tok] = []
    for c in chunks:
        out.extend(c)
    return out

def mutate_inside_block(tokens: List[Tok], rng: random.Random) -> List[Tok]:
    span = find_first_outer_block(tokens)
    if span is None:
        return mutate_top_level_chunks(tokens, rng)

    l, r = span
    prefix = tokens[:l+1]
    body = tokens[l+1:r]
    suffix = tokens[r:]

    stmts = split_block_statements(body)
    if not stmts:
        return mutate_top_level_chunks(tokens, rng)

    op = rng.randrange(5)

    # mutate one statement
    if op == 0:
        i = rng.randrange(len(stmts))
        stmts[i] = mutate_tokens_locally(stmts[i], rng, max_edits=6)

    # duplicate one statement
    elif op == 1:
        i = rng.randrange(len(stmts))
        ins = rng.randrange(len(stmts) + 1)
        stmts.insert(ins, list(stmts[i]))

    # delete one statement
    elif op == 2 and len(stmts) > 1:
        i = rng.randrange(len(stmts))
        del stmts[i]

    # swap statements
    elif op == 3 and len(stmts) > 1:
        a = rng.randrange(len(stmts))
        b = rng.randrange(len(stmts))
        stmts[a], stmts[b] = stmts[b], stmts[a]

    # merge/splice statements
    elif op == 4 and len(stmts) > 1:
        a = rng.randrange(len(stmts))
        b = rng.randrange(len(stmts))
        merged = stmts[a] + stmts[b]
        stmts[a] = mutate_tokens_locally(merged, rng, max_edits=4)
        if a != b and b < len(stmts):
            del stmts[b]

    out = list(prefix)
    for s in stmts:
        out.extend(s)
    out.extend(suffix)
    return out

def token_based_mutate_source(src: str, rng: random.Random) -> str:
    src = remove_comments(src)
    toks = lex(src)

    if not toks:
        toks = [Tok("void"), Tok("main"), Tok("("), Tok(")"), Tok("{"), Tok("}")]

    op = rng.randrange(4)

    if op == 0:
        out = mutate_tokens_locally(toks, rng, max_edits=8)
    elif op == 1:
        out = mutate_top_level_chunks(toks, rng)
    elif op == 2:
        out = mutate_inside_block(toks, rng)
    else:
        out = mutate_inside_block(mutate_top_level_chunks(toks, rng), rng)

    return untok(out)

# ----------------------------------------
# Crossover helpers
# ----------------------------------------

def splice_token_streams(a: List[Tok], b: List[Tok], rng: random.Random) -> List[Tok]:
    if not a:
        return list(b)
    if not b:
        return list(a)

    cut_a1 = rng.randrange(len(a) + 1)
    cut_a2 = rng.randrange(cut_a1, len(a) + 1)
    cut_b1 = rng.randrange(len(b) + 1)
    cut_b2 = rng.randrange(cut_b1, len(b) + 1)

    return a[:cut_a1] + b[cut_b1:cut_b2] + a[cut_a2:]

def crossover_top_level(src1: str, src2: str, rng: random.Random) -> str:
    t1 = lex(remove_comments(src1))
    t2 = lex(remove_comments(src2))

    c1 = split_top_level(t1)
    c2 = split_top_level(t2)

    if not c1 or not c2:
        return untok(splice_token_streams(t1, t2, rng))

    out = list(c1)

    take = 1 + rng.randrange(min(MAX_TOPLEVEL_SPLICE, len(c2)))
    picks = rng.sample(range(len(c2)), k=take)

    for idx in picks:
        ins = rng.randrange(len(out) + 1)
        out.insert(ins, list(c2[idx]))

    # optionally delete one old chunk
    if len(out) > 1 and rng.random() < 0.35:
        del out[rng.randrange(len(out))]

    flat: List[Tok] = []
    for c in out:
        flat.extend(c)

    return untok(flat)

def crossover_block_level(src1: str, src2: str, rng: random.Random) -> str:
    t1 = lex(remove_comments(src1))
    t2 = lex(remove_comments(src2))

    s1 = find_first_outer_block(t1)
    s2 = find_first_outer_block(t2)
    if s1 is None or s2 is None:
        return untok(splice_token_streams(t1, t2, rng))

    l1, r1 = s1
    l2, r2 = s2

    prefix = t1[:l1+1]
    suffix = t1[r1:]

    stmts1 = split_block_statements(t1[l1+1:r1])
    stmts2 = split_block_statements(t2[l2+1:r2])

    if not stmts1 or not stmts2:
        return untok(splice_token_streams(t1, t2, rng))

    out = list(stmts1)

    take = 1 + rng.randrange(min(MAX_STATEMENT_SPLICE, len(stmts2)))
    picks = rng.sample(range(len(stmts2)), k=take)

    for idx in picks:
        ins = rng.randrange(len(out) + 1)
        out.insert(ins, list(stmts2[idx]))

    if len(out) > 1 and rng.random() < 0.3:
        del out[rng.randrange(len(out))]

    flat = list(prefix)
    for s in out:
        flat.extend(s)
    flat.extend(suffix)
    return untok(flat)

# ----------------------------------------
# Main fuzz entrypoint
# ----------------------------------------

def fuzz(buf: bytearray, add_buf, max_size: int) -> bytearray:
    if not _initialized:
        init(0)

    rng = random.Random(random.randrange(1 << 30))

    if not isinstance(buf, (bytes, bytearray)):
        return bytearray(buf)

    header, body = strip_blob(bytes(buf))
    header = maybe_mutate_header(header, rng)

    try:
        src = body.decode("utf-8", errors="ignore")
    except Exception:
        src = ""

    if not src.strip():
        src = "void main() {\n}\n"

    mutated_src = token_based_mutate_source(src, rng)
    out_body = mutated_src.encode("utf-8", errors="ignore")

    return pack_blob(header, out_body, max_size)

# ----------------------------------------
# libFuzzer custom mutator hook
# ----------------------------------------

def custom_mutator(buf: bytearray, add_buf, max_size: int, callback=None) -> bytearray:
    try:
        return fuzz(buf, add_buf, max_size)
    except Exception:
        return bytearray(buf[:max_size])

# ----------------------------------------
# libFuzzer custom crossover hook
# ----------------------------------------

def custom_crossover(data1: bytearray, data2: bytearray, max_size: int, seed: int) -> bytearray:
    rng = random.Random(seed)

    try:
        h1, b1 = strip_blob(bytes(data1))
        h2, b2 = strip_blob(bytes(data2))

        # Keep header mostly from parent1, sometimes from parent2, sometimes mutate
        header = h1 if rng.random() < 0.7 else h2
        header = maybe_mutate_header(header, rng)

        src1 = b1.decode("utf-8", errors="ignore")
        src2 = b2.decode("utf-8", errors="ignore")

        if not src1.strip():
            src1 = "void main() {\n}\n"
        if not src2.strip():
            src2 = "void main() {\n}\n"

        mode = rng.randrange(3)
        if mode == 0:
            out_src = crossover_top_level(src1, src2, rng)
        elif mode == 1:
            out_src = crossover_block_level(src1, src2, rng)
        else:
            t1 = lex(remove_comments(src1))
            t2 = lex(remove_comments(src2))
            out_src = untok(splice_token_streams(t1, t2, rng))

        out_body = out_src.encode("utf-8", errors="ignore")
        return pack_blob(header, out_body, max_size)

    except Exception:
        return bytearray(bytes(data1)[:max_size])

# ----------------------------------------
# Simple CLI test helper
# ----------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: mutator.py input-file [input-file-2]")
        raise SystemExit(1)

    with open(sys.argv[1], "rb") as f:
        d1 = bytearray(f.read())

    init(1234)

    if len(sys.argv) == 2:
        out = custom_mutator(d1, None, 1_000_000)
    else:
        with open(sys.argv[2], "rb") as f:
            d2 = bytearray(f.read())
        out = custom_crossover(d1, d2, 1_000_000, 1337)

    hdr, body = strip_blob(bytes(out))
    print("=== HEADER ===")
    print(hdr)
    print("=== BODY ===")
    try:
        print(body.decode("utf-8", errors="ignore"))
    except Exception:
        print(body)

