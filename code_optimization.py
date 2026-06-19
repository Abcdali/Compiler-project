import copy
from intermediate_code import Quad


# Ops that transfer control / are not pure assignments
JUMP_OPS   = {"goto", "if", "ifFalse", "return"}
BIN_OPS    = {"+", "-", "*", "/", "%", "**"}
REL_OPS    = {"==", "!=", "<", ">", "<=", ">="}
# Ops whose `result` field is a *label name*, NOT a defined variable
LABEL_OPS  = {"label", "goto", "if", "ifFalse", "func", "endfunc"}
# Ops that produce a value into `result`
DEF_OPS    = BIN_OPS | REL_OPS | {"="}


# =============================================================================
# Basic Block
# =============================================================================
class BasicBlock:
    def __init__(self, idx):
        self.idx     = idx          # block number  B0, B1, ...
        self.quads   = []           # list[Quad]
        self.succs   = set()        # successor block indices
        self.preds   = set()        # predecessor block indices
        self.label   = None         # leading label name (if any)

    def leader_text(self):
        return self.quads[0].to_text().strip() if self.quads else "(empty)"

    def __repr__(self):
        return f"B{self.idx}({len(self.quads)} quads)"


# =============================================================================
# Helpers
# =============================================================================
def _is_number(x):
    if x is None:
        return False
    s = str(x)
    try:
        float(s)
        return True
    except ValueError:
        return False

def _to_num(x):
    s = str(x)
    if "." in s or "e" in s or "E" in s:
        return float(s)
    return int(s)

def _num_to_str(n):
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)

def _is_temp(name):
    """t1, t2, ... are compiler-generated temporaries (safe to remove)."""
    return isinstance(name, str) and len(name) > 1 and name[0] == "t" and name[1:].isdigit()


def _quad_clone_list(quads):
    return [copy.copy(q) for q in quads]


