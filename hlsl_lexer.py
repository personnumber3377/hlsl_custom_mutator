from __future__ import annotations
from dataclasses import dataclass
from typing import List
import re


KEYWORDS = {
    "if", "else", "for", "while", "do", "return", "break", "continue", "discard",
    "struct", "true", "false",
    "static", "const", "in", "out", "inout", "uniform", "precise",
    "row_major", "column_major",
    "void", "bool", "int", "uint", "float", "half", "double",
    "min16float", "min16int", "min16uint",
    "Texture2D", "TextureCube", "RWTexture2D", "SamplerState", "cbuffer",
}

# This is hack around all the weird "types" in HLSL which are actually constructors, but are syntactically identical to types. Yuck!!!
TYPELIKE_KEYWORDS = {
    "void", "bool", "int", "uint", "float", "half", "double",
    "min16float", "min16int", "min16uint",
    "Texture2D", "TextureCube", "RWTexture2D", "SamplerState",
    "float2", "float3", "float4",
    "int2", "int3", "int4",
    "uint2", "uint3", "uint4",
    "bool2", "bool3", "bool4",
    "float2x2", "float3x3", "float4x4",
    "matrix",
    "cbuffer", "tbuffer", # All kinds of buffers...
}

QUALIFIERS = {
    "static", "const", "in", "out", "inout", "uniform",
    "precise", "row_major", "column_major",
}

OPERATORS = [
    ">>=", "<<=", "++", "--", "==", "!=", "<=", ">=", "&&", "||",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>",
    "->", "::",
    "+", "-", "*", "/", "%", "=", "<", ">", "!", "~", "&", "|", "^", "?", ":", ".",
]

PUNCT = ["{", "}", "(", ")", "[", "]", ";", ","]

_OP_RE = "|".join(re.escape(x) for x in sorted(OPERATORS, key=len, reverse=True))
_PUNCT_RE = "|".join(re.escape(x) for x in PUNCT)

TOKEN_RE = re.compile(
    rf"""
    (?P<WS>\s+) |
    (?P<LINECOMMENT>//[^\n]*\n?) |
    (?P<BLOCKCOMMENT>/\*.*?\*/) |
    (?P<FLOAT>(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?(?:[fFlL])?) |
    (?P<INT>0[xX][0-9a-fA-F]+[uU]?|\d+[uU]?) |
    (?P<ID>[A-Za-z_][A-Za-z0-9_]*) |
    (?P<OP>{_OP_RE}) |
    (?P<PUNCT>{_PUNCT_RE})
    """,
    re.VERBOSE | re.DOTALL | re.MULTILINE,
)


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def lex(src: str) -> List[Token]:
    out: List[Token] = []
    for m in TOKEN_RE.finditer(src):
        kind = m.lastgroup
        value = m.group(kind)
        pos = m.start()

        if kind in ("WS", "LINECOMMENT", "BLOCKCOMMENT"):
            continue

        if kind == "ID" and value in KEYWORDS:
            out.append(Token("KW", value, pos))
        elif kind == "PUNCT":
            out.append(Token(value, value, pos))
        elif kind == "OP":
            out.append(Token("OP", value, pos))
        elif kind == "INT":
            out.append(Token("INT", value, pos))
        elif kind == "FLOAT":
            out.append(Token("FLOAT", value, pos))
        else:
            out.append(Token(kind, value, pos))

    out.append(Token("EOF", "", len(src)))
    return out

