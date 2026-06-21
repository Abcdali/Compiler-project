from parser_rules import Node


_BIN_OPS = {"plus": "+", "minus": "-", "mul": "*", "div": "/",
            "mode": "%", "power": "**"}
_REL_OPS = {"is_it": "==", "is_less": "<", "is_grtr": ">",
            "less=": "<=", "grtr=": ">=", "is_less=": "<=", "is_grtr=": ">="}


def _kids_by_name(node: Node, *names):
    return [c for c in node.kids if c.name in names]


# Short human label per statement / construct (for the Semantics display).
_KIND = {
    "DeclStmt": "declare", "AssignStmt": "assign", "DisplayStmt": "display",
    "InputStmt": "read",   "CheckStmt": "if",      "ElifList": "elif",
    "ElsePart": "else",    "WhileLoop": "while",    "ForLoop": "for",
    "DoLoop": "do-while",  "ReturnStmt": "return",  "Condition": "condition",
    "FunctionDef": "function", "Expr": "expression", "Term": "term",
    "Factor": "factor",
}


class SDDEngine:
    """
    Lean S-attributed evaluator.  `annotate(root)` walks the tree post-order and
    sets, on every node:
        node.aval     synthesised VALUE (constant-folded where possible)
        node.sval     printable value string
        node.stype    inferred type
        node.meaning  short description (for the Semantics tab)
    """

    def annotate(self, root: Node) -> Node:
        self._visit(root)
        return root

    def _visit(self, node: Node):
        node.aval = None
        for child in node.kids:          # post-order: children first
            self._visit(child)
        self._compute_value(node)        # synthesise this node's value
        # display attributes (generic — derived from the value)
        node.sval    = "" if node.aval is None else self._fmt(node.aval)
        node.stype   = self._type_of(node)
        node.meaning = self._meaning(node)

    # ── tree / value helpers ────────────────────────────────────────────
    def _child_any(self, node: Node, *names):
        for c in node.kids:
            if c.name in names:
                return c
        return None

    @staticmethod
    def _fmt(v):
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    def _terminal_value(self, node: Node):
        tt, v = node.tok_type, node.value
        if tt == "NUMBER":
            try:    return int(v)
            except (TypeError, ValueError): return v
        if tt == "FLOAT":
            try:    return float(v)
            except (TypeError, ValueError): return v
        if tt in ("STRING", "IDENTIFIER"):
            return v
        if node.name == "yes":
            return True
        if node.name == "no":
            return False
        return None

    def _apply_op(self, op_tok, left, right):
        sym = _BIN_OPS.get(op_tok, op_tok)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)) \
                and not isinstance(left, bool) and not isinstance(right, bool):
            try:
                if sym == "+":  return left + right
                if sym == "-":  return left - right
                if sym == "*":  return left * right
                if sym == "/":  return left / right if right != 0 else f"({left} / {right})"
                if sym == "%":  return left % right if right != 0 else f"({left} % {right})"
                if sym == "**": return left ** right
            except Exception:
                pass
        return f"({self._fmt(left)} {sym} {self._fmt(right)})"

    def _apply_rel(self, op_tok, left, right):
        sym = _REL_OPS.get(op_tok, op_tok)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)) \
                and not isinstance(left, bool) and not isinstance(right, bool):
            try:
                if sym == "==": return left == right
                if sym == "<":  return left <  right
                if sym == ">":  return left >  right
                if sym == "<=": return left <= right
                if sym == ">=": return left >= right
            except Exception:
                pass
        return f"({self._fmt(left)} {sym} {self._fmt(right)})"

    def _fold_tail(self, left, tail: Node):
        if tail is None or not tail.kids:
            return left
        op_tok  = tail.kids[0].name
        operand = self._child_any(tail, "Term", "Factor")
        right   = operand.aval if operand else None
        folded  = self._apply_op(op_tok, left, right)
        nxt     = self._child_any(tail, "ExprTail", "TermTail")
        return self._fold_tail(folded, nxt)

    # ── the synthesised VALUE attribute (S-attributed rule application) ──
    def _compute_value(self, node: Node):
        name = node.name

        if node.is_terminal():
            node.aval = self._terminal_value(node)
            return

        if name == "Factor":
            if node.kids and node.kids[0].name == "((":
                inner = self._child_any(node, "Expr")
                node.aval = inner.aval if inner else None
            elif node.kids:
                node.aval = node.kids[0].aval

        elif name == "Term":
            base = self._child_any(node, "Factor")
            node.aval = self._fold_tail(base.aval if base else None,
                                        self._child_any(node, "TermTail"))

        elif name == "Expr":
            base = self._child_any(node, "Term")
            node.aval = self._fold_tail(base.aval if base else None,
                                        self._child_any(node, "ExprTail"))

        elif name == "Condition":
            exprs = _kids_by_name(node, "Expr")
            relop = self._child_any(node, "RelOp")
            op    = relop.kids[0].name if (relop and relop.kids) else "?"
            left  = exprs[0].aval if exprs          else None
            right = exprs[1].aval if len(exprs) > 1 else None
            node.aval = self._apply_rel(op, left, right)

        elif name == "DeclTail":
            inner = self._child_any(node, "Expr")
            node.aval = inner.aval if inner else None

        elif name in ("DeclStmt", "AssignStmt", "DisplayStmt", "RetVal", "ReturnStmt"):
            inner = self._child_any(node, "Expr", "DeclTail", "RetVal")
            node.aval = inner.aval if inner else None

        elif name == "Stmt":
            node.aval = node.kids[0].aval if node.kids else None

    # ── display-only attributes (generic, derived from the value) ───────
    def _type_of(self, node: Node) -> str:
        if node.is_terminal():
            return {"NUMBER": "integer", "FLOAT": "decimal",
                    "STRING": "word", "IDENTIFIER": "id"}.get(node.tok_type, "")
        av = node.aval
        if isinstance(av, bool):  return "logic"
        if isinstance(av, int):   return "integer"
        if isinstance(av, float): return "decimal"
        return ""

    def _meaning(self, node: Node) -> str:
        if node.is_terminal():
            if node.tok_type in ("NUMBER", "FLOAT", "STRING", "IDENTIFIER"):
                return f"{node.tok_type} = {node.value}"
            return ""
        label = _KIND.get(node.name, "")
        if node.aval is not None and node.aval != "":
            val = self._fmt(node.aval)
            return f"{label} = {val}" if label else f"= {val}"
        return label
