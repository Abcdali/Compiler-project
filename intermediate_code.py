# =============================================================================
# intermediate_code.py  —  Three-Address Code (TAC) generator
# =============================================================================
# Phase: Intermediate Code Generation
#
# Walks the parse tree (Node) produced by any Crystal parser and emits
# three-address code.  Every instruction has at most three addresses:
#
#       result = arg1  op  arg2
#
# Temporaries are named t1, t2, ...   Labels are named L1, L2, ...
# =============================================================================

from parser_rules import Node


# Arithmetic operator token  →  TAC symbol
BIN_OPS = {
    "plus": "+", "minus": "-", "mul": "*", "div": "/",
    "mode": "%", "power": "**",
}

# Relational operator token  →  TAC symbol
REL_OPS = {
    "is_it":   "==", "==":       "==",
    "is_less":  "<",  "is_grtr":  ">",
    "less=":   "<=", "grtr=":    ">=",
    "is_less=":"<=", "is_grtr=": ">=",
}


# ---------------------------------------------------------------------------
# A single three-address instruction (quadruple form: op, arg1, arg2, result)
# ---------------------------------------------------------------------------
class Quad:
    __slots__ = ("op", "arg1", "arg2", "result")

    def __init__(self, op, arg1=None, arg2=None, result=None):
        self.op     = op
        self.arg1   = arg1
        self.arg2   = arg2
        self.result = result

    def to_text(self) -> str:
        """Render this instruction as a single line of three-address code."""
        op = self.op
        if op == "label":   return f"{self.result}:"
        if op == "goto":    return f"    goto {self.result}"
        if op == "ifFalse": return f"    ifFalse {self.arg1} goto {self.result}"
        if op == "if":      return f"    if {self.arg1} goto {self.result}"
        if op == "=":       return f"    {self.result} = {self.arg1}"
        if op == "display": return f"    display {self.arg1}"
        if op == "read":    return f"    read {self.arg1}"
        if op == "param":   return f"    param {self.arg1}"
        if op == "return":
            return f"    return {self.arg1}" if self.arg1 is not None else "    return"
        if op == "func":    return f"\nfunc {self.result}:"
        if op == "endfunc": return f"    end func {self.result}\n"
        # default: binary instruction  result = arg1 op arg2
        return f"    {self.result} = {self.arg1} {op} {self.arg2}"

    def as_row(self):
        """Return (op, arg1, arg2, result) strings for a quadruple table."""
        return (
            self.op,
            "" if self.arg1   is None else str(self.arg1),
            "" if self.arg2   is None else str(self.arg2),
            "" if self.result is None else str(self.result),
        )


