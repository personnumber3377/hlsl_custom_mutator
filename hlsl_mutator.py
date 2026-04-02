from __future__ import annotations
import copy
import random

from hlsl_ast import *
from hlsl_input_format import Header, unpack_blob, pack_blob
from hlsl_parser import parse_to_tree, ParseError
from hlsl_unparser import unparse_tu


SCALAR_TYPES = ["int", "uint", "float", "bool"]
VECTOR_TYPES = ["float2", "float3", "float4", "int2", "int3", "int4", "uint2", "uint3", "uint4"]


class TypeInfo:
    def __init__(self, name: str, array_dims=None):
        self.name = name
        self.array_dims = list(array_dims or [])

    def is_array(self) -> bool:
        return bool(self.array_dims)

    def elem(self) -> "TypeInfo":
        if not self.array_dims:
            return self
        return TypeInfo(self.name, self.array_dims[1:])


class Env:
    def __init__(self):
        self.struct_defs: dict[str, list[StructField]] = {}
        self.globals: dict[str, TypeInfo] = {}
        self.funcs: dict[str, tuple[TypeInfo, list[TypeInfo]]] = {}

    def clone(self):
        return copy.deepcopy(self)


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.vars: dict[str, TypeInfo] = {}

    def define(self, name: str, ti: TypeInfo):
        self.vars[name] = ti

    def lookup(self, name: str):
        s = self
        while s is not None:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        return None

    def all_vars(self):
        out = {}
        s = self
        while s is not None:
            out.update(s.vars)
            s = s.parent
        return out


def typename_to_typeinfo(t: TypeName) -> TypeInfo:
    return TypeInfo(t.name, t.array_dims)


def vardecl_to_typeinfo(v: VarDecl) -> TypeInfo:
    return TypeInfo(v.type_name.name, v.array_dims)


def build_env(tu: TranslationUnit) -> Env:
    env = Env()
    for item in tu.items:
        if isinstance(item, StructDef):
            env.struct_defs[item.name] = list(item.fields)
        elif isinstance(item, GlobalDecl):
            for d in item.decls:
                env.globals[d.name] = vardecl_to_typeinfo(d)
        elif isinstance(item, FunctionDef):
            env.funcs[item.name] = (
                typename_to_typeinfo(item.return_type),
                [typename_to_typeinfo(p.type_name) for p in item.params],
            )
    return env


def coin(rng: random.Random, p: float) -> bool:
    return rng.random() < p


def choose(rng: random.Random, xs):
    return xs[rng.randrange(len(xs))] if xs else None


def infer_expr_type(e: Expr, scope: Scope, env: Env):
    if isinstance(e, IntLiteral):
        return TypeInfo("int")
    if isinstance(e, FloatLiteral):
        return TypeInfo("float")
    if isinstance(e, BoolLiteral):
        return TypeInfo("bool")
    if isinstance(e, Identifier):
        return scope.lookup(e.name) or env.globals.get(e.name)
    if isinstance(e, UnaryExpr):
        return infer_expr_type(e.operand, scope, env)
    if isinstance(e, BinaryExpr):
        if e.op in ("&&", "||", "<", ">", "<=", ">=", "==", "!="):
            return TypeInfo("bool")
        return infer_expr_type(e.left, scope, env)
    if isinstance(e, TernaryExpr):
        return infer_expr_type(e.then_expr, scope, env)
    if isinstance(e, CallExpr) and isinstance(e.callee, Identifier):
        sig = env.funcs.get(e.callee.name)
        if sig:
            return sig[0]
    if isinstance(e, MemberExpr):
        bt = infer_expr_type(e.base, scope, env)
        if bt and bt.name in env.struct_defs:
            for f in env.struct_defs[bt.name]:
                if f.name == e.member:
                    return TypeInfo(f.type_name.name, f.array_dims)
    if isinstance(e, IndexExpr):
        bt = infer_expr_type(e.base, scope, env)
        if bt:
            return bt.elem()
    return None


def candidates_by_type(scope: Scope, env: Env, want: TypeInfo | None):
    allv = scope.all_vars()
    for k, v in env.globals.items():
        if k not in allv:
            allv[k] = v
    if want is None:
        return list(allv.keys())
    same = [n for n, ti in allv.items() if ti.name == want.name]
    return same


