ATTRIBUTES = {
    "Program":     [("code", "synthesised")],
    "StmtList":    [("code", "synthesised")],
    "Stmt":        [("code", "synthesised")],
    "DeclStmt":    [("type", "synthesised"), ("place", "synthesised")],
    "DataType":    [("type", "synthesised"), ("width", "synthesised")],
    "DeclTail":    [("type", "inherited"), ("val", "synthesised")],
    "AssignStmt":  [("code", "synthesised")],
    "DisplayStmt": [("code", "synthesised")],
    "InputStmt":   [("code", "synthesised")],
    "Condition":   [("val", "synthesised"), ("type", "synthesised")],
    "RelOp":       [("op", "synthesised")],
    # Expressions — left-recursive (S-attributed) view:
    "Expr":        [("val", "synthesised"), ("type", "synthesised")],
    "Term":        [("val", "synthesised"), ("type", "synthesised")],
    "Factor":      [("val", "synthesised"), ("type", "synthesised")],
    # Expressions — left-factored tails (L-attributed view):
    "ExprTail":    [("inh", "inherited"), ("syn", "synthesised")],
    "TermTail":    [("inh", "inherited"), ("syn", "synthesised")],
    # Terminals carry .lexval / .type from the lexer:
    "NUMBER":      [("lexval", "synthesised"), ("type", "synthesised")],
    "FLOAT":       [("lexval", "synthesised"), ("type", "synthesised")],
    "STRING":      [("lexval", "synthesised"), ("type", "synthesised")],
    "IDENTIFIER":  [("place",  "synthesised"), ("type", "inherited")],
}



S_ATTRIBUTED_SDD = [
    ("Program  → FuncList StmtList",
        ["Program.code = FuncList.code || StmtList.code"]),

    ("StmtList → StmtList1 Stmt",
        ["StmtList.code = StmtList1.code || Stmt.code"]),
    ("StmtList → Stmt",
        ["StmtList.code = Stmt.code"]),

    ("Stmt → DeclStmt | DisplayStmt | InputStmt | AssignStmt",
        ["Stmt.code = child.code"]),

    ("DeclStmt → DataType IDENTIFIER DeclTail",
        ["addtype(IDENTIFIER.entry, DataType.type)",
         "DeclStmt.type  = DataType.type",
         "DeclStmt.place = IDENTIFIER.place",
         "DeclStmt.code  = (DeclTail has Expr) ? IDENTIFIER.place ' = ' DeclTail.val : ''"]),

    ("DataType → integer",   ["DataType.type = 'integer' ; DataType.width = 2"]),
    ("DataType → decimal",   ["DataType.type = 'decimal' ; DataType.width = 4"]),
    ("DataType → word",      ["DataType.type = 'word'    ; DataType.width = 2"]),
    ("DataType → character", ["DataType.type = 'character'; DataType.width = 1"]),
    ("DataType → logic",     ["DataType.type = 'logic'   ; DataType.width = 1"]),

    ("DeclTail → equalto Expr Semi", ["DeclTail.val = Expr.val"]),
    ("DeclTail → Semi",              ["DeclTail.val = null"]),

    ("AssignStmt → IDENTIFIER equalto Expr Semi",
        ["AssignStmt.code = IDENTIFIER.place ' = ' Expr.val"]),

    ("DisplayStmt → display Expr Semi",
        ["DisplayStmt.code = 'display ' Expr.val"]),

    ("InputStmt → insrt IDENTIFIER Semi",
        ["InputStmt.code = 'read ' IDENTIFIER.place"]),

    # ---- Expressions: LEFT-RECURSIVE, purely synthesised (S-attributed) -----
    ("Expr → Expr1 plus Term",
        ["Expr.val  = Expr1.val + Term.val",
         "Expr.type = max(Expr1.type, Term.type)"]),
    ("Expr → Expr1 minus Term",
        ["Expr.val  = Expr1.val - Term.val"]),
    ("Expr → Term",
        ["Expr.val = Term.val ; Expr.type = Term.type"]),

    ("Term → Term1 mul Factor",
        ["Term.val = Term1.val * Factor.val"]),
    ("Term → Term1 div Factor",
        ["Term.val = Term1.val / Factor.val"]),
    ("Term → Factor",
        ["Term.val = Factor.val ; Term.type = Factor.type"]),

    ("Factor → (( Expr ))", ["Factor.val = Expr.val ; Factor.type = Expr.type"]),
    ("Factor → NUMBER",     ["Factor.val = NUMBER.lexval ; Factor.type = 'integer'"]),
    ("Factor → FLOAT",      ["Factor.val = FLOAT.lexval  ; Factor.type = 'decimal'"]),
    ("Factor → STRING",     ["Factor.val = STRING.lexval ; Factor.type = 'word'"]),
    ("Factor → IDENTIFIER", ["Factor.val = IDENTIFIER.place ; Factor.type = lookup(id).type"]),
    ("Factor → yes",        ["Factor.val = true  ; Factor.type = 'logic'"]),
    ("Factor → no",         ["Factor.val = false ; Factor.type = 'logic'"]),

    ("Condition → Expr1 RelOp Expr2",
        ["Condition.val  = apply(RelOp.op, Expr1.val, Expr2.val)",
         "Condition.type = 'logic'"]),

    ("RelOp → is_it | == ", ["RelOp.op = '=='"]),
    ("RelOp → is_less",     ["RelOp.op = '<'"]),
    ("RelOp → is_grtr",     ["RelOp.op = '>'"]),
    ("RelOp → less=",       ["RelOp.op = '<='"]),
    ("RelOp → grtr=",       ["RelOp.op = '>='"]),
]