# ---------------------------------------------------------------------------
# Three-Address Code generator
# ---------------------------------------------------------------------------
class TACGenerator:
    """Generate three-address code from a Crystal parse tree."""

    def __init__(self):
        self.quads = []
        self._t = 0
        self._l = 0

    # ── name factories ──────────────────────────────────────────────────
    def new_temp(self) -> str:
        self._t += 1
        return f"t{self._t}"

    def new_label(self) -> str:
        self._l += 1
        return f"L{self._l}"

    def emit(self, op, arg1=None, arg2=None, result=None):
        self.quads.append(Quad(op, arg1, arg2, result))

    # ── tree navigation helpers ─────────────────────────────────────────
    def _child(self, node, *names):
        if node is None:
            return None
        for c in node.kids:
            if c.name in names:
                return c
        return None

    def _children(self, node, *names):
        if node is None:
            return []
        return [c for c in node.kids if c.name in names]

    def _ident(self, node):
        """First direct IDENTIFIER terminal child's value."""
        for c in node.kids:
            if c.tok_type == "IDENTIFIER":
                return c.value if c.value is not None else c.name
        return "?"

    @staticmethod
    def _leaf_val(node):
        return node.value if node.value is not None else node.name

    # ── entry point ─────────────────────────────────────────────────────
    def generate(self, root: Node):
        self.quads = []
        self._t = 0
        self._l = 0
        prog = root
        # Unwrap augmented start  Program'  →  Program  (LR parsers)
        if prog is not None and prog.name.endswith("'") and prog.kids:
            prog = prog.kids[0]
        if prog is not None:
            self._program(prog)
        return self.quads

    # ── Program → FuncList StmtList ─────────────────────────────────────
    def _program(self, node):
        self._funclist(self._child(node, "FuncList"))
        self._stmtlist(self._child(node, "StmtList"))

    # ── FuncList → FunctionDef FuncList | ε ─────────────────────────────
    def _funclist(self, node):
        fd = self._child(node, "FunctionDef")
        if fd:
            self._functiondef(fd)
            self._funclist(self._child(node, "FuncList"))

    def _functiondef(self, node):
        name = self._ident(node)
        self.emit("func", result=name)
        # Parameters become incoming params.
        for ident in self._collect_param_names(self._child(node, "ParamList")):
            self.emit("param", arg1=ident)
        self._stmtlist(self._child(node, "StmtList"))
        self.emit("endfunc", result=name)

    def _collect_param_names(self, param_list):
        names = []
        cur = param_list
        while cur and cur.kids:
            param = self._child(cur, "Param")
            if param:
                names.append(self._ident(param))
            cur = self._child(cur, "ParamTail")
        return names

    # ── StmtList → Stmt StmtList | ε ────────────────────────────────────
    def _stmtlist(self, node):
        st = self._child(node, "Stmt")
        if st:
            self._stmt(st)
            self._stmtlist(self._child(node, "StmtList"))

    def _stmt(self, node):
        if not node.kids:
            return
        c = node.kids[0]
        dispatch = {
            "DeclStmt":    self._decl,
            "AssignStmt":  self._assign,
            "DisplayStmt": self._display,
            "InputStmt":   self._input,
            "CheckStmt":   self._check,
            "WhileLoop":   self._while,
            "ForLoop":     self._for,
            "DoLoop":      self._do,
            "ReturnStmt":  self._return,
        }
        handler = dispatch.get(c.name)
        if handler:
            handler(c)

    # ── Declarations / Assignments ──────────────────────────────────────
    def _decl(self, node):
        # DataType IDENTIFIER DeclTail   (DeclTail = equalto Expr Semi | Semi)
        name  = self._ident(node)
        dtail = self._child(node, "DeclTail")
        expr  = self._child(dtail, "Expr") if dtail else None
        if expr:
            place = self._expr(expr)
            self.emit("=", arg1=place, result=name)

    def _assign(self, node):
        # IDENTIFIER equalto Expr Semi
        name  = self._ident(node)
        place = self._expr(self._child(node, "Expr"))
        self.emit("=", arg1=place, result=name)

    def _display(self, node):
        place = self._expr(self._child(node, "Expr"))
        self.emit("display", arg1=place)

    def _input(self, node):
        self.emit("read", arg1=self._ident(node))

    # ── Expressions ─────────────────────────────────────────────────────
    def _expr(self, node):
        place = self._term(self._child(node, "Term"))
        return self._exprtail(self._child(node, "ExprTail"), place)

    def _exprtail(self, node, left):
        if node is None or not node.kids:
            return left                       # ε
        op    = BIN_OPS.get(node.kids[0].name, node.kids[0].name)
        right = self._term(self._child(node, "Term"))
        t = self.new_temp()
        self.emit(op, arg1=left, arg2=right, result=t)
        return self._exprtail(self._child(node, "ExprTail"), t)

    def _term(self, node):
        place = self._factor(self._child(node, "Factor"))
        return self._termtail(self._child(node, "TermTail"), place)

    def _termtail(self, node, left):
        if node is None or not node.kids:
            return left                       # ε
        op    = BIN_OPS.get(node.kids[0].name, node.kids[0].name)
        right = self._factor(self._child(node, "Factor"))
        t = self.new_temp()
        self.emit(op, arg1=left, arg2=right, result=t)
        return self._termtail(self._child(node, "TermTail"), t)

    def _factor(self, node):
        # Factor → (( Expr )) | NUMBER | FLOAT | STRING | IDENTIFIER | yes | no
        if node is None or not node.kids:
            return "?"
        first = node.kids[0]
        if first.name == "((":
            return self._expr(self._child(node, "Expr"))
        return self._leaf_val(first)

    # ── Conditions ──────────────────────────────────────────────────────
    def _condition(self, node):
        """Evaluate a condition into a boolean temporary and return it."""
        exprs = self._children(node, "Expr")
        left  = self._expr(exprs[0]) if exprs            else "?"
        right = self._expr(exprs[1]) if len(exprs) > 1   else "?"
        relop = self._child(node, "RelOp")
        opnm  = relop.kids[0].name if (relop and relop.kids) else "?"
        op    = REL_OPS.get(opnm, opnm)
        t = self.new_temp()
        self.emit(op, arg1=left, arg2=right, result=t)
        return t

    # ── check / elif / uncheck  (if / else-if / else) ──────────────────
    def _check(self, node):
        end = self.new_label()
        cond = self._condition(self._child(node, "Condition"))
        nxt  = self.new_label()
        self.emit("ifFalse", arg1=cond, result=nxt)
        self._stmtlist(self._child(node, "StmtList"))
        self.emit("goto", result=end)
        self.emit("label", result=nxt)
        self._eliflist(self._child(node, "ElifList"), end)
        else_part = self._child(node, "ElsePart")
        if else_part and else_part.kids:
            self._stmtlist(self._child(else_part, "StmtList"))
        self.emit("label", result=end)

    def _eliflist(self, node, end):
        if node is None or not node.kids:
            return                            # ε
        cond = self._condition(self._child(node, "Condition"))
        nxt  = self.new_label()
        self.emit("ifFalse", arg1=cond, result=nxt)
        self._stmtlist(self._child(node, "StmtList"))
        self.emit("goto", result=end)
        self.emit("label", result=nxt)
        self._eliflist(self._child(node, "ElifList"), end)

    # ── Loops ───────────────────────────────────────────────────────────
    def _while(self, node):
        start, end = self.new_label(), self.new_label()
        self.emit("label", result=start)
        cond = self._condition(self._child(node, "Condition"))
        self.emit("ifFalse", arg1=cond, result=end)
        self._stmtlist(self._child(node, "StmtList"))
        self.emit("goto", result=start)
        self.emit("label", result=end)

    def _do(self, node):
        # dloop {{ StmtList }} wloop (( Condition )) Semi
        start = self.new_label()
        self.emit("label", result=start)
        self._stmtlist(self._child(node, "StmtList"))
        cond = self._condition(self._child(node, "Condition"))
        self.emit("if", arg1=cond, result=start)

    def _for(self, node):
        # floop (( ID = Expr ; Condition ; ID = Expr )) {{ StmtList }}
        idents = [c for c in node.kids if c.tok_type == "IDENTIFIER"]
        exprs  = self._children(node, "Expr")
        cond   = self._child(node, "Condition")

        if idents and exprs:                  # initialisation
            self.emit("=", arg1=self._expr(exprs[0]),
                      result=self._leaf_val(idents[0]))

        start, end = self.new_label(), self.new_label()
        self.emit("label", result=start)
        if cond:
            self.emit("ifFalse", arg1=self._condition(cond), result=end)
        self._stmtlist(self._child(node, "StmtList"))
        if len(idents) > 1 and len(exprs) > 1:  # update
            self.emit("=", arg1=self._expr(exprs[1]),
                      result=self._leaf_val(idents[1]))
        self.emit("goto", result=start)
        self.emit("label", result=end)

    # ── Return ──────────────────────────────────────────────────────────
    def _return(self, node):
        retval = self._child(node, "RetVal")
        expr   = self._child(retval, "Expr") if retval else None
        if expr:
            self.emit("return", arg1=self._expr(expr))
        else:
            self.emit("return")


# ---------------------------------------------------------------------------
# Convenience module-level helpers
# ---------------------------------------------------------------------------
def generate(root: Node):
    """Return a list of Quad instructions for the given parse tree."""
    return TACGenerator().generate(root)


def to_text(quads) -> str:
    """Join a list of Quads into a single TAC listing."""
    return "\n".join(q.to_text() for q in quads)