def gen_literal_for_type(want: TypeInfo, rng: random.Random) -> Expr:
    if want.name == "int":
        return IntLiteral(rng.randrange(0, 8))
    if want.name == "uint":
        return IntLiteral(rng.randrange(0, 8))
    if want.name == "float":
        return FloatLiteral(rng.choice([0.0, 0.5, 1.0, -1.0, 2.0]))
    if want.name == "bool":
        return BoolLiteral(rng.choice([True, False]))
    if want.name in ("float2", "float3", "float4", "int2", "int3", "int4", "uint2", "uint3", "uint4"):
        n = int(want.name[-1])
        base = "float" if "float" in want.name else ("uint" if "uint" in want.name else "int")
        return CallExpr(Identifier(want.name), [gen_literal_for_type(TypeInfo(base), rng) for _ in range(n)])
    if want.name in env_struct_names_cache:
        fields = env_struct_names_cache[want.name]
        return CallExpr(Identifier(want.name), [gen_literal_for_type(TypeInfo(f.type_name.name), rng) for f in fields])
    return IntLiteral(0)


env_struct_names_cache = {}


def gen_expr(want: TypeInfo | None, scope: Scope, env: Env, rng: random.Random, depth: int = 0) -> Expr:
    global env_struct_names_cache
    env_struct_names_cache = env.struct_defs

    if depth > 3:
        return gen_leaf(want, scope, env, rng)

    ops = [lambda: gen_leaf(want, scope, env, rng)]

    if want and want.name in ("int", "float", "bool"):
        ops += [
            lambda: UnaryExpr(choose(rng, ["+", "-", "!"]), gen_expr(want, scope, env, rng, depth + 1)),
            lambda: BinaryExpr(choose(rng, ["+", "-", "*", "/", "==", "!=", "<", ">"]), gen_expr(want, scope, env, rng, depth + 1), gen_expr(want, scope, env, rng, depth + 1)),
            lambda: TernaryExpr(gen_expr(TypeInfo("bool"), scope, env, rng, depth + 1), gen_expr(want, scope, env, rng, depth + 1), gen_expr(want, scope, env, rng, depth + 1)),
        ]

    if env.funcs:
        ops.append(lambda: gen_call(want, scope, env, rng, depth))

    if env.struct_defs:
        ops.append(lambda: gen_member_access(want, scope, env, rng, depth))

    return choose(rng, ops)()


def gen_leaf(want: TypeInfo | None, scope: Scope, env: Env, rng: random.Random) -> Expr:
    if want:
        pool = candidates_by_type(scope, env, want)
        if pool and coin(rng, 0.35):
            return Identifier(choose(rng, pool))
        return gen_literal_for_type(want, rng)

    any_name = candidates_by_type(scope, env, None)
    if any_name and coin(rng, 0.5):
        return Identifier(choose(rng, any_name))
    return IntLiteral(rng.randrange(0, 8))


def gen_call(want: TypeInfo | None, scope: Scope, env: Env, rng: random.Random, depth: int) -> Expr:
    cands = []
    for fname, (ret, params) in env.funcs.items():
        if want is None or ret.name == want.name:
            cands.append((fname, params))
    if not cands:
        return gen_leaf(want, scope, env, rng)
    fname, params = choose(rng, cands)
    args = [gen_expr(pt, scope, env, rng, depth + 1) for pt in params]
    return CallExpr(Identifier(fname), args)


def gen_member_access(want: TypeInfo | None, scope: Scope, env: Env, rng: random.Random, depth: int) -> Expr:
    vars_ = [(n, ti) for n, ti in scope.all_vars().items() if ti.name in env.struct_defs]
    for n, ti in env.globals.items():
        if ti.name in env.struct_defs and n not in {x[0] for x in vars_}:
            vars_.append((n, ti))
    if not vars_:
        return gen_leaf(want, scope, env, rng)
    n, ti = choose(rng, vars_)
    fields = env.struct_defs[ti.name]
    f = choose(rng, fields)
    return MemberExpr(Identifier(n), f.name)