L_ATTRIBUTED_SDD = [
    ("DeclStmt → DataType IDENTIFIER DeclTail",
        ["IDENTIFIER.type = DataType.type      (inherited ↓)",
         "DeclTail.type   = DataType.type      (inherited ↓)",
         "addtype(IDENTIFIER.entry, DataType.type)"]),

    ("DeclTail → equalto Expr Semi", ["DeclTail.val = Expr.val   (synthesised ↑)"]),
    ("DeclTail → Semi",              ["DeclTail.val = null"]),

    # ---- Expressions: LEFT-FACTORED, inherited value threaded through tail ---
    ("Expr → Term ExprTail",
        ["ExprTail.inh = Term.val               (inherited ↓)",
         "Expr.val     = ExprTail.syn            (synthesised ↑)"]),

    ("ExprTail → plus Term ExprTail1",
        ["ExprTail1.inh = ExprTail.inh + Term.val   (inherited ↓)",
         "ExprTail.syn  = ExprTail1.syn             (synthesised ↑)"]),
    ("ExprTail → minus Term ExprTail1",
        ["ExprTail1.inh = ExprTail.inh - Term.val",
         "ExprTail.syn  = ExprTail1.syn"]),
    ("ExprTail → ε",
        ["ExprTail.syn = ExprTail.inh            (pass inherited up)"]),

    ("Term → Factor TermTail",
        ["TermTail.inh = Factor.val              (inherited ↓)",
         "Term.val     = TermTail.syn            (synthesised ↑)"]),

    ("TermTail → mul Factor TermTail1",
        ["TermTail1.inh = TermTail.inh * Factor.val (inherited ↓)",
         "TermTail.syn  = TermTail1.syn"]),
    ("TermTail → div Factor TermTail1",
        ["TermTail1.inh = TermTail.inh / Factor.val",
         "TermTail.syn  = TermTail1.syn"]),
    ("TermTail → ε",
        ["TermTail.syn = TermTail.inh            (pass inherited up)"]),

    ("Factor → NUMBER",     ["Factor.val = NUMBER.lexval"]),
    ("Factor → (( Expr ))", ["Factor.val = Expr.val"]),
    ("Factor → IDENTIFIER", ["Factor.val = IDENTIFIER.place"]),
]


# -----------------------------------------------------------------------------
# 4. WHICH PARSER USES WHICH SDD
# -----------------------------------------------------------------------------
PARSER_APPLICABILITY = {
    "LL(1)":  "Top-down / predictive — evaluates the L-ATTRIBUTED SDD as it "
              "expands non-terminals (inherited attrs go DOWN, synthesised UP).",
    "LR(0)":  "Bottom-up / shift-reduce — evaluates the S-ATTRIBUTED SDD during "
              "each REDUCE (post-order). L-attributed also possible via an "
              "attribute stack.",
    "SLR(1)": "Bottom-up — same as LR(0): S-ATTRIBUTED SDD on reductions "
              "(FOLLOW decides the reduce).",
    "CLR(1)": "Bottom-up — same as LR(0)/SLR(1): S-ATTRIBUTED SDD on reductions "
              "(LR(1) lookahead decides the reduce).",
}


# -----------------------------------------------------------------------------
# 5. Pretty printer
# -----------------------------------------------------------------------------
def to_text() -> str:
    out = []
    out.append("=" * 70)
    out.append("  SYNTAX-DIRECTED DEFINITIONS (SDD) — Crystal grammar")
    out.append("=" * 70)

    out.append("\n[1] ATTRIBUTES  (non-terminal : attribute kind)")
    for nt, attrs in ATTRIBUTES.items():
        a = ", ".join(f"{n} ({k})" for n, k in attrs)
        out.append(f"    {nt:<12} : {a}")

    out.append("\n[2] S-ATTRIBUTED SDD  (synthesised only — LR(0) / SLR(1) / CLR(1))")
    for prod, rules in S_ATTRIBUTED_SDD:
        out.append(f"    {prod}")
        for r in rules:
            out.append(f"          {{ {r} }}")

    out.append("\n[3] L-ATTRIBUTED SDD  (inherited + synthesised — LL(1))")
    for prod, rules in L_ATTRIBUTED_SDD:
        out.append(f"    {prod}")
        for r in rules:
            out.append(f"          {{ {r} }}")

    out.append("\n[4] PARSER → SDD STYLE")
    for p, desc in PARSER_APPLICABILITY.items():
        out.append(f"    {p:<7}: {desc}")

    return "\n".join(out)


if __name__ == "__main__":
    import sys, io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    print(to_text())
