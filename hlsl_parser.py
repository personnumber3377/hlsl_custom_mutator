from __future__ import annotations
from typing import List, Optional, Union

from hlsl_lexer import Token, lex, QUALIFIERS, TYPELIKE_KEYWORDS
from hlsl_ast import *


class ParseError(Exception):
    pass

def dump_tokens(src: str):
    for t in lex(src):
        print(f"{t.kind:>8}  {t.value!r}  @{t.pos}")

PRECEDENCE = {
    ",": 1,
    "=": 2, "+=": 2, "-=": 2, "*=": 2, "/=": 2, "%=": 2,
    "||": 3,
    "&&": 4,
    "|": 5,
    "^": 6,
    "&": 7,
    "==": 8, "!=": 8,
    "<": 9, "<=": 9, ">": 9, ">=": 9,
    "<<": 10, ">>": 10,
    "+": 11, "-": 11,
    "*": 12, "/": 12, "%": 12,
    "CALL": 15,
    "INDEX": 15,
    ".": 16,
}
RIGHT_ASSOC = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, tokens: List[Token], original_input: Optional[str] = None):
        self.toks = tokens
        self.i = 0
        self.original_input = original_input or ""

    def peek(self) -> Token:
        return self.toks[self.i]

    def advance(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def match(self, kind: str, value: Optional[str] = None) -> bool:
        t = self.peek()
        if value is None:
            if t.kind == kind:
                self.advance()
                return True
            return False
        if t.kind == kind and t.value == value:
            self.advance()
            return True
        if t.kind == value and t.value == value:
            self.advance()
            return True
        return False

    def expect(self, kind: str, value: Optional[str] = None) -> Token:
        t = self.peek()
        if self.match(kind, value):
            return self.toks[self.i - 1]
        raise ParseError(f"Expected {kind} {value or ''} at {t.pos}, got {t.kind}:{t.value}")

    def parse_attributes(self) -> List[Attribute]:
        attrs: List[Attribute] = []
        while self.peek().kind == "[":
            self.advance()
            depth = 1
            parts = []
            while depth > 0:
                t = self.advance()
                if t.kind == "[":
                    depth += 1
                elif t.kind == "]":
                    depth -= 1
                    if depth == 0:
                        break
                parts.append(t.value)
            attrs.append(Attribute("[" + "".join(parts) + "]"))
        return attrs

    def parse_semantic(self) -> Optional[str]:
        if not self.match("OP", ":"):
            return None
        t = self.peek()
        if t.kind in ("ID", "KW", "INT"):
            return self.advance().value
        return None

    def parse_expr(self, min_prec: int = 0) -> Expr:
        left = self.parse_prefix()

        while True:
            t = self.peek()

            if t.kind == "OP" and t.value in ("++", "--"):
                if PRECEDENCE["CALL"] < min_prec:
                    break
                op = self.advance().value
                left = UnaryExpr(op, left, postfix=True)
                continue

            if t.kind == "(":
                if PRECEDENCE["CALL"] < min_prec:
                    break
                left = self.parse_call(left)
                continue

            if t.kind == "[":
                if PRECEDENCE["INDEX"] < min_prec:
                    break
                left = self.parse_index(left)
                continue

            if t.kind == "OP" and t.value == ".":
                if PRECEDENCE["."] < min_prec:
                    break
                self.advance()
                ident = self.expect("ID")
                left = MemberExpr(left, ident.value)
                continue

            if t.kind == "OP" and t.value == "?":
                if 0 < min_prec:
                    break
                self.advance()
                then_expr = self.parse_expr(0)
                self.expect("OP", ":")
                else_expr = self.parse_expr(0)
                left = TernaryExpr(left, then_expr, else_expr)
                continue

            if t.kind == "OP" and t.value in PRECEDENCE:
                op = t.value
                prec = PRECEDENCE[op]
                if prec < min_prec:
                    break
                self.advance()
                next_min = prec + (0 if op in RIGHT_ASSOC else 1)
                right = self.parse_expr(next_min)
                left = BinaryExpr(op, left, right)
                continue

            if t.kind == ",":
                op = ","
                prec = PRECEDENCE[op]
                if prec < min_prec:
                    break
                self.advance()
                right = self.parse_expr(prec + 1)
                left = BinaryExpr(op, left, right)
                continue

            break

        return left

    def parse_prefix(self) -> Expr:
        t = self.peek()

        if t.kind == "(":
            self.advance()
            e = self.parse_expr(0)
            self.expect(")")
            return e

        if t.kind == "{":
            self.advance()
            elems = []
            if not self.match("}"):
                while True:
                    elems.append(self.parse_expr(0))
                    if self.match("}"):
                        break
                    self.expect(",")
            return InitListExpr(elems)

        if t.kind == "INT":
            self.advance()
            s = t.value.lower().rstrip("u")
            val = int(s, 16) if s.startswith("0x") else int(s, 10)
            return IntLiteral(val)

        if t.kind == "FLOAT":
            self.advance()
            return FloatLiteral(float(t.value.rstrip("fFlL")))

        if t.kind == "KW" and t.value in ("true", "false"):
            self.advance()
            return BoolLiteral(t.value == "true")

        if t.kind == "OP" and t.value in ("+", "-", "!", "~", "++", "--"):
            op = self.advance().value
            operand = self.parse_expr(PRECEDENCE["CALL"])
            return UnaryExpr(op, operand, postfix=False)

        if t.kind in ("ID", "KW"):
            self.advance()
            return Identifier(t.value)
        '''
        if t.kind == "{": # Like 
            self.advance()
            elems = []

            if not self.match("}"):
                while True:
                    elems.append(self.parse_expr(0))
                    if self.match("}"):
                        break
                    self.expect(",")

            return InitListExpr(elems)
        '''

        raise ParseError(f"Unexpected token in expression at {t.pos}: {t.kind}:{t.value}")

    def parse_call(self, callee: Expr) -> Expr:
        self.expect("(")
        args: List[Expr] = []
        if not self.match(")"):
            while True:
                args.append(self.parse_expr(0))
                if self.match(")"):
                    break
                self.expect(",")
        return CallExpr(callee, args)

    def parse_index(self, base: Expr) -> Expr:
        self.expect("[")
        idx = self.parse_expr(0)
        self.expect("]")
        return IndexExpr(base, idx)

    def parse_type_name(self) -> TypeName:
        qualifiers: List[str] = []
        while self.peek().kind == "KW" and self.peek().value in QUALIFIERS:
            qualifiers.append(self.advance().value)

        t = self.peek()
        if (t.kind == "KW" and t.value in TYPELIKE_KEYWORDS) or t.kind == "ID":
            name = self.advance().value
            return TypeName(name=name, qualifiers=qualifiers)

        raise ParseError(f"Expected type name at {t.pos}, got {t.kind}:{t.value}")

    def parse_array_dims(self) -> List[Optional[Expr]]:
        dims: List[Optional[Expr]] = []
        while self.match("["):
            if self.match("]"):
                dims.append(None)
            else:
                dims.append(self.parse_expr(0))
                self.expect("]")
        return dims

    def parse_var_decl(self, tname: TypeName) -> VarDecl:
        name = self.expect("ID").value
        array_dims = self.parse_array_dims()
        semantic = self.parse_semantic()
        init = None
        if self.match("OP", "="):
            init = self.parse_expr(0)
        return VarDecl(tname, name, array_dims, init, semantic)

    def parse_struct_field(self) -> List[StructField]:
        tname = self.parse_type_name()
        fields = []
        while True:
            name = self.expect("ID").value
            dims = self.parse_array_dims()
            semantic = self.parse_semantic()
            fields.append(StructField(tname, name, dims, semantic))
            if not self.match(","):
                break
        self.expect(";")
        return fields

    def parse_struct_def(self) -> StructDef:
        self.expect("KW", "struct")
        name = self.expect("ID").value
        self.expect("{")
        fields: List[StructField] = []
        while self.peek().kind != "}":
            fields.extend(self.parse_struct_field())
        self.expect("}")
        self.expect(";")
        return StructDef(name, fields)

    def parse_param(self) -> FunctionParam:
        modifiers = []

        # 👇 NEW: consume param modifiers
        while self.peek().kind == "KW" and self.peek().value in ("in", "out", "inout", "uniform"):
            modifiers.append(self.advance().value)

        tname = self.parse_type_name()

        pname = None
        if self.peek().kind == "ID":
            pname = self.advance().value

        dims = self.parse_array_dims()
        semantic = self.parse_semantic()
        return FunctionParam(
            type_name=tname,
            name=pname,
            array_dims=dims,
            semantic=semantic,
            modifiers=modifiers
        )
        # return FunctionParam(tname, pname, dims, semantic, modifiers)

    def parse_decl_stmt(self) -> DeclStmt:
        tname = self.parse_type_name()
        decls = [self.parse_var_decl(tname)]
        while self.match(","):
            decls.append(self.parse_var_decl(tname))
        self.expect(";")
        return DeclStmt(decls)

    def parse_stmt(self) -> Stmt:
        t = self.peek()

        if t.kind == "{":
            return self.parse_block()

        if t.kind == ";":
            self.advance()
            return EmptyStmt()

        if t.kind == "KW" and t.value == "if":
            self.advance()
            self.expect("(")
            cond = self.parse_expr(0)
            self.expect(")")
            then_branch = self.parse_stmt()
            else_branch = None
            if self.peek().kind == "KW" and self.peek().value == "else":
                self.advance()
                else_branch = self.parse_stmt()
            return IfStmt(cond, then_branch, else_branch)

        if t.kind == "KW" and t.value == "while":
            self.advance()
            self.expect("(")
            cond = self.parse_expr(0)
            self.expect(")")
            body = self.parse_stmt()
            return WhileStmt(cond, body)

        if t.kind == "KW" and t.value == "do":
            self.advance()
            body = self.parse_stmt()
            self.expect("KW", "while")
            self.expect("(")
            cond = self.parse_expr(0)
            self.expect(")")
            self.expect(";")
            return DoWhileStmt(body, cond)

        if t.kind == "KW" and t.value == "for":
            self.advance()
            self.expect("(")
            init: Optional[Union[DeclStmt, ExprStmt]] = None
            if self.peek().kind != ";":
                if self._looks_like_decl():
                    init = self.parse_decl_stmt()
                else:
                    e = self.parse_expr(0)
                    self.expect(";")
                    init = ExprStmt(e)
            else:
                self.expect(";")

            cond = None
            if self.peek().kind != ";":
                cond = self.parse_expr(0)
            self.expect(";")

            loop = None
            if self.peek().kind != ")":
                loop = self.parse_expr(0)
            self.expect(")")

            body = self.parse_stmt()
            return ForStmt(init, cond, loop, body)

        if t.kind == "KW" and t.value == "return":
            self.advance()
            if self.peek().kind == ";":
                self.advance()
                return ReturnStmt(None)
            e = self.parse_expr(0)
            self.expect(";")
            return ReturnStmt(e)

        if t.kind == "KW" and t.value == "break":
            self.advance()
            self.expect(";")
            return BreakStmt()

        if t.kind == "KW" and t.value == "continue":
            self.advance()
            self.expect(";")
            return ContinueStmt()

        if t.kind == "KW" and t.value == "discard":
            self.advance()
            self.expect(";")
            return DiscardStmt()

        if self._looks_like_decl():
            return self.parse_decl_stmt()

        e = self.parse_expr(0)
        self.expect(";")
        return ExprStmt(e)

    def parse_block(self) -> BlockStmt:
        self.expect("{")
        stmts: List[Stmt] = []
        while self.peek().kind != "}":
            stmts.append(self.parse_stmt())
        self.expect("}")
        return BlockStmt(stmts)

    def _looks_like_decl(self) -> bool:
        j = self.i
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == "KW" and t.value in QUALIFIERS:
                j += 1
                continue
            break
        if j >= len(self.toks):
            return False

        t = self.toks[j]
        if not ((t.kind == "KW" and t.value in TYPELIKE_KEYWORDS) or t.kind == "ID"):
            return False

        if j + 1 >= len(self.toks):
            return False

        j += 1
        if self.toks[j].kind != "ID":
            return False

        j += 1
        while j < len(self.toks) and self.toks[j].kind == "[":
            j += 1
            if j < len(self.toks) and self.toks[j].kind != "]":
                j += 1
            if j < len(self.toks) and self.toks[j].kind == "]":
                j += 1

        if j < len(self.toks) and self.toks[j].kind == "(":
            return False
        return True

    def parse_global_decl_or_function(self, attrs: List[Attribute]) -> TopLevel:
        save = self.i
        ret = self.parse_type_name()

        if self.peek().kind != "ID":
            self.i = save
            raise ParseError("expected identifier after type")

        name_tok = self.advance()
        if self.peek().kind == "(":
            self.expect("(")
            params: List[FunctionParam] = []
            if not self.match(")"):
                while True:
                    params.append(self.parse_param())
                    if self.match(")"):
                        break
                    self.expect(",")
            ret_sem = self.parse_semantic()
            body = self.parse_block()
            return FunctionDef(ret, name_tok.value, params, body, ret_sem, attrs)

        self.i = save
        ds = self.parse_decl_stmt()
        return GlobalDecl(ds.decls, attrs)

    def parse_translation_unit(self) -> TranslationUnit:
        items: List[TopLevel] = []
        while self.peek().kind != "EOF":
            attrs = self.parse_attributes()
            t = self.peek()

            if t.kind == "KW" and t.value == "struct":
                items.append(self.parse_struct_def())
                continue

            items.append(self.parse_global_decl_or_function(attrs))

        return TranslationUnit(items)


def parse_directives_and_body(src: str) -> tuple[List[Directive], str]:
    directives: List[Directive] = []
    body_lines: List[str] = []

    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#pragma"):
            directives.append(PragmaDirective(s[len("#pragma"):].strip()))
        elif s.startswith("#define"):
            directives.append(DefineDirective(s[len("#define"):].strip()))
        elif s.startswith("#"):
            directives.append(VersionDirective(s))
        else:
            body_lines.append(line)

    return directives, "\n".join(body_lines)


def parse_to_tree(src: str) -> TranslationUnit:
    directives, body = parse_directives_and_body(src)
    toks = lex(body)
    p = Parser(toks, original_input=src)
    tu = p.parse_translation_unit()
    tu.directives = directives
    return tu
