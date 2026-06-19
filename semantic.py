from parser_rules import Node



_BIN_OPS = {
    "plus": "+", "minus": "-", "mul": "*", "div": "/",
    "mode": "%", "power": "**",
}
_REL_OPS = {
    "is_it":   "==", "is_less":  "<",  "is_grtr":  ">",
    "less=":   "<=", "grtr=":    ">=",
    "is_less=":"<=", "is_grtr=": ">=",
}

def _kids_by_name(node: Node, *names):
    """Return children whose .name is in names (best-effort)."""
    return [c for c in node.kids if c.name in names]

def _first_leaf_value(node: Node) -> str | None:
    """Return value of first terminal descendant."""
    if node.is_terminal():
        return node.value
    for c in node.kids:
        v = _first_leaf_value(c)
        if v:
            return v
    return None

def _all_leaf_values(node: Node) -> list[str]:
    if node.is_terminal():
        return [node.value] if node.value else []
    result = []
    for c in node.kids:
        result.extend(_all_leaf_values(c))
    return result


class SDDEngine:
    """
    Annotates the parse tree produced by any of the Crystal parsers with:
      - node.meaning  (str)  : semantic description from SDD rules
      - node.stype    (str)  : static type  (integer / decimal / word / etc.)
      - node.sval     (str)  : synthesized value string
    """

    _HANDLERS: dict = {}

    def annotate(self, root: Node) -> Node:
        """Walk tree post-order and apply SDD rules."""
        self._visit(root)
        return root

    def _visit(self, node: Node):

        node.meaning = ""
        node.stype   = ""
        node.sval    = node.value or ""
        node.aval    = None         

        for child in node.kids:
            self._visit(child)

        handler = getattr(self, f"_sdd_{node.name}", None)
        if handler:
            handler(node)
        elif node.is_terminal():
            self._sdd_terminal(node)

        self._compute_value(node)

    def _child_any(self, node: Node, *names):
        for c in node.kids:
            if c.name in names:
                return c
        return None

    @staticmethod
    def _fmt(v):
        """Pretty-print a value (drop trailing .0 on whole floats)."""
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    def _terminal_value(self, node: Node):
        """Literal value carried by a terminal leaf, or None."""
        tt, v = node.tok_type, node.value
        if tt == "NUMBER":
            try:    return int(v)
            except (TypeError, ValueError): return v
        if tt == "FLOAT":
            try:    return float(v)
            except (TypeError, ValueError): return v
        if tt == "STRING":
            return v               
        if tt == "IDENTIFIER":
            return v                   
        if node.name == "yes":
            return True
        if node.name == "no":
            return False
        return None                      

    def _apply_op(self, op_tok, left, right):
        """Fold a binary arithmetic op; stay symbolic if not both numeric."""
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
        """Fold a relational op into yes/no when both sides are numeric."""
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
        """Walk an ExprTail / TermTail chain, folding into `left`."""
        if tail is None or not tail.kids:
            return left                                
        op_tok  = tail.kids[0].name                       
        operand = self._child_any(tail, "Term", "Factor")
        right   = operand.aval if operand else None
        folded  = self._apply_op(op_tok, left, right)
        nxt     = self._child_any(tail, "ExprTail", "TermTail")
        return self._fold_tail(folded, nxt)

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
            left  = exprs[0].aval if exprs           else None
            right = exprs[1].aval if len(exprs) > 1  else None
            node.aval = self._apply_rel(op, left, right)

        elif name == "DeclTail":
            inner = self._child_any(node, "Expr")
            node.aval = inner.aval if inner else None

        elif name in ("DeclStmt", "AssignStmt", "DisplayStmt", "RetVal", "ReturnStmt"):
            inner = self._child_any(node, "Expr", "DeclTail", "RetVal")
            node.aval = inner.aval if inner else None

        elif name == "Stmt":
            node.aval = node.kids[0].aval if node.kids else None

    def _sdd_terminal(self, node: Node):
        node.sval    = node.value or node.name
        node.meaning = f"Token: {node.tok_type or node.name} = \"{node.sval}\""
    
        if node.tok_type == "NUMBER":
            node.stype = "integer"
        elif node.tok_type == "FLOAT":
            node.stype = "decimal"
        elif node.tok_type == "STRING":
            node.stype = "word"
        elif node.tok_type == "IDENTIFIER":
            node.stype = "id"


    def _sdd_Program(self, node: Node):
        func_list = self._child(node, "FuncList")
        stmt_list = self._child(node, "StmtList")
        n_funcs = self._count_funcs(func_list) if func_list else 0
        n_stmts = self._count_stmts(stmt_list) if stmt_list else 0
        node.meaning = (
            f"Crystal Program — "
            f"{n_funcs} function(s), {n_stmts} statement(s)"
        )
        node.stype = "program"

    def _sdd_FuncList(self, node: Node):
        if not node.kids or node.kids[0].value == "ε":
            node.meaning = "No function definitions"
        else:
            node.meaning = "Function definition list"

    def _sdd_FunctionDef(self, node: Node):
    
        name = self._leaf_val(node, 1)   
        node.meaning = f"Function definition: {name}(...)"
        node.stype   = "function"
        node.sval    = name

    def _sdd_ParamList(self, node: Node):
        if not node.kids:
            node.meaning = "No parameters"
        else:
            params = self._collect_params(node)
            node.meaning = "Parameters: " + (", ".join(params) if params else "none")
            node.sval    = ", ".join(params)

    def _sdd_Param(self, node: Node):
  
        leaves = _all_leaf_values(node)
        if len(leaves) >= 2:
            node.meaning = f"Parameter: {leaves[0]} : {leaves[-1]}"
            node.stype   = leaves[-1]
            node.sval    = f"{leaves[0]}:{leaves[-1]}"

    def _sdd_ParamTail(self, node: Node):
    
        if not node.kids:
            node.meaning = "No more parameters"
            node.sval    = ""
            return
        param = self._child(node, "Param")
        tail  = self._child(node, "ParamTail")
        parts = []
        if param and param.sval:
            parts.append(param.sval)
        if tail and tail.sval:
            parts.append(tail.sval)
        node.sval    = ", ".join(parts)
        node.meaning = "More parameters: " + (node.sval or "none")

    def _sdd_StmtList(self, node: Node):
        n = self._count_stmts(node)
        node.meaning = f"{n} statement(s)"

    def _sdd_Stmt(self, node: Node):
        if node.kids:
    
            c = node.kids[0]
            node.meaning = c.meaning
            node.stype   = c.stype
            node.sval    = c.sval


    def _sdd_DeclStmt(self, node: Node):

        dtype = self._child(node, "DataType")
        ident = self._leaf_at_type(node, "IDENTIFIER")
        dtail = self._child(node, "DeclTail")

        type_str = dtype.sval  if dtype else "?"
        name_str = ident.value if ident else "?"

        if dtail and dtail.sval:
            node.meaning = (
                f"Declare variable '{name_str}' of type [{type_str}]"
                f" = {dtail.sval}"
            )
        else:
            node.meaning = f"Declare variable '{name_str}' of type [{type_str}]"
        node.stype = type_str
        node.sval  = name_str

    def _sdd_DeclTail(self, node: Node):
     
        expr = self._child(node, "Expr")
        if expr:
            node.meaning = f"Initialiser: = {expr.sval}"
            node.sval    = expr.sval
            node.stype   = expr.stype
        else:
            node.meaning = "No initialiser (declaration only)"
            node.sval    = ""

    def _sdd_DataType(self, node: Node):
        v = _first_leaf_value(node) or ""
        node.sval    = v
        node.stype   = v
        node.meaning = f"Data type: {v}"

    def _sdd_Type(self, node: Node):
        self._sdd_DataType(node)


    def _sdd_AssignStmt(self, node: Node):
     
        ident = self._leaf_at_type(node, "IDENTIFIER")
        expr  = self._child(node, "Expr")
        name  = ident.value if ident else "?"
        val   = expr.sval   if expr  else "?"
        node.meaning = f"Assign '{name}' = {val}"
        node.stype   = expr.stype if expr else ""
        node.sval    = val

   

    def _sdd_DisplayStmt(self, node: Node):
        expr = self._child(node, "Expr")
        val  = expr.sval if expr else "?"
        node.meaning = f"Output (display): {val}"
        node.sval    = val

    def _sdd_InputStmt(self, node: Node):
        ident = self._leaf_at_type(node, "IDENTIFIER")
        name  = ident.value if ident else "?"
        node.meaning = f"Read input → variable '{name}'"
        node.sval    = name



    def _sdd_CheckStmt(self, node: Node):
        cond = self._child(node, "Condition")
        cval = cond.sval if cond else "?"
        node.meaning = f"If ( {cval} ) then ... [elif/else optional]"
        node.sval    = cval

    def _sdd_ElifList(self, node: Node):
        if not node.kids:
            node.meaning = "No elif branches"
        else:
            cond = self._child(node, "Condition")
            node.meaning = f"Elif ( {cond.sval if cond else '?'} )"

    def _sdd_ElsePart(self, node: Node):
        if not node.kids:
            node.meaning = "No else branch"
        else:
            node.meaning = "Else branch"

    def _sdd_WhileLoop(self, node: Node):
        cond = self._child(node, "Condition")
        node.meaning = f"While loop: while ( {cond.sval if cond else '?'} )"

    def _sdd_ForLoop(self, node: Node):
        leaves = _all_leaf_values(node)
        node.meaning = (
            f"For loop: {leaves[0] if leaves else '?'} from ... to ..."
        )

    def _sdd_DoLoop(self, node: Node):
        cond = self._child(node, "Condition")
        node.meaning = f"Do-while loop: do {{ ... }} while ( {cond.sval if cond else '?'} )"

    def _sdd_ReturnStmt(self, node: Node):
        retval = self._child(node, "RetVal")
        val    = retval.sval if retval else ""
        node.meaning = f"Return: {val if val else 'void'}"
        node.sval    = val

    def _sdd_RetVal(self, node: Node):
        if node.kids and node.kids[0].name == "khali":
            node.meaning = "Return void (khali)"
            node.sval    = "void"
        else:
            expr = self._child(node, "Expr")
            node.sval    = expr.sval if expr else ""
            node.meaning = f"Return value: {node.sval}"


    def _sdd_Condition(self, node: Node):

        exprs  = [c for c in node.kids if c.name == "Expr"]
        relop  = self._child(node, "RelOp")
        left   = exprs[0].sval  if len(exprs) > 0 else "?"
        right  = exprs[1].sval  if len(exprs) > 1 else "?"
        op     = relop.sval     if relop            else "?"
        node.sval    = f"{left} {op} {right}"
        node.meaning = f"Condition: {left} {op} {right}"

    def _sdd_RelOp(self, node: Node):
        v = _first_leaf_value(node) or ""
        RELOP_MEANINGS = {
            "is_it":   "==",  "==":       "==",
            "is_less":  "<",  "is_grtr":  ">",
            "less=":   "<=",  "grtr=":    ">=",
            "is_less=":"<=",  "is_grtr=": ">=",
        }
        node.sval    = RELOP_MEANINGS.get(v, v)
        node.meaning = f"Relational operator: {v} → {node.sval}"


    def _sdd_Expr(self, node: Node):

        term  = self._child(node, "Term")
        tail  = self._child(node, "ExprTail")
        base  = term.sval  if term else "?"
        rest  = tail.sval  if (tail and tail.sval) else ""
        node.sval    = f"{base}{rest}".strip()
        node.stype   = term.stype if term else ""
        node.meaning = f"Expression: {node.sval}"

    def _sdd_ExprTail(self, node: Node):
        if not node.kids:
            node.sval = ""
            return
        leaves = _all_leaf_values(node)
        node.sval = " " + " ".join(leaves) if leaves else ""
        node.meaning = f"Expression tail: {node.sval.strip()}"

    def _sdd_Term(self, node: Node):
        factor = self._child(node, "Factor")
        tail   = self._child(node, "TermTail")
        base   = factor.sval if factor else "?"
        rest   = tail.sval   if (tail and tail.sval) else ""
        node.sval    = f"{base}{rest}".strip()
        node.stype   = factor.stype if factor else ""
        node.meaning = f"Term: {node.sval}"

    def _sdd_TermTail(self, node: Node):
        if not node.kids:
            node.sval = ""
            return
        leaves = _all_leaf_values(node)
        node.sval = " " + " ".join(leaves) if leaves else ""
        node.meaning = f"Term tail: {node.sval.strip()}"

    def _sdd_Factor(self, node: Node):

        if not node.kids:
            node.sval = ""
            return
        first = node.kids[0]
        if first.name == "((" :
            expr = self._child(node, "Expr")
            node.sval    = f"( {expr.sval if expr else '?'} )"
            node.stype   = expr.stype if expr else ""
            node.meaning = f"Grouped expression: {node.sval}"
        else:
            node.sval    = first.sval or first.value or first.name
            node.stype   = first.stype or first.tok_type or ""
            node.meaning = f"Factor: {node.sval} [{node.stype}]"


    def _child(self, node: Node, name: str) -> Node | None:
        for c in node.kids:
            if c.name == name:
                return c
        return None

    def _leaf_at_type(self, node: Node, tok_type: str) -> Node | None:
        """First terminal child whose tok_type matches."""
        for c in node.kids:
            if c.is_terminal() and c.tok_type == tok_type:
                return c
        return None

    def _leaf_at(self, node: Node, idx: int) -> Node | None:
        leaves = [c for c in node.kids if c.is_terminal()]
        return leaves[idx] if idx < len(leaves) else None

    def _leaf_val(self, node: Node, idx: int) -> str:
        n = self._leaf_at(node, idx)
        return n.value if n else "?"

    def _count_funcs(self, func_list: Node) -> int:
        if not func_list or not func_list.kids:
            return 0
        count = 0
        cur = func_list
        while cur and cur.kids:
            if cur.kids[0].name == "FunctionDef":
                count += 1
            if len(cur.kids) > 1 and cur.kids[1].name == "FuncList":
                cur = cur.kids[1]
            else:
                break
        return count

    def _count_stmts(self, stmt_list: Node) -> int:
        if not stmt_list or not stmt_list.kids:
            return 0
        count = 0
        cur = stmt_list
        while cur and cur.kids:
            if cur.kids[0].name == "Stmt":
                count += 1
            if len(cur.kids) > 1 and cur.kids[1].name == "StmtList":
                cur = cur.kids[1]
            else:
                break
        return count

    def _collect_params(self, param_list: Node) -> list[str]:
        result = []
        cur = param_list
        while cur and cur.kids:
            if cur.kids[0].name == "Param":
                p = cur.kids[0]
                leaves = _all_leaf_values(p)
                if leaves:
                    result.append(":".join(leaves))
            for c in cur.kids:
                if c.name == "ParamTail":
                    cur = c
                    break
            else:
                break
        return result