def mutate_expr(e: Expr, rng: random.Random, scope: Scope, env: Env) -> Expr:
    if coin(rng, 0.05):
        t = infer_expr_type(e, scope, env)
        return gen_expr(t, scope, env, rng)

    if isinstance(e, Identifier):
        ti = scope.lookup(e.name) or env.globals.get(e.name)
        pool = candidates_by_type(scope, env, ti)
        if pool and coin(rng, 0.25):
            return Identifier(choose(rng, pool))
        return e

    if isinstance(e, IntLiteral):
        if coin(rng, 0.4):
            return IntLiteral(e.value + choose(rng, [-2, -1, 1, 2, 4, 8]))
        return e

    if isinstance(e, FloatLiteral):
        if coin(rng, 0.4):
            return FloatLiteral(e.value + choose(rng, [-1.0, -0.5, 0.5, 1.0]))
        return e

    if isinstance(e, BoolLiteral):
        if coin(rng, 0.4):
            return BoolLiteral(not e.value)
        return e

    if isinstance(e, UnaryExpr):
        return UnaryExpr(e.op, mutate_expr(e.operand, rng, scope, env), e.postfix)

    if isinstance(e, BinaryExpr):
        op = e.op
        if coin(rng, 0.15):
            op = choose(rng, [op, "+", "-", "*", "/", "==", "!=", "<", ">", "&&", "||"])
        return BinaryExpr(op, mutate_expr(e.left, rng, scope, env), mutate_expr(e.right, rng, scope, env))

    if isinstance(e, TernaryExpr):
        return TernaryExpr(
            mutate_expr(e.cond, rng, scope, env),
            mutate_expr(e.then_expr, rng, scope, env),
            mutate_expr(e.else_expr, rng, scope, env),
        )

    if isinstance(e, CallExpr):
        args = [mutate_expr(a, rng, scope, env) for a in e.args]
        return CallExpr(e.callee, args)

    if isinstance(e, IndexExpr):
        return IndexExpr(mutate_expr(e.base, rng, scope, env), mutate_expr(e.index, rng, scope, env))

    if isinstance(e, MemberExpr):
        bt = infer_expr_type(e.base, scope, env)
        if bt and bt.name in env.struct_defs and coin(rng, 0.35):
            names = [f.name for f in env.struct_defs[bt.name]]
            other = [x for x in names if x != e.member]
            if other:
                return MemberExpr(mutate_expr(e.base, rng, scope, env), choose(rng, other))
        return MemberExpr(mutate_expr(e.base, rng, scope, env), e.member)

    return e


def mutate_stmt(s: Stmt, rng: random.Random, scope: Scope, env: Env) -> Stmt:
    if isinstance(s, BlockStmt):
        child = Scope(scope)
        out = list(s.stmts)
        if out:
            i = rng.randrange(len(out))
            out[i] = mutate_stmt(out[i], rng, child, env)
        if coin(rng, 0.15):
            expr = gen_expr(TypeInfo(choose(rng, SCALAR_TYPES)), child, env, rng)
            out.append(ExprStmt(expr))
        return BlockStmt(out)

    if isinstance(s, DeclStmt):
        decls = copy.deepcopy(s.decls)
        if decls:
            i = rng.randrange(len(decls))
            d = decls[i]
            if d.init is not None:
                d.init = mutate_expr(d.init, rng, scope, env)
            else:
                d.init = gen_expr(TypeInfo(d.type_name.name), scope, env, rng)
        for d in decls:
            scope.define(d.name, vardecl_to_typeinfo(d))
        return DeclStmt(decls)

    if isinstance(s, ExprStmt):
        return ExprStmt(mutate_expr(s.expr, rng, scope, env))

    if isinstance(s, IfStmt):
        return IfStmt(
            mutate_expr(s.cond, rng, scope, env),
            mutate_stmt(s.then_branch, rng, Scope(scope), env),
            mutate_stmt(s.else_branch, rng, Scope(scope), env) if s.else_branch else None,
        )

    if isinstance(s, WhileStmt):
        return WhileStmt(mutate_expr(s.cond, rng, scope, env), mutate_stmt(s.body, rng, Scope(scope), env))

    if isinstance(s, DoWhileStmt):
        return DoWhileStmt(mutate_stmt(s.body, rng, Scope(scope), env), mutate_expr(s.cond, rng, scope, env))

    if isinstance(s, ForStmt):
        child = Scope(scope)
        init = mutate_stmt(s.init, rng, child, env) if s.init else None
        cond = mutate_expr(s.cond, rng, child, env) if s.cond else None
        loop = mutate_expr(s.loop, rng, child, env) if s.loop else None
        body = mutate_stmt(s.body, rng, child, env)
        return ForStmt(init, cond, loop, body)

    if isinstance(s, ReturnStmt):
        return ReturnStmt(mutate_expr(s.expr, rng, scope, env) if s.expr else None)

    return s


