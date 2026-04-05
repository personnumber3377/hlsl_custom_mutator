from __future__ import annotations
from hlsl_ast import *


def unparse_expr(e: Expr) -> str:
    if isinstance(e, Identifier):
        return e.name
    if isinstance(e, IntLiteral):
        return str(e.value)
    if isinstance(e, FloatLiteral):
        return repr(e.value)
    if isinstance(e, BoolLiteral):
        return "true" if e.value else "false"
    if isinstance(e, UnaryExpr):
        return f"{unparse_expr(e.operand)}{e.op}" if e.postfix else f"{e.op}{unparse_expr(e.operand)}"
    if isinstance(e, BinaryExpr):
        if e.op in ("=", "+=", "-=", "*=", "/=", "%=", ","):
            return f"{unparse_expr(e.left)} {e.op} {unparse_expr(e.right)}"
        return f"({unparse_expr(e.left)} {e.op} {unparse_expr(e.right)})"
    if isinstance(e, TernaryExpr):
        return f"({unparse_expr(e.cond)} ? {unparse_expr(e.then_expr)} : {unparse_expr(e.else_expr)})"
    if isinstance(e, CallExpr):
        return f"{unparse_expr(e.callee)}(" + ", ".join(unparse_expr(a) for a in e.args) + ")"
    if isinstance(e, IndexExpr):
        return f"{unparse_expr(e.base)}[{unparse_expr(e.index)}]"
    if isinstance(e, MemberExpr):
        return f"{unparse_expr(e.base)}.{e.member}"
    if isinstance(e, InitListExpr):
        return "{ " + ", ".join(unparse_expr(x) for x in e.elems) + " }"
    raise TypeError(type(e))


def unparse_array_dims(dims) -> str:
    out = ""
    for d in dims or []:
        if d is None:
            out += "[]"
        else:
            out += f"[{unparse_expr(d)}]"
    return out


def unparse_type(t: TypeName) -> str:
    parts = []
    if t.qualifiers:
        parts.extend(t.qualifiers)
    parts.append(t.name)
    parts.append(unparse_array_dims(t.array_dims))
    return " ".join(x for x in parts if x)


def unparse_semantic(s: str | None) -> str:
    return f" : {s}" if s else ""


def unparse_struct_field(f: StructField) -> str:
    return f"{unparse_type(f.type_name)} {f.name}{unparse_array_dims(f.array_dims)}{unparse_semantic(f.semantic)};"


def unparse_var_decl(v: VarDecl) -> str:
    s = f"{v.name}{unparse_array_dims(v.array_dims)}{unparse_semantic(v.semantic)}"
    if v.init is not None:
        s += f" = {unparse_expr(v.init)}"
    return s


def unparse_param(p: FunctionParam) -> str:
    parts = []
    if getattr(p, "modifiers", None):
        parts.extend(p.modifiers)
    parts.append(unparse_type(p.type_name))
    if p.name:
        parts.append(p.name)
    s = " ".join(parts)
    s += unparse_array_dims(p.array_dims)
    s += unparse_semantic(p.semantic)
    return s


def unparse_stmt(s: Stmt, indent: int = 0) -> str:
    pad = "  " * indent

    if isinstance(s, EmptyStmt):
        return pad + ";\n"
    if isinstance(s, ExprStmt):
        return pad + f"{unparse_expr(s.expr)};\n"
    if isinstance(s, DeclStmt):
        t = s.decls[0].type_name
        return pad + unparse_type(t) + " " + ", ".join(unparse_var_decl(d) for d in s.decls) + ";\n"
    if isinstance(s, BlockStmt):
        out = pad + "{\n"
        for st in s.stmts:
            out += unparse_stmt(st, indent + 1)
        out += pad + "}\n"
        return out
    if isinstance(s, IfStmt):
        out = pad + f"if ({unparse_expr(s.cond)})\n"
        out += unparse_stmt(s.then_branch, indent)
        if s.else_branch:
            out += pad + "else\n"
            out += unparse_stmt(s.else_branch, indent)
        return out
    if isinstance(s, WhileStmt):
        return pad + f"while ({unparse_expr(s.cond)})\n" + unparse_stmt(s.body, indent)
    if isinstance(s, DoWhileStmt):
        return pad + "do\n" + unparse_stmt(s.body, indent) + pad + f"while ({unparse_expr(s.cond)});\n"
    if isinstance(s, ForStmt):
        def _stmt_to_inline(x):
            if x is None:
                return ""
            txt = unparse_stmt(x, 0).strip()
            return txt[:-1] if txt.endswith(";") else txt
        return (
            pad
            + f"for ({_stmt_to_inline(s.init)}; "
            + (unparse_expr(s.cond) if s.cond else "")
            + "; "
            + (unparse_expr(s.loop) if s.loop else "")
            + ")\n"
            + unparse_stmt(s.body, indent)
        )
    if isinstance(s, ReturnStmt):
        return pad + ("return;\n" if s.expr is None else f"return {unparse_expr(s.expr)};\n")
    if isinstance(s, BreakStmt):
        return pad + "break;\n"
    if isinstance(s, ContinueStmt):
        return pad + "continue;\n"
    if isinstance(s, DiscardStmt):
        return pad + "discard;\n"

    raise TypeError(type(s))


def unparse_tu(tu: TranslationUnit) -> str:
    out = ""

    for d in tu.directives:
        if isinstance(d, PragmaDirective):
            out += f"#pragma {d.text}\n"
        elif isinstance(d, DefineDirective):
            out += f"#define {d.text}\n"
        elif isinstance(d, VersionDirective):
            out += d.text + ("\n" if not d.text.endswith("\n") else "")

    if out:
        out += "\n"

    for item in tu.items:
        if isinstance(item, StructDef):
            out += f"struct {item.name} {{\n"
            for f in item.fields:
                out += "  " + unparse_struct_field(f) + "\n"
            out += "};\n\n"
            continue

        if isinstance(item, GlobalDecl):
            for a in item.attributes:
                out += a.text + "\n"
            out += unparse_type(item.decls[0].type_name) + " " + ", ".join(unparse_var_decl(d) for d in item.decls) + ";\n\n"
            continue

        if isinstance(item, FunctionDef):
            for a in item.attributes:
                out += a.text + "\n"
            out += (
                f"{unparse_type(item.return_type)} {item.name}("
                + ", ".join(unparse_param(p) for p in item.params)
                + ")"
                + unparse_semantic(item.return_semantic)
                + "\n"
            )
            out += unparse_stmt(item.body, 0)
            out += "\n"
            continue

    return out
