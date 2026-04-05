#!/usr/bin/env python3
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional

# --------------------------------------------------
# Config
# --------------------------------------------------

HEADER_SIZE = 8
MUTATE_HEADER_PROB = 0.03
MAX_BODY_SIZE = 1_000_000

_initialized = False

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


# --------------------------------------------------
# Init
# --------------------------------------------------

def init(seed: int):
    global _initialized
    if _initialized:
        return
    random.seed(seed)
    _initialized = True


def deinit():
    global _initialized
    _initialized = False


# --------------------------------------------------
# Blob helpers
# --------------------------------------------------

def split_blob(buf: bytes) -> Tuple[bytes, bytes]:
    if len(buf) >= HEADER_SIZE:
        return buf[:HEADER_SIZE], buf[HEADER_SIZE:].rstrip(b"\x00")
    return b"", buf.rstrip(b"\x00")


def join_blob(header: bytes, body: bytes, max_size: int) -> bytearray:
    out = bytearray()
    out.extend(header)
    out.extend(body)
    return out[:max_size]


def maybe_mutate_header(header: bytes, rng: random.Random) -> bytes:
    if header and rng.random() < MUTATE_HEADER_PROB:
        try:
            return mutate_header_precise(header, rng)
        except Exception:
            b = bytearray(header)
            if b:
                i = rng.randrange(len(b))
                b[i] ^= 1 << rng.randrange(8)
            return bytes(b)
    return header


# --------------------------------------------------
# Tokenizer
# --------------------------------------------------

TOKEN_RE = re.compile(
    r"""
    //.*?$ |
    /\*.*?\*/ |
    "(?:\\.|[^"\\])*" |
    '(?:\\.|[^'\\])*' |
    \b0x[0-9A-Fa-f]+[uUlL]*\b |
    \b[0-9]+(?:\.[0-9]*)?(?:[eE][+\-]?[0-9]+)?[fFlLuU]*\b |
    :: | -> |
    \+\+ | -- | <<= | >>= | \+= | -= | \*= | /= | %= | &= | \|= | \^= |
    == | != | <= | >= | && | \|\| | << | >> |
    [A-Za-z_][A-Za-z0-9_]* |
    [(){}\[\];,.:?~+\-*/%<>=!&|^#]
    """,
    re.VERBOSE | re.MULTILINE | re.DOTALL,
)

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

HLSL_BUILTIN_TYPES = {
    "void", "bool", "int", "uint", "dword", "half", "float", "double",
    "min16float", "min10float", "min16int", "min12int", "min16uint",
    "int1", "int2", "int3", "int4",
    "uint1", "uint2", "uint3", "uint4",
    "float1", "float2", "float3", "float4",
    "double1", "double2", "double3", "double4",
    "bool1", "bool2", "bool3", "bool4",
    "float1x1", "float1x2", "float1x3", "float1x4",
    "float2x1", "float2x2", "float2x3", "float2x4",
    "float3x1", "float3x2", "float3x3", "float3x4",
    "float4x1", "float4x2", "float4x3", "float4x4",
    "uint2x2", "uint3x3", "uint4x4",
    "matrix", "vector",
}

HLSL_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "discard",
    "struct", "class", "enum", "typedef", "namespace", "template",
    "cbuffer", "tbuffer", "register", "groupshared",
    "static", "const", "volatile", "row_major", "column_major",
    "in", "out", "inout", "uniform", "precise", "nointerpolation",
    "linear", "centroid", "sample",
    "true", "false",
}

HLSL_INTERESTING = [
    "Texture1D", "Texture2D", "Texture3D", "TextureCube",
    "Texture2DArray", "TextureCubeArray",
    "RWBuffer", "Buffer", "RWStructuredBuffer", "StructuredBuffer",
    "AppendStructuredBuffer", "ConsumeStructuredBuffer",
    "ByteAddressBuffer", "RWByteAddressBuffer",
    "SamplerState", "SamplerComparisonState",
    "RayQuery", "RayDesc", "RaytracingAccelerationStructure",
    "InputPatch", "OutputPatch", "LineStream", "TriangleStream",
    "DispatchMesh", "WaveGetLaneCount", "WaveGetLaneIndex",
    "GroupMemoryBarrierWithGroupSync", "InterlockedAdd",
    "SV_Target", "SV_Position", "SV_GroupThreadID", "SV_DispatchThreadID",
    "SV_GroupIndex", "SV_GroupID", "SV_Target0",
    "numthreads", "RootSignature", "shader", "domain", "partitioning",
    "outputtopology", "outputcontrolpoints", "patchconstantfunc",
]