def mutate_function(fn: FunctionDef, rng: random.Random, env: Env) -> FunctionDef:
    fn2 = copy.deepcopy(fn)
    scope = Scope(None)
    for p in fn2.params:
        if p.name:
            scope.define(p.name, typename_to_typeinfo(p.type_name))
    fn2.body = mutate_stmt(fn2.body, rng, scope, env)
    return fn2


def mutate_global(g: GlobalDecl, rng: random.Random, env: Env) -> GlobalDecl:
    g2 = copy.deepcopy(g)
    if g2.decls:
        i = rng.randrange(len(g2.decls))
        d = g2.decls[i]
        if d.init is not None:
            d.init = mutate_expr(d.init, rng, Scope(None), env)
        elif coin(rng, 0.35):
            d.init = gen_expr(TypeInfo(d.type_name.name), Scope(None), env, rng)
    return g2


def mutate_struct(sd: StructDef, rng: random.Random) -> StructDef:
    sd2 = copy.deepcopy(sd)
    if sd2.fields and coin(rng, 0.25):
        i = rng.randrange(len(sd2.fields))
        sd2.fields[i].name += choose(rng, ["_", "0", "x", "y"])
    return sd2


def mutate_header(h: Header, rng: random.Random) -> Header:
    h = copy.deepcopy(h)
    if coin(rng, 0.30):
        h.exec_mode = rng.randrange(0, 6)
    if coin(rng, 0.30):
        h.sub_mode ^= 1 << rng.randrange(0, 8)
    if coin(rng, 0.30):
        h.src_mode = rng.randrange(0, 3)
    if coin(rng, 0.35):
        h.bits0 ^= 1 << rng.randrange(0, 8)
    if coin(rng, 0.35):
        h.bits1 ^= 1 << rng.randrange(0, 8)
    if coin(rng, 0.35):
        h.bits2 ^= 1 << rng.randrange(0, 8)
    return h


def mutate_translation_unit(tu: TranslationUnit, rng: random.Random) -> TranslationUnit:
    tu2 = copy.deepcopy(tu)
    env = build_env(tu2)

    if not tu2.items:
        return tu2

    i = rng.randrange(len(tu2.items))
    item = tu2.items[i]

    if isinstance(item, FunctionDef):
        tu2.items[i] = mutate_function(item, rng, env)
    elif isinstance(item, GlobalDecl):
        tu2.items[i] = mutate_global(item, rng, env)
    elif isinstance(item, StructDef):
        tu2.items[i] = mutate_struct(item, rng)

    if coin(rng, 0.10) and env.struct_defs:
        sname = choose(rng, list(env.struct_defs.keys()))
        if sname:
            vname = f"g_{rng.randrange(10000)}"
            decl = GlobalDecl([
                VarDecl(TypeName(sname), vname, [], CallExpr(Identifier(sname), []), None)
            ])
            tu2.items.insert(rng.randrange(len(tu2.items) + 1), decl)

    return tu2


def mutate_blob(data: bytes, seed: int | None = None) -> bytes:
    rng = random.Random(seed)
    h, src_bytes = unpack_blob(data)

    try:
        src = src_bytes.decode("utf-8", errors="ignore")
        tu = parse_to_tree(src)
        tu2 = mutate_translation_unit(tu, rng)
        src2 = unparse_tu(tu2).encode("utf-8", errors="ignore")
        h2 = mutate_header(h, rng)
        return pack_blob(h2, src2)
    except Exception:
        h2 = mutate_header(h, rng)
        raw = bytearray(src_bytes)
        if raw:
            for _ in range(1 + rng.randrange(4)):
                idx = rng.randrange(len(raw))
                raw[idx] ^= 1 << rng.randrange(8)
        return pack_blob(h2, bytes(raw))
