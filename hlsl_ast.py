from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Union


# ---------- Directives ----------

@dataclass
class VersionDirective:
    text: str

@dataclass
class PragmaDirective:
    text: str

@dataclass
class DefineDirective:
    text: str

Directive = Union[VersionDirective, PragmaDirective, DefineDirective]


# ---------- Expressions ----------

class Expr:
    pass

@dataclass
class Identifier(Expr):
    name: str

@dataclass
class IntLiteral(Expr):
    value: int

@dataclass
class FloatLiteral(Expr):
    value: float

@dataclass
class BoolLiteral(Expr):
    value: bool

@dataclass
class UnaryExpr(Expr):
    op: str
    operand: Expr
    postfix: bool = False

@dataclass
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr

@dataclass
class TernaryExpr(Expr):
    cond: Expr
    then_expr: Expr
    else_expr: Expr

@dataclass
class CallExpr(Expr):
    callee: Expr
    args: List[Expr]

@dataclass
class IndexExpr(Expr):
    base: Expr
    index: Expr

@dataclass
class MemberExpr(Expr):
    base: Expr
    member: str

class InitListExpr(Expr):
    def __init__(self, elements):
        self.elements = elements

# Function parameters. This needs to be a separate class since there are modifiers such as "inout" etc..
class FunctionParam:
    def __init__(self, tname, name, dims, semantic, modifiers=None):
        self.tname = tname
        self.name = name
        self.dims = dims
        self.semantic = semantic
        self.modifiers = modifiers or []

# Initializer list...
class InitListExpr(Expr):
    def __init__(self, elems):
        self.elems = elems

# ---------- Types / decls ----------

@dataclass
class TypeName:
    name: str
    qualifiers: List[str] = field(default_factory=list)
    array_dims: List[Optional[Expr]] = field(default_factory=list)

@dataclass
class StructField:
    type_name: TypeName
    name: str
    array_dims: List[Optional[Expr]] = field(default_factory=list)
    semantic: Optional[str] = None

@dataclass
class VarDecl:
    type_name: TypeName
    name: str
    array_dims: List[Optional[Expr]] = field(default_factory=list)
    init: Optional[Expr] = None
    semantic: Optional[str] = None

@dataclass
class FunctionParam:
    type_name: TypeName
    name: Optional[str]
    array_dims: List[Optional[Expr]] = field(default_factory=list)
    semantic: Optional[str] = None

@dataclass
class Attribute:
    text: str


# ---------- Statements ----------

class Stmt:
    pass

@dataclass
class EmptyStmt(Stmt):
    pass

@dataclass
class ExprStmt(Stmt):
    expr: Expr

@dataclass
class DeclStmt(Stmt):
    decls: List[VarDecl]

@dataclass
class BlockStmt(Stmt):
    stmts: List[Stmt]

@dataclass
class IfStmt(Stmt):
    cond: Expr
    then_branch: Stmt
    else_branch: Optional[Stmt] = None

@dataclass
class WhileStmt(Stmt):
    cond: Expr
    body: Stmt

@dataclass
class DoWhileStmt(Stmt):
    body: Stmt
    cond: Expr

@dataclass
class ForStmt(Stmt):
    init: Optional[Union[DeclStmt, ExprStmt]]
    cond: Optional[Expr]
    loop: Optional[Expr]
    body: Stmt

@dataclass
class ReturnStmt(Stmt):
    expr: Optional[Expr]

@dataclass
class BreakStmt(Stmt):
    pass

@dataclass
class ContinueStmt(Stmt):
    pass

@dataclass
class DiscardStmt(Stmt):
    pass


# ---------- Top-level ----------

class TopLevel:
    pass

@dataclass
class StructDef(TopLevel):
    name: str
    fields: List[StructField]

@dataclass
class GlobalDecl(TopLevel):
    decls: List[VarDecl]
    attributes: List[Attribute] = field(default_factory=list)

@dataclass
class FunctionDef(TopLevel):
    return_type: TypeName
    name: str
    params: List[FunctionParam]
    body: BlockStmt
    return_semantic: Optional[str] = None
    attributes: List[Attribute] = field(default_factory=list)

@dataclass
class TranslationUnit:
    items: List[TopLevel]
    directives: List[Directive] = field(default_factory=list)