PUNCT = [
    "{", "}", "(", ")", "[", "]", ";", ",", ".", ":", "::",
    "+", "-", "*", "/", "%", "=",
    "==", "!=", "<", ">", "<=", ">=",
    "&&", "||", "&", "|", "^", "<<", ">>",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
    "?", "~", "#",
]

LITERALS = [
    "0", "1", "2", "3", "4", "5",
    "0.0", "0.5", "1.0", "2.0", "-1.0",
    "true", "false",
    "\"\"", "\"x\"",
]


@dataclass
class Tok:
    text: str


def strip_comments(src: str) -> str:
    src = re.sub(r"//.*?$", "", src, flags=re.MULTILINE)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return src


def lex(src: str) -> List[Tok]:
    toks: List[Tok] = []
    for m in TOKEN_RE.finditer(src):
        text = m.group(0)
        if text.startswith("//") or text.startswith("/*"):
            continue
        toks.append(Tok(text))
    return toks


def untok(tokens: List[Tok]) -> str:
    if not tokens:
        return ""

    def identlike(s: str) -> bool:
        return bool(IDENT_RE.match(s)) or bool(re.match(r"^[0-9]", s))

    no_space_before = {")", "]", "}", ";", ",", ".", ":", "::"}
    no_space_after = {"(", "[", "{", ".", "::"}
    force_space = {
        "if", "for", "while", "switch", "return", "struct", "class", "enum",
        "cbuffer", "tbuffer", "in", "out", "inout", "groupshared", "static",
        "const", "row_major", "column_major"
    }

    out: List[str] = []
    prev = ""

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
        if cur == "(" and identlike(prev):
            need_space = False
        if prev == "." or cur == "." or prev == "::" or cur == "::":
            need_space = False
        if prev in force_space or cur in force_space:
            need_space = True

        if need_space:
            out.append(" ")
        out.append(cur)
        prev = cur

    s = "".join(out)

    s = s.replace("{", "{\n")
    s = s.replace("}", "\n}\n")
    s = s.replace(";", ";\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


# --------------------------------------------------
# Harvest names / types
# --------------------------------------------------

@dataclass
class TokenPools:
    idents: List[str]
    typeish: List[str]
    funcs: List[str]


def harvest_pools(tokens: List[Tok]) -> TokenPools:
    idents = set()
    typeish = set(HLSL_BUILTIN_TYPES)
    funcs = set()

    for i, t in enumerate(tokens):
        x = t.text
        if IDENT_RE.match(x):
            idents.add(x)

            if i + 1 < len(tokens) and tokens[i + 1].text == "(":
                funcs.add(x)

            if (
                x in HLSL_BUILTIN_TYPES
                or re.match(r"^(float|int|uint|bool|double|min16|min10|min12|half)", x)
                or x in HLSL_INTERESTING
            ):
                typeish.add(x)

    if not idents:
        idents.update(["x", "y", "z", "main", "foo", "tmp"])

    if not funcs:
        funcs.update(["main", "foo"])

    return TokenPools(
        idents=sorted(idents),
        typeish=sorted(typeish),
        funcs=sorted(funcs),
    )


# --------------------------------------------------
# Rough chunking
# --------------------------------------------------

def split_top_level(tokens: List[Tok]) -> List[List[Tok]]:
    chunks: List[List[Tok]] = []
    cur: List[Tok] = []

    bp = bb = bc = 0

    for t in tokens:
        cur.append(t)
        x = t.text

        if x == "(":
            bp += 1
        elif x == ")":
            bp = max(0, bp - 1)
        elif x == "[":
            bb += 1
        elif x == "]":
            bb = max(0, bb - 1)
        elif x == "{":
            bc += 1
        elif x == "}":
            bc = max(0, bc - 1)
            if bc == 0 and bp == 0 and bb == 0:
                chunks.append(cur)
                cur = []
                continue
        elif x == ";" and bc == 0 and bp == 0 and bb == 0:
            chunks.append(cur)
            cur = []

    if cur:
        chunks.append(cur)

    return [c for c in chunks if c]


def first_outer_block(tokens: List[Tok]) -> Optional[Tuple[int, int]]:
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


def split_statements(tokens: List[Tok]) -> List[List[Tok]]:
    out: List[List[Tok]] = []
    cur: List[Tok] = []
    bp = bb = bc = 0

    for t in tokens:
        cur.append(t)
        x = t.text

        if x == "(":
            bp += 1
        elif x == ")":
            bp = max(0, bp - 1)
        elif x == "[":
            bb += 1
        elif x == "]":
            bb = max(0, bb - 1)
        elif x == "{":
            bc += 1
        elif x == "}":
            bc = max(0, bc - 1)
            if bc == 0 and bp == 0 and bb == 0:
                out.append(cur)
                cur = []
        elif x == ";" and bc == 0 and bp == 0 and bb == 0:
            out.append(cur)
            cur = []

    if cur:
        out.append(cur)

    return [x for x in out if x]


# --------------------------------------------------
# Token generation / mutation
# --------------------------------------------------

def rand_ident(rng: random.Random, pools: TokenPools) -> str:
    if rng.random() < 0.8 and pools.idents:
        return rng.choice(pools.idents)
    return rng.choice(["x", "tmp", "buf", "tex", "main", "foo", "i", "j"])


def rand_type(rng: random.Random, pools: TokenPools) -> str:
    if rng.random() < 0.85 and pools.typeish:
        return rng.choice(pools.typeish)
    return rng.choice(["float", "float2", "float4", "int", "uint", "bool"])


def rand_literal(rng: random.Random) -> str:
    return rng.choice(LITERALS)


def rand_token(rng: random.Random, pools: TokenPools) -> Tok:
    x = rng.random()
    if x < 0.20:
        return Tok(rand_type(rng, pools))
    if x < 0.45:
        return Tok(rand_ident(rng, pools))
    if x < 0.65:
        return Tok(rand_literal(rng))
    if x < 0.90:
        return Tok(rng.choice(PUNCT))
    return Tok(rng.choice(HLSL_INTERESTING))


def replace_with_similar(tok: Tok, rng: random.Random, pools: TokenPools) -> Tok:
    x = tok.text

    if x in HLSL_BUILTIN_TYPES or x in HLSL_INTERESTING:
        return Tok(rand_type(rng, pools))

    if x in HLSL_KEYWORDS:
        return Tok(rng.choice(list(HLSL_KEYWORDS)))

    if IDENT_RE.match(x):
        return Tok(rand_ident(rng, pools))

    if re.match(r"^[0-9]", x):
        return Tok(rand_literal(rng))

    return Tok(rng.choice(PUNCT))


def balanced_wrap(segment: List[Tok], rng: random.Random) -> List[Tok]:
    choice = rng.randrange(5)
    if choice == 0:
        return [Tok("(")] + segment + [Tok(")")]
    if choice == 1:
        return [Tok("{")] + segment + [Tok("}")]
    if choice == 2:
        return [Tok("[")] + segment + [Tok("]")]
    if choice == 3:
        return [Tok("("), Tok(rand_type(rng, harvest_pools(segment))) , Tok(")")] + segment
    return [Tok(rand_ident(rng, harvest_pools(segment))), Tok("(")] + segment + [Tok(")")]


def mutate_tokens_aggressive(tokens: List[Tok], rng: random.Random, pools: TokenPools) -> List[Tok]:
    toks = list(tokens)
    if not toks:
        return toks

    n_ops = 1 + rng.randrange(12)

    for _ in range(n_ops):
        op = rng.randrange(12)

        if op == 0 and toks:
            i = rng.randrange(len(toks))
            toks[i] = replace_with_similar(toks[i], rng, pools)

        elif op == 1:
            i = rng.randrange(len(toks) + 1)
            toks[i:i] = [rand_token(rng, pools)]

        elif op == 2 and len(toks) > 1:
            i = rng.randrange(len(toks))
            del toks[i]

        elif op == 3 and len(toks) > 1:
            a = rng.randrange(len(toks))
            b = min(len(toks), a + 1 + rng.randrange(min(8, len(toks) - a)))
            ins = rng.randrange(len(toks) + 1)
            toks[ins:ins] = toks[a:b]

        elif op == 4 and len(toks) > 4:
            a1 = rng.randrange(len(toks) - 1)
            b1 = min(len(toks), a1 + 1 + rng.randrange(min(6, len(toks) - a1)))
            a2 = rng.randrange(len(toks) - 1)
            b2 = min(len(toks), a2 + 1 + rng.randrange(min(6, len(toks) - a2)))
            seg1 = toks[a1:b1]
            seg2 = toks[a2:b2]
            if a1 < a2:
                toks = toks[:a1] + seg2 + toks[b1:a2] + seg1 + toks[b2:]
            else:
                toks = toks[:a2] + seg1 + toks[b2:a1] + seg2 + toks[b1:]

        elif op == 5 and len(toks) > 0:
            i = rng.randrange(len(toks))
            toks[i:i+1] = balanced_wrap([toks[i]], rng)

        elif op == 6 and len(toks) > 2:
            a = rng.randrange(len(toks) - 1)
            b = min(len(toks), a + 1 + rng.randrange(min(10, len(toks) - a)))
            toks[a:b] = balanced_wrap(toks[a:b], rng)

        elif op == 7:
            i = rng.randrange(len(toks) + 1)
            inject = [
                Tok(rand_type(rng, pools)),
                Tok(rand_ident(rng, pools)),
                Tok("="),
                Tok(rand_literal(rng)),
                Tok(";"),
            ]
            toks[i:i] = inject

        elif op == 8:
            i = rng.randrange(len(toks) + 1)
            inject = [
                Tok("if"), Tok("("), Tok("true"), Tok(")"),
                Tok("{"),
                Tok(rand_ident(rng, pools)), Tok("="), Tok(rand_literal(rng)), Tok(";"),
                Tok("}"),
            ]
            toks[i:i] = inject

        elif op == 9:
            i = rng.randrange(len(toks) + 1)
            inject = [
                Tok(rand_ident(rng, pools)), Tok("("), Tok(rand_literal(rng)), Tok(")"), Tok(";")
            ]
            toks[i:i] = inject

        elif op == 10:
            i = rng.randrange(len(toks) + 1)
            inject = [
                Tok("["), Tok("numthreads"), Tok("("), Tok("1"), Tok(","), Tok("1"), Tok(","), Tok("1"), Tok(")"), Tok("]")
            ]
            toks[i:i] = inject

        elif op == 11 and len(toks) > 0:
            id_positions = [i for i, t in enumerate(toks) if IDENT_RE.match(t.text)]
            if id_positions:
                i = rng.choice(id_positions)
                toks[i] = Tok(rand_ident(rng, pools))

    return toks


def mutate_by_structure(tokens: List[Tok], rng: random.Random) -> List[Tok]:
    pools = harvest_pools(tokens)

    mode = rng.randrange(4)

    if mode == 0:
        return mutate_tokens_aggressive(tokens, rng, pools)

    if mode == 1:
        chunks = split_top_level(tokens)
        if not chunks:
            return mutate_tokens_aggressive(tokens, rng, pools)

        i = rng.randrange(len(chunks))
        chunks[i] = mutate_tokens_aggressive(chunks[i], rng, pools)

        if len(chunks) > 1 and rng.random() < 0.35:
            j = rng.randrange(len(chunks))
            chunks.insert(rng.randrange(len(chunks) + 1), list(chunks[j]))

        out: List[Tok] = []
        for c in chunks:
            out.extend(c)
        return out

    if mode == 2:
        span = first_outer_block(tokens)
        if span is None:
            return mutate_tokens_aggressive(tokens, rng, pools)

        l, r = span
        prefix = tokens[:l+1]
        body = tokens[l+1:r]
        suffix = tokens[r:]

        stmts = split_statements(body)
        if not stmts:
            return mutate_tokens_aggressive(tokens, rng, pools)

        i = rng.randrange(len(stmts))
        stmts[i] = mutate_tokens_aggressive(stmts[i], rng, pools)

        if len(stmts) > 1 and rng.random() < 0.5:
            j = rng.randrange(len(stmts))
            stmts.insert(rng.randrange(len(stmts) + 1), list(stmts[j]))

        out = list(prefix)
        for s in stmts:
            out.extend(s)
        out.extend(suffix)
        return out

    # mixed mode
    tmp = mutate_tokens_aggressive(tokens, rng, pools)
    return mutate_by_structure(tmp, rng) if rng.random() < 0.4 else tmp


# --------------------------------------------------
# Main mutation
# --------------------------------------------------

def mutate_source(src: str, rng: random.Random) -> str:
    src = strip_comments(src)
    toks = lex(src)

    if not toks:
        toks = [
            Tok("void"), Tok("main"), Tok("("), Tok(")"),
            Tok("{"), Tok("}"),
        ]

    out = mutate_by_structure(toks, rng)
    return untok(out)


# --------------------------------------------------
# Crossover
# --------------------------------------------------

def splice_token_streams(a: List[Tok], b: List[Tok], rng: random.Random) -> List[Tok]:
    if not a:
        return list(b)
    if not b:
        return list(a)

    a1 = rng.randrange(len(a) + 1)
    a2 = rng.randrange(a1, len(a) + 1)
    b1 = rng.randrange(len(b) + 1)
    b2 = rng.randrange(b1, len(b) + 1)

    return a[:a1] + b[b1:b2] + a[a2:]


def crossover_source(src1: str, src2: str, rng: random.Random) -> str:
    t1 = lex(strip_comments(src1))
    t2 = lex(strip_comments(src2))

    if not t1:
        t1 = [Tok("void"), Tok("main"), Tok("("), Tok(")"), Tok("{"), Tok("}")]
    if not t2:
        t2 = [Tok("void"), Tok("main"), Tok("("), Tok(")"), Tok("{"), Tok("}")]

    mode = rng.randrange(4)

    if mode == 0:
        out = splice_token_streams(t1, t2, rng)
        return untok(out)

    if mode == 1:
        c1 = split_top_level(t1)
        c2 = split_top_level(t2)
        if not c1 or not c2:
            return untok(splice_token_streams(t1, t2, rng))

        out_chunks = list(c1)
        take = 1 + rng.randrange(min(4, len(c2)))
        for idx in rng.sample(range(len(c2)), k=take):
            out_chunks.insert(rng.randrange(len(out_chunks) + 1), list(c2[idx]))

        if len(out_chunks) > 1 and rng.random() < 0.3:
            del out_chunks[rng.randrange(len(out_chunks))]

        out: List[Tok] = []
        for c in out_chunks:
            out.extend(c)
        return untok(out)

    if mode == 2:
        s1 = first_outer_block(t1)
        s2 = first_outer_block(t2)
        if s1 is None or s2 is None:
            return untok(splice_token_streams(t1, t2, rng))

        l1, r1 = s1
        l2, r2 = s2

        prefix = t1[:l1+1]
        suffix = t1[r1:]

        stmts1 = split_statements(t1[l1+1:r1])
        stmts2 = split_statements(t2[l2+1:r2])

        if not stmts1 or not stmts2:
            return untok(splice_token_streams(t1, t2, rng))

        out_stmts = list(stmts1)
        take = 1 + rng.randrange(min(8, len(stmts2)))
        for idx in rng.sample(range(len(stmts2)), k=take):
            out_stmts.insert(rng.randrange(len(out_stmts) + 1), list(stmts2[idx]))

        out = list(prefix)
        for s in out_stmts:
            out.extend(s)
        out.extend(suffix)
        return untok(out)

    # crossover + mutate
    out = splice_token_streams(t1, t2, rng)
    out = mutate_by_structure(out, rng)
    return untok(out)


# --------------------------------------------------
# AFL/libFuzzer entrypoints
# --------------------------------------------------

def fuzz(buf: bytearray, add_buf, max_size: int) -> bytearray:
    if not _initialized:
        init(0)

    rng = random.Random(random.randrange(1 << 30))

    header, body = split_blob(bytes(buf))
    header = maybe_mutate_header(header, rng)

    try:
        src = body.decode("utf-8", errors="ignore")
    except Exception:
        src = ""

    if not src.strip():
        src = "void main() {\n}\n"

    out_src = mutate_source(src, rng)
    out_body = out_src.encode("utf-8", errors="ignore")[:max(0, max_size - len(header))]
    return join_blob(header, out_body, max_size)


def custom_mutator(buf: bytearray, add_buf, max_size: int, callback=None) -> bytearray:
    try:
        return fuzz(buf, add_buf, max_size)
    except Exception:
        return bytearray(bytes(buf)[:max_size])


def custom_crossover(data1: bytearray, data2: bytearray, max_size: int, seed: int) -> bytearray:
    rng = random.Random(seed)

    try:
        h1, b1 = split_blob(bytes(data1))
        h2, b2 = split_blob(bytes(data2))

        header = h1 if rng.random() < 0.7 else h2
        header = maybe_mutate_header(header, rng)

        src1 = b1.decode("utf-8", errors="ignore")
        src2 = b2.decode("utf-8", errors="ignore")

        if not src1.strip():
            src1 = "void main() {\n}\n"
        if not src2.strip():
            src2 = "void main() {\n}\n"

        out_src = crossover_source(src1, src2, rng)
        out_body = out_src.encode("utf-8", errors="ignore")[:max(0, max_size - len(header))]
        return join_blob(header, out_body, max_size)

    except Exception:
        return bytearray(bytes(data1)[:max_size])


# --------------------------------------------------
# CLI helper
# --------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: mutator.py file1 [file2]")
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

    h, b = split_blob(bytes(out))
    print("=== HEADER ===")
    print(h)
    print("=== BODY ===")
    print(b.decode("utf-8", errors="ignore"))