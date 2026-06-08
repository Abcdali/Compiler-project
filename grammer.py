# =============================================================================
# Crystal Language — Complete Grammar + First / Follow Engine
# =============================================================================

EPS = "ε"
END = "$"

# Full grammar (LL(1) — no left recursion, left-factored)
GRAMMAR = {
    "Program":     [["FuncList", "StmtList"]],

    "FuncList":    [["FunctionDef", "FuncList"],
                    [EPS]],

    "FunctionDef": [["fun", "IDENTIFIER", "((", "ParamList", "))", "{{", "StmtList", "}}"]],

    "ParamList":   [["Param", "ParamTail"],
                    [EPS]],

    "ParamTail":   [[",", "Param", "ParamTail"],
                    [EPS]],

    "Param":       [["IDENTIFIER", ":", "Type"]],

    "Type":        [["integer"], ["decimal"], ["word"], ["character"], ["logic"]],

    "StmtList":    [["Stmt", "StmtList"],
                    [EPS]],

    "Stmt":        [["DeclStmt"],
                    ["DisplayStmt"],
                    ["InputStmt"],
                    ["CheckStmt"],
                    ["WhileLoop"],
                    ["ForLoop"],
                    ["DoLoop"],
                    ["ReturnStmt"],
                    ["AssignStmt"]],

    "DeclStmt":    [["DataType", "IDENTIFIER", "DeclTail"]],

    "DeclTail":    [["equalto", "Expr", "Semi"],
                    ["Semi"]],

    "DataType":    [["integer"], ["decimal"], ["word"], ["character"], ["logic"]],

    "AssignStmt":  [["IDENTIFIER", "equalto", "Expr", "Semi"]],

    "DisplayStmt": [["display", "Expr", "Semi"]],

    "InputStmt":   [["insrt", "IDENTIFIER", "Semi"]],

    "CheckStmt":   [["check", "((", "Condition", "))", "{{", "StmtList", "}}", "ElifList", "ElsePart"]],

    "ElifList":    [["elif", "((", "Condition", "))", "{{", "StmtList", "}}", "ElifList"],
                    [EPS]],

    "ElsePart":    [["uncheck", "{{", "StmtList", "}}"],
                    [EPS]],

    "WhileLoop":   [["wloop", "((", "Condition", "))", "{{", "StmtList", "}}"]],

    "ForLoop":     [["floop", "((", "IDENTIFIER", "equalto", "Expr", "Semi",
                     "Condition", "Semi", "IDENTIFIER", "equalto", "Expr",
                     "))", "{{", "StmtList", "}}"]],

    "DoLoop":      [["dloop", "{{", "StmtList", "}}", "wloop", "((", "Condition", "))", "Semi"]],

    "ReturnStmt":  [["back", "RetVal", "Semi"]],

    "RetVal":      [["khali"],
                    ["Expr"]],

    "Condition":   [["Expr", "RelOp", "Expr"]],

    "RelOp":       [["is_it"], ["is_less"], ["is_grtr"],
                    ["less="], ["grtr="], ["is_less="], ["is_grtr="]],

    "Expr":        [["Term", "ExprTail"]],

    "ExprTail":    [["plus",  "Term", "ExprTail"],
                    ["minus", "Term", "ExprTail"],
                    [EPS]],

    "Term":        [["Factor", "TermTail"]],

    "TermTail":    [["mul",   "Factor", "TermTail"],
                    ["div",   "Factor", "TermTail"],
                    ["mode",  "Factor", "TermTail"],
                    ["power", "Factor", "TermTail"],
                    [EPS]],

    "Factor":      [["((", "Expr", "))"],
                    ["NUMBER"], ["FLOAT"], ["STRING"],
                    ["IDENTIFIER"], ["yes"], ["no"]],
}

START = "Program"
NON_TERMINALS = list(GRAMMAR.keys())
NT_SET = set(NON_TERMINALS)


# =============================================================================
# Grammar class — First + Follow sets + pretty print
# =============================================================================