# =============================================================================
# The Optimizer
# =============================================================================
class CodeOptimizer:
    """
    Usage:
        opt = CodeOptimizer(quads)
        result = opt.optimize()
        # result has: blocks, cfg_edges, loops, passes, original, optimized
    """

    def __init__(self, quads):
        self.original  = _quad_clone_list(quads)
        self.quads     = _quad_clone_list(quads)
        self.blocks    = []
        self.cfg_edges = []          # list of (src_idx, dst_idx, kind)
        self.loops     = []          # list of dicts describing natural loops
        self.passes    = []          # log of optimization passes (name, [changes])

    # ------------------------------------------------------------------ #
    #  Public entry point
    # ------------------------------------------------------------------ #
    def _analyze(self):
        """Build basic blocks + CFG + detect loops on the CURRENT quads."""
        self._build_basic_blocks()
        self._build_cfg()
        self._detect_loops()

    def optimize(self):
        # ── Structural analysis of the ORIGINAL code (snapshot for display) ──
        self._analyze()
        original_blocks = self.blocks
        original_edges  = self.cfg_edges
        original_loops  = copy.deepcopy(self.loops)

        # 4 — machine-independent optimizations (iterate to a fixed point)
        changed = True
        rounds  = 0
        while changed and rounds < 10:
            rounds += 1
            c0 = self._temp_copy_elimination()
            c1 = self._constant_folding()
            c2 = self._constant_propagation()
            c3 = self._copy_propagation()
            c4 = self._algebraic_simplification()
            c5 = self._common_subexpr_elimination()
            c6 = self._dead_code_elimination()
            changed = any([c0, c1, c2, c3, c4, c5, c6])

        # 5 — loop optimization (needs fresh loop info on optimized code)
        self._analyze()
        self._loop_invariant_code_motion()
        self._strength_reduction()

        # Final cleanup pass
        self._dead_code_elimination()

        # ── Re-analyse the FINAL optimized code (for display) ──
        self._analyze()

        return {
            "blocks":          self.blocks,        # optimized structure
            "cfg_edges":       self.cfg_edges,
            "loops":           self.loops,
            "orig_blocks":     original_blocks,    # original structure
            "orig_cfg_edges":  original_edges,
            "orig_loops":      original_loops,
            "passes":          self.passes,
            "original":        self.original,
            "optimized":       self.quads,
            "stats": {
                "before": len(self.original),
                "after":  len(self.quads),
                "removed": len(self.original) - len(self.quads),
            },
        }

    def _log(self, pass_name, change):
        # group changes under the same pass name
        for p in self.passes:
            if p["name"] == pass_name:
                p["changes"].append(change)
                return
        self.passes.append({"name": pass_name, "changes": [change]})

    # ================================================================== #
    #  STEP 1 — BASIC BLOCKS
    # ================================================================== #
    def _build_basic_blocks(self):
        quads = self.quads
        n = len(quads)
        if n == 0:
            self.blocks = []
            return

        # Find leaders.
        leaders = set([0])
        # Map label name → index of the label quad
        label_at = {}
        for i, q in enumerate(quads):
            if q.op == "label":
                label_at[q.result] = i
            if q.op == "func":
                leaders.add(i)

        for i, q in enumerate(quads):
            if q.op in ("goto", "if", "ifFalse"):
                # target is a leader
                tgt = q.result
                if tgt in label_at:
                    leaders.add(label_at[tgt])
                # instruction right after a jump is a leader
                if i + 1 < n:
                    leaders.add(i + 1)
            elif q.op in ("return", "endfunc"):
                if i + 1 < n:
                    leaders.add(i + 1)
            elif q.op == "label":
                leaders.add(i)

        sorted_leaders = sorted(leaders)

        # Carve blocks between consecutive leaders.
        self.blocks = []
        self._label_to_block = {}
        for bidx, start in enumerate(sorted_leaders):
            end = sorted_leaders[bidx + 1] if bidx + 1 < len(sorted_leaders) else n
            blk = BasicBlock(bidx)
            blk.quads = quads[start:end]
            if blk.quads and blk.quads[0].op == "label":
                blk.label = blk.quads[0].result
                self._label_to_block[blk.label] = bidx
            self.blocks.append(blk)

    # ================================================================== #
    #  STEP 2 — CONTROL-FLOW GRAPH  (Program Flow Graph)
    # ================================================================== #
    def _build_cfg(self):
        self.cfg_edges = []
        for blk in self.blocks:
            if not blk.quads:
                # empty block falls through
                self._add_edge(blk.idx, blk.idx + 1, "fall")
                continue
            last = blk.quads[-1]

            if last.op == "goto":
                tgt = self._label_to_block.get(last.result)
                if tgt is not None:
                    self._add_edge(blk.idx, tgt, "jump")
            elif last.op in ("if", "ifFalse"):
                # conditional: branch to target + fall through
                tgt = self._label_to_block.get(last.result)
                if tgt is not None:
                    self._add_edge(blk.idx, tgt, "branch")
                if blk.idx + 1 < len(self.blocks):
                    self._add_edge(blk.idx, blk.idx + 1, "fall")
            elif last.op in ("return", "endfunc"):
                pass  # no successor
            else:
                # ordinary block — fall through to next
                if blk.idx + 1 < len(self.blocks):
                    self._add_edge(blk.idx, blk.idx + 1, "fall")

    def _add_edge(self, src, dst, kind):
        if 0 <= src < len(self.blocks) and 0 <= dst < len(self.blocks):
            self.cfg_edges.append((src, dst, kind))
            self.blocks[src].succs.add(dst)
            self.blocks[dst].preds.add(src)

    # ================================================================== #
    #  STEP 3 — LOOP DETECTION  (dominators → back edges → natural loops)
    # ================================================================== #
    def _detect_loops(self):
        self.loops = []
        n = len(self.blocks)
        if n == 0:
            return

        # Compute dominators (iterative data-flow).
        # DOM(entry) = {entry};  DOM(n) = {n} ∪ (∩ DOM(p) for p in preds(n))
        all_nodes = set(range(n))
        dom = {b: set(all_nodes) for b in range(n)}
        dom[0] = {0}
        changed = True
        while changed:
            changed = False
            for b in range(1, n):
                preds = self.blocks[b].preds
                if not preds:
                    new = {b}
                else:
                    inter = set(all_nodes)
                    for p in preds:
                        inter &= dom[p]
                    new = {b} | inter
                if new != dom[b]:
                    dom[b] = new
                    changed = True

        # Find back edges:  edge a→b where b dominates a.
        for (src, dst, kind) in self.cfg_edges:
            if dst in dom[src]:
                # back edge  src → dst (dst is loop header)
                loop_nodes = self._natural_loop(src, dst)
                self.loops.append({
                    "header": dst,
                    "tail":   src,
                    "nodes":  sorted(loop_nodes),
                    "back_edge": (src, dst),
                })

    def _natural_loop(self, tail, header):
        """Natural loop of back edge tail→header = header + all nodes that
        reach tail without passing through header."""
        loop = {header, tail}
        stack = [tail]
        while stack:
            node = stack.pop()
            for p in self.blocks[node].preds:
                if p not in loop:
                    loop.add(p)
                    stack.append(p)
        return loop

    # ================================================================== #
    #  STEP 4a — CONSTANT FOLDING   (t = 3 + 4  →  t = 7)
    # ================================================================== #
    def _constant_folding(self):
        changed = False
        for q in self.quads:
            if q.op in BIN_OPS and _is_number(q.arg1) and _is_number(q.arg2):
                try:
                    a, b = _to_num(q.arg1), _to_num(q.arg2)
                    val = self._apply_op(q.op, a, b)
                    if val is None:
                        continue
                    before = q.to_text().strip()
                    q.op, q.arg1, q.arg2 = "=", _num_to_str(val), None
                    self._log("Constant Folding",
                              f"{before}   →   {q.to_text().strip()}")
                    changed = True
                except Exception:
                    pass
            elif q.op in REL_OPS and _is_number(q.arg1) and _is_number(q.arg2):
                a, b = _to_num(q.arg1), _to_num(q.arg2)
                val = self._apply_rel(q.op, a, b)
                before = q.to_text().strip()
                q.op, q.arg1, q.arg2 = "=", ("1" if val else "0"), None
                self._log("Constant Folding",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True
        return changed

    @staticmethod
    def _apply_op(op, a, b):
        if op == "+":  return a + b
        if op == "-":  return a - b
        if op == "*":  return a * b
        if op == "/":  return None if b == 0 else (a / b if (a % b) else a // b)
        if op == "%":  return None if b == 0 else a % b
        if op == "**": return a ** b
        return None

    @staticmethod
    def _apply_rel(op, a, b):
        return {
            "==": a == b, "!=": a != b, "<": a < b,
            ">":  a > b,  "<=": a <= b, ">=": a >= b,
        }.get(op, False)

    # ================================================================== #
    #  STEP 4b — CONSTANT PROPAGATION  (x = 5; y = x + 1 → y = 5 + 1)
    # ================================================================== #
    def _constant_propagation(self):
        changed = False
        const_env = {}     # var → constant string  (reset at labels/jumps)

        for q in self.quads:
            # Barrier: control-flow boundaries invalidate the environment.
            if q.op in ("label", "goto", "if", "ifFalse", "func", "endfunc", "return"):
                if q.op == "return" and q.arg1 in const_env:
                    q.arg1 = const_env[q.arg1]; changed = True
                if q.op in ("if", "ifFalse") and q.arg1 in const_env:
                    q.arg1 = const_env[q.arg1]; changed = True
                const_env.clear()
                continue

            # Keep 'display' referencing the variable — do NOT fold the final
            # answer into it (the program should print the variable's value,
            # not the literal constant).
            if q.op == "display":
                continue

            # Substitute known constants into args.
            if q.arg1 in const_env:
                before = q.to_text().strip()
                q.arg1 = const_env[q.arg1]
                self._log("Constant Propagation",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True
            if q.arg2 in const_env:
                before = q.to_text().strip()
                q.arg2 = const_env[q.arg2]
                self._log("Constant Propagation",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True

            # Record / kill definitions.
            if q.op == "=" and q.result is not None:
                if _is_number(q.arg1):
                    const_env[q.result] = str(q.arg1)
                else:
                    const_env.pop(q.result, None)
            elif q.op in DEF_OPS and q.result is not None:
                const_env.pop(q.result, None)
            elif q.op == "read":
                const_env.pop(q.arg1, None)

        return changed

    # ================================================================== #
    #  STEP 4b' — TEMP-COPY ELIMINATION
    #            t = a op b ; x = t   →   x = a op b      (t = single-use temp)
    #  Keeps the named RESULT variable and drops the throw-away temporary,
    #  so the result lands directly in the variable the programmer wrote.
    # ================================================================== #
    def _temp_copy_elimination(self):
        changed = False

        def uses_of(name):
            n = 0
            for q in self.quads:
                if str(q.arg1) == name:
                    n += 1
                if str(q.arg2) == name:
                    n += 1
            return n

        i = 0
        while i < len(self.quads):
            q = self.quads[i]
            # a pure copy  x = t  where t is a temporary
            if (q.op == "=" and q.result is not None
                    and q.arg1 is not None and _is_temp(str(q.arg1))):
                t = str(q.arg1)
                if uses_of(t) == 1:                       # t used only here
                    # find the (single) instruction that defines t
                    defq = None
                    for d in self.quads[:i]:
                        if d.result == t and d.op in DEF_OPS:
                            defq = d
                    if defq is not None:
                        before = f"{defq.to_text().strip()} ; {q.to_text().strip()}"
                        defq.result = q.result            # write straight into x
                        self.quads.pop(i)                 # drop the copy
                        self._log("Temp-Copy Elimination",
                                  f"{before}   →   {defq.to_text().strip()}")
                        changed = True
                        continue
            i += 1
        return changed

    # ================================================================== #
    #  STEP 4c — COPY PROPAGATION   (x = y; z = x → z = y)
    # ================================================================== #
    def _copy_propagation(self):
        changed = False
        copy_env = {}      # var → source var

        for q in self.quads:
            if q.op in ("label", "goto", "if", "ifFalse", "func", "endfunc"):
                if q.op in ("if", "ifFalse") and q.arg1 in copy_env:
                    q.arg1 = copy_env[q.arg1]; changed = True
                copy_env.clear()
                continue

            if q.op == "display":          # keep display referencing the variable
                continue

            if q.arg1 in copy_env:
                before = q.to_text().strip()
                q.arg1 = copy_env[q.arg1]
                self._log("Copy Propagation",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True
            if q.arg2 in copy_env:
                before = q.to_text().strip()
                q.arg2 = copy_env[q.arg2]
                self._log("Copy Propagation",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True

            # Kill copies whose source/dest is redefined.
            if q.result is not None and q.op not in LABEL_OPS:
                dead = [k for k, v in copy_env.items()
                        if k == q.result or v == q.result]
                for k in dead:
                    copy_env.pop(k, None)

            # Record new copy:  x = y   (y not a constant, both identifiers)
            if (q.op == "=" and q.result is not None
                    and q.arg1 is not None and not _is_number(q.arg1)):
                copy_env[q.result] = q.arg1

        return changed

    # ================================================================== #
    #  STEP 4d — ALGEBRAIC SIMPLIFICATION  (x*1→x, x+0→x, x*0→0)
    # ================================================================== #
    def _algebraic_simplification(self):
        changed = False
        for q in self.quads:
            if q.op not in BIN_OPS:
                continue
            a1, a2 = str(q.arg1), str(q.arg2)
            before = q.to_text().strip()
            new = None

            if q.op == "+" and a2 == "0":           new = ("=", q.arg1, None)
            elif q.op == "+" and a1 == "0":         new = ("=", q.arg2, None)
            elif q.op == "-" and a2 == "0":         new = ("=", q.arg1, None)
            elif q.op == "*" and a2 == "1":         new = ("=", q.arg1, None)
            elif q.op == "*" and a1 == "1":         new = ("=", q.arg2, None)
            elif q.op == "*" and (a1 == "0" or a2 == "0"):
                new = ("=", "0", None)
            elif q.op == "/" and a2 == "1":         new = ("=", q.arg1, None)
            elif q.op == "**" and a2 == "1":        new = ("=", q.arg1, None)
            elif q.op == "**" and a2 == "0":        new = ("=", "1", None)

            if new:
                q.op, q.arg1, q.arg2 = new
                self._log("Algebraic Simplification",
                          f"{before}   →   {q.to_text().strip()}")
                changed = True
        return changed

    # ================================================================== #
    #  STEP 4e — COMMON SUB-EXPRESSION ELIMINATION
    #            (t1 = a+b; t2 = a+b  →  t2 = t1)
    # ================================================================== #
    def _common_subexpr_elimination(self):
        changed = False
        avail = {}      # (op, arg1, arg2) → result var

        for q in self.quads:
            if q.op in ("label", "goto", "if", "ifFalse", "func", "endfunc"):
                avail.clear()
                continue

            # 1. Try to REUSE an already-available identical expression.
            reused  = False
            was_bin = q.op in BIN_OPS
            key = None
            if was_bin:
                key  = (q.op, str(q.arg1), str(q.arg2))
                keyc = (q.op, str(q.arg2), str(q.arg1)) if q.op in ("+", "*") else None
                src  = avail.get(key) or (avail.get(keyc) if keyc else None)
                if src is not None and src != q.result:
                    before = q.to_text().strip()
                    q.op, q.arg1, q.arg2 = "=", src, None
                    self._log("Common Sub-expression Elimination",
                              f"{before}   →   {q.to_text().strip()}  (reuse {src})")
                    changed = True
                    reused = True

            # 2. A redefinition of q.result kills expressions that used it.
            if q.result is not None and q.op not in LABEL_OPS:
                for k in [k for k in avail
                          if q.result in (k[1], k[2]) or avail[k] == q.result]:
                    avail.pop(k, None)

            # 3. Record this expression as available (after the kill, so its
            #    own entry survives).
            if was_bin and not reused and q.result is not None:
                avail[key] = q.result
        return changed

    # ================================================================== #
    #  STEP 4f — DEAD-CODE ELIMINATION
    #            (remove temp defs whose result is never used)
    # ================================================================== #
    def _dead_code_elimination(self):
        changed = False
        # Collect all uses.
        keep = True
        while keep:
            keep = False
            used = set()
            for q in self.quads:
                if q.arg1 is not None and not _is_number(q.arg1):
                    used.add(str(q.arg1))
                if q.arg2 is not None and not _is_number(q.arg2):
                    used.add(str(q.arg2))
                # if/ifFalse/return use arg1 already captured; labels use result as label
            new_quads = []
            for q in self.quads:
                # Only remove pure value-producing defs into a TEMP that's unused.
                if (q.op in DEF_OPS and q.result is not None
                        and _is_temp(q.result) and q.result not in used):
                    self._log("Dead-Code Elimination",
                              f"removed  {q.to_text().strip()}  (result '{q.result}' never used)")
                    changed = True
                    keep = True
                    continue
                new_quads.append(q)
            self.quads = new_quads
        return changed

    # ================================================================== #
    #  STEP 5a — LOOP-INVARIANT CODE MOTION
    # ================================================================== #
    def _loop_invariant_code_motion(self):
        """
        For each detected natural loop, find instructions whose operands are
        not modified anywhere inside the loop (loop-invariant) and hoist them
        to a pre-header placed just before the loop header label.
        Re-builds blocks afterwards so indices stay valid.
        """
        if not self.loops:
            return

        # Work on the flat quad list using label positions.
        for loop in self.loops:
            nodes = [b for b in loop["nodes"] if b < len(self.blocks)]
            if not nodes:
                continue
            header = loop["header"]
            if header >= len(self.blocks):
                continue

            # Gather quads inside the loop and the set of vars defined inside.
            loop_quads = []
            for b in nodes:
                loop_quads.extend(self.blocks[b].quads)
            defined_in_loop = set()
            for q in loop_quads:
                if q.result is not None and q.op not in LABEL_OPS:
                    defined_in_loop.add(str(q.result))

            # An instruction is invariant if it's a pure binary op whose
            # operands are constants or vars NOT defined inside the loop.
            invariants = []
            for q in loop_quads:
                if q.op in BIN_OPS:
                    ops_ok = all(
                        _is_number(a) or str(a) not in defined_in_loop
                        for a in (q.arg1, q.arg2)
                    )
                    # result must be defined only once in the loop
                    single_def = sum(
                        1 for x in loop_quads
                        if x.result == q.result and x.op not in LABEL_OPS
                    ) == 1
                    if ops_ok and single_def and _is_temp(str(q.result)):
                        invariants.append(q)

            if not invariants:
                continue

            # Hoist: remove from loop body, insert before header label.
            header_label = self.blocks[header].label
            if header_label is None:
                continue
            # Find header label position in flat quads.
            pos = next((i for i, q in enumerate(self.quads)
                        if q.op == "label" and q.result == header_label), None)
            if pos is None:
                continue

            remaining = [q for q in self.quads if q not in invariants]
            insert_at = next((i for i, q in enumerate(remaining)
                              if q.op == "label" and q.result == header_label), pos)
            for inv in invariants:
                self._log("Loop-Invariant Code Motion",
                          f"hoisted  {inv.to_text().strip()}  out of loop "
                          f"(header B{header})")
            self.quads = remaining[:insert_at] + invariants + remaining[insert_at:]
            self._analyze()   # refresh blocks/CFG/loops after mutation

    # ================================================================== #
    #  STEP 5b — STRENGTH REDUCTION   (x * 2  →  x + x ;  x ** 2 → x * x)
    # ================================================================== #
    def _strength_reduction(self):
        changed = False
        for q in self.quads:
            before = q.to_text().strip()
            if q.op == "*" and str(q.arg2) == "2":
                q.op, q.arg2 = "+", q.arg1
                self._log("Strength Reduction",
                          f"{before}   →   {q.to_text().strip()}  (mul→add)")
                changed = True
            elif q.op == "*" and str(q.arg1) == "2":
                q.op, q.arg1 = "+", q.arg2
                self._log("Strength Reduction",
                          f"{before}   →   {q.to_text().strip()}  (mul→add)")
                changed = True
            elif q.op == "**" and str(q.arg2) == "2":
                q.op, q.arg2 = "*", q.arg1
                self._log("Strength Reduction",
                          f"{before}   →   {q.to_text().strip()}  (pow→mul)")
                changed = True
        return changed


# =============================================================================
# Module-level convenience helpers
# =============================================================================
def optimize(quads):
    """Run the full optimization pipeline on a list of Quads."""
    return CodeOptimizer(quads).optimize()


def blocks_to_text(blocks):
    """Pretty-print basic blocks."""
    out = []
    for blk in blocks:
        succ = ", ".join(f"B{s}" for s in sorted(blk.succs)) or "-"
        out.append(f"B{blk.idx}:   (successors: {succ})")
        for q in blk.quads:
            out.append("    " + q.to_text().strip())
        out.append("")
    return "\n".join(out)


def cfg_to_text(edges):
    """Pretty-print CFG edges."""
    if not edges:
        return "(no edges)"
    return "\n".join(f"B{s}  --{kind}-->  B{d}" for (s, d, kind) in edges)


# =============================================================================
# Quick standalone test
# =============================================================================
if __name__ == "__main__":
    import sys, io
    # Make console UTF-8 safe (Windows cp1252 chokes on → arrows)
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    import lexer
    from parser_rules import GrammarEngine
    import intermediate_code as icg

    code = (
        "integer a equalto 3 plus 4 semi\n"
        "integer b equalto a mul 1 semi\n"
        "integer c equalto a plus 4 semi\n"
        "wloop (( a is_less 10 ))\n{{\n"
        "    integer d equalto b plus 5 semi\n"
        "    a equalto a plus 1 semi\n"
        "}}\n"
    )
    toks = lexer.lexer(code)
    tree = GrammarEngine().ll1_parse(toks)
    quads = icg.generate(tree)

    print("=== ORIGINAL TAC ===")
    print(icg.to_text(quads))

    res = optimize(quads)

    print("\n=== BASIC BLOCKS ===")
    print(blocks_to_text(res["blocks"]))
    print("=== CFG (PFG) ===")
    print(cfg_to_text(res["cfg_edges"]))
    print("\n=== LOOPS ===")
    for L in res["loops"]:
        print(f"  header B{L['header']}, nodes {L['nodes']}, back edge {L['back_edge']}")
    print("\n=== PASSES ===")
    for p in res["passes"]:
        print(f"  {p['name']}: {len(p['changes'])} change(s)")
        for c in p["changes"]:
            print(f"      {c}")
    print("\n=== OPTIMIZED TAC ===")
    print(icg.to_text(res["optimized"]))
    print(f"\nInstructions: {res['stats']['before']} → {res['stats']['after']} "
          f"({res['stats']['removed']} removed)")
