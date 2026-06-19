from parser_rules import Node


_BIN = {"plus": "+", "minus": "-", "mul": "*", "div": "/", "mode": "%", "power": "**"}
_REL = {
    "is_it":   "==", "is_less":  "<",  "is_grtr":  ">",
    "less=":   "<=", "grtr=":    ">=",
    "is_less=":"<=", "is_grtr=": ">=",
}


class BPInstr:
    """One quad. Jump instructions carry a (possibly unfilled) target."""
    __slots__ = ("idx", "kind", "body", "target")

    def __init__(self, idx, kind, body, target=None):
        self.idx    = idx
        self.kind   = kind        # "code" | "cond" | "goto"
        self.body   = body        # text for "code"/"cond"
        self.target = target      # int quad index, or None (= "_")

    def _tgt(self):
        return str(self.target) if self.target is not None else "_"

    def text(self):
        if self.kind == "cond":
            return f"if {self.body} goto {self._tgt()}"
        if self.kind == "goto":
            return f"goto {self._tgt()}"
        return self.body


class BackpatchGenerator:
    def __init__(self, start=100):
        self.start  = start
        self.instrs = []
        self.log    = []
        self._t     = 0

    # ── core backpatching primitives ────────────────────────────────────
    @property
    def nextquad(self):
        return self.start + len(self.instrs)

    def emit(self, kind, body="", target=None):
        idx = self.nextquad
        self.instrs.append(BPInstr(idx, kind, body, target))
        return idx

    def _at(self, idx):
        return self.instrs[idx - self.start]

    def makelist(self, i):
        self.log.append(f"makelist({i}) = {{{i}}}")
        return [i]

    def merge(self, *lists):
        out = []
        for l in lists:
            out.extend(l)
        if len([l for l in lists if l]) > 1:
            self.log.append(f"merge → {{{', '.join(map(str, out))}}}")
        return out

    def backpatch(self, lst, target):
        if not lst:
            return
        for idx in lst:
            self._at(idx).target = target
        self.log.append(f"backpatch({{{', '.join(map(str, lst))}}}, {target})")

    def new_temp(self):
        self._t += 1
        return f"t{self._t}"

    # ── tree helpers ────────────────────────────────────────────────────
    def _child(self, node, *names):
        if node is None:
            return None
        for c in node.kids:
            if c.name in names:
                return c
        return None

    def _ident(self, node):
        for c in node.kids:
            if c.tok_type == "IDENTIFIER":
                return c.value if c.value is not None else c.name
        return "?"

    @staticmethod
    def _leaf(node):
        return node.value if node.value is not None else node.name

    # ── entry point ─────────────────────────────────────────────────────
    def generate(self, root: Node):
        prog = root
        if prog is not None and prog.name.endswith("'") and prog.kids:
            prog = prog.kids[0]
        if prog is not None:
            self._stmtlist(self._child(prog, "StmtList"))
        return self.instrs

    # ── statement lists / statements ────────────────────────────────────
    def _stmtlist(self, node):
        st = self._child(node, "Stmt")
        if st:
            self._stmt(st)
            self._stmtlist(self._child(node, "StmtList"))

    def _stmt(self, node):
        if not node.kids:
            return
        c = node.kids[0]
        {
            "DeclStmt":    self._decl,
            "AssignStmt":  self._assign,
            "DisplayStmt": self._display,
            "InputStmt":   self._input,
            "CheckStmt":   self._check,
            "WhileLoop":   self._while,
            "DoLoop":      self._do,
        }.get(c.name, lambda n: None)(c)

    def _decl(self, node):
        name  = self._ident(node)
        dtail = self._child(node, "DeclTail")
        expr  = self._child(dtail, "Expr") if dtail else None
        if expr:
            self.emit("code", f"{name} = {self._expr(expr)}")

    def _assign(self, node):
        self.emit("code", f"{self._ident(node)} = {self._expr(self._child(node, 'Expr'))}")

    def _display(self, node):
        self.emit("code", f"display {self._expr(self._child(node, 'Expr'))}")

    def _input(self, node):
        self.emit("code", f"read {self._ident(node)}")

    # ── boolean condition → (truelist, falselist) ───────────────────────
    def _bool(self, cond_node):
        exprs = [c for c in cond_node.kids if c.name == "Expr"]
        relop = self._child(cond_node, "RelOp")
        op    = _REL.get(relop.kids[0].name, "?") if (relop and relop.kids) else "?"
        left  = self._expr(exprs[0]) if exprs           else "?"
        right = self._expr(exprs[1]) if len(exprs) > 1  else "?"
        t = self.emit("cond", f"{left} {op} {right}")   # jump when true
        truelist  = self.makelist(t)
        f = self.emit("goto")                            # jump when false
        falselist = self.makelist(f)
        return truelist, falselist

    # ── check / elif / uncheck  (if / else-if / else) ──────────────────
    def _check(self, node):
        truelist, falselist = self._bool(self._child(node, "Condition"))
        m_then = self.nextquad
        self.backpatch(truelist, m_then)
        self._stmtlist(self._child(node, "StmtList"))
        goto_end = self.emit("goto")
        end_list = self.makelist(goto_end)

        # false → elif chain / else
        m_false = self.nextquad
        self.backpatch(falselist, m_false)
        end_list = self.merge(end_list, self._eliflist(self._child(node, "ElifList")))

        else_part = self._child(node, "ElsePart")
        if else_part and else_part.kids:
            self._stmtlist(self._child(else_part, "StmtList"))

        m_end = self.nextquad
        self.backpatch(end_list, m_end)

    def _eliflist(self, node):
        """Returns a list of 'goto end' quads needing backpatch to the end."""
        if node is None or not node.kids:
            return []
        truelist, falselist = self._bool(self._child(node, "Condition"))
        m_then = self.nextquad
        self.backpatch(truelist, m_then)
        self._stmtlist(self._child(node, "StmtList"))
        goto_end = self.emit("goto")
        end_list = self.makelist(goto_end)
        m_false = self.nextquad
        self.backpatch(falselist, m_false)
        return self.merge(end_list, self._eliflist(self._child(node, "ElifList")))

    # ── while ───────────────────────────────────────────────────────────
    def _while(self, node):
        m_begin = self.nextquad
        truelist, falselist = self._bool(self._child(node, "Condition"))
        m_body = self.nextquad
        self.backpatch(truelist, m_body)
        self._stmtlist(self._child(node, "StmtList"))
        self.emit("goto", target=m_begin)             # loop back (known target)
        m_after = self.nextquad
        self.backpatch(falselist, m_after)

    # ── do-while ────────────────────────────────────────────────────────
    def _do(self, node):
        m_begin = self.nextquad
        self._stmtlist(self._child(node, "StmtList"))
        truelist, falselist = self._bool(self._child(node, "Condition"))
        self.backpatch(truelist, m_begin)             # true → repeat
        m_after = self.nextquad
        self.backpatch(falselist, m_after)

    # ── arithmetic expression → operand text (emits code quads) ─────────
    def _expr(self, node):
        place = self._term(self._child(node, "Term"))
        return self._tail(self._child(node, "ExprTail"), place)

    def _tail(self, node, left):
        if node is None or not node.kids:
            return left
        op    = _BIN.get(node.kids[0].name, node.kids[0].name)
        right = self._term(self._child(node, "Term"))
        t = self.new_temp()
        self.emit("code", f"{t} = {left} {op} {right}")
        return self._tail(self._child(node, "ExprTail"), t)

    def _term(self, node):
        place = self._factor(self._child(node, "Factor"))
        return self._ttail(self._child(node, "TermTail"), place)

    def _ttail(self, node, left):
        if node is None or not node.kids:
            return left
        op    = _BIN.get(node.kids[0].name, node.kids[0].name)
        right = self._factor(self._child(node, "Factor"))
        t = self.new_temp()
        self.emit("code", f"{t} = {left} {op} {right}")
        return self._ttail(self._child(node, "TermTail"), t)

    def _factor(self, node):
        if node is None or not node.kids:
            return "?"
        first = node.kids[0]
        if first.name == "((":
            return self._expr(self._child(node, "Expr"))
        return self._leaf(first)


# =============================================================================
# Module-level helpers
# =============================================================================
def generate(root: Node):
    g = BackpatchGenerator()
    g.generate(root)
    return g


def to_text(instrs) -> str:
    return "\n".join(f"{i.idx}:  {i.text()}" for i in instrs)