class Grammar:
    """Computes FIRST and FOLLOW sets for the Crystal grammar."""

    def __init__(self, rules: dict = None, start: str = None):
        self.rules = rules if rules is not None else GRAMMAR
        self.start = start if start is not None else START
        self.nonterminals = list(self.rules.keys())
        self._nt_set = set(self.nonterminals)

        # Collect terminals automatically
        seen = set()
        terms = []
        for prods in self.rules.values():
            for prod in prods:
                for sym in prod:
                    if sym not in self._nt_set and sym != EPS and sym not in seen:
                        seen.add(sym)
                        terms.append(sym)
        self.terminals = terms

        self._first = None
        self._follow = None

    # ------------------------------------------------------------------
    def is_terminal(self, sym):
        return sym not in self._nt_set

    # ------------------------------------------------------------------
    def _first_of_seq(self, seq, first):
        """FIRST set of a sequence of grammar symbols."""
        result = set()
        if not seq or seq == [EPS]:
            return {EPS}
        for sym in seq:
            fs = first.get(sym, {sym})
            result |= (fs - {EPS})
            if EPS not in fs:
                break
        else:
            result.add(EPS)
        return result

    # ------------------------------------------------------------------
    def first_sets(self):
        """Return { NonTerminal: set_of_terminals } for FIRST."""
        if self._first:
            return self._first

        first = {nt: set() for nt in self.nonterminals}
        # Terminals map to themselves
        for t in self.terminals:
            first[t] = {t}
        first[EPS] = {EPS}

        changed = True
        while changed:
            changed = False
            for nt, prods in self.rules.items():
                for prod in prods:
                    f = self._first_of_seq(prod, first)
                    before = len(first[nt])
                    first[nt] |= f
                    if len(first[nt]) != before:
                        changed = True

        self._first = first
        return first

    # ------------------------------------------------------------------
    def follow_sets(self):
        """Return { NonTerminal: set_of_terminals } for FOLLOW."""
        if self._follow:
            return self._follow

        first = self.first_sets()
        follow = {nt: set() for nt in self.nonterminals}
        follow[self.start].add(END)

        changed = True
        while changed:
            changed = False
            for lhs, prods in self.rules.items():
                for prod in prods:
                    for i, sym in enumerate(prod):
                        if sym == EPS or self.is_terminal(sym):
                            continue
                        rest = prod[i + 1:]
                        fr = self._first_of_seq(rest, first)
                        before = len(follow[sym])
                        follow[sym] |= (fr - {EPS})
                        if EPS in fr:
                            follow[sym] |= follow[lhs]
                        if len(follow[sym]) != before:
                            changed = True

        self._follow = follow
        return follow

    # ------------------------------------------------------------------
    def print_first_follow(self):
        first  = self.first_sets()
        follow = self.follow_sets()
        w = 14
        print("FIRST sets:")
        for nt in self.nonterminals:
            print(f"  FIRST({nt:<{w}}) = {{ {', '.join(sorted(first[nt]))} }}")
        print("\nFOLLOW sets:")
        for nt in self.nonterminals:
            print(f"  FOLLOW({nt:<{w}}) = {{ {', '.join(sorted(follow[nt]))} }}")

    # ------------------------------------------------------------------
    def print_grammar(self):
        print("Grammar productions:")
        for nt, prods in self.rules.items():
            for i, prod in enumerate(prods):
                rhs = " ".join(prod) if prod != [EPS] else EPS
                arrow = "→" if i == 0 else "|"
                prefix = f"  {nt:<16}" if i == 0 else f"  {'':16}"
                print(f"{prefix} {arrow} {rhs}")
        print()


# =============================================================================
# Standalone helpers (used by ll1_parser / slr_parser)
# =============================================================================

def compute_first(rules=None):
    g = Grammar(rules)
    return g.first_sets()


def compute_follow(rules=None):
    g = Grammar(rules)
    return g.follow_sets()


# =============================================================================
# Quick test
# =============================================================================
if __name__ == "__main__":
    g = Grammar()
    g.print_grammar()
    g.print_first_follow()