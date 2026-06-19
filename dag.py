

from intermediate_code import Quad


BIN_OPS = {"+", "-", "*", "/", "%", "**"}
REL_OPS = {"==", "!=", "<", ">", "<=", ">="}

BLOCK_BREAKERS = {"label", "goto", "if", "ifFalse", "func", "endfunc", "return"}


class DAGNode:
    def __init__(self, nid, op=None, left=None, right=None, value=None):
        self.nid    = nid          # N0, N1, ...
        self.op     = op           # operator (interior node) or None (leaf)
        self.left   = left         # DAGNode | None
        self.right  = right        # DAGNode | None
        self.value  = value        # leaf literal / variable name
        self.labels = []           # variables attached to this node

    def is_leaf(self):
        return self.op is None

    def add_label(self, name):
        if name not in self.labels:
            self.labels.append(name)


class DAG:
    """A DAG for a single basic block."""

    def __init__(self, block_index, leader=""):
        self.block_index = block_index
        self.leader      = leader        # text of the first instruction (for display)
        self.nodes       = []            # all DAGNode, in creation order
        self._var_node   = {}            # variable → current DAGNode holding its value
        self._leaf_cache = {}            # literal/var → leaf DAGNode
        self._interior   = {}            # (op, left_id, right_id) → interior DAGNode

    # ── node factories ──────────────────────────────────────────────────
    def _new(self, **kw):
        node = DAGNode(f"N{len(self.nodes)}", **kw)
        self.nodes.append(node)
        return node

    def _leaf(self, name):
        """Return the node currently representing `name` (leaf if first seen)."""
        if name in self._var_node:
            return self._var_node[name]
        if name in self._leaf_cache:
            return self._leaf_cache[name]
        node = self._new(value=name)
        self._leaf_cache[name] = node
        self._var_node[name]   = node
        return node

    def _detach(self, name):
        """Remove `name` as a label from whatever node it was attached to."""
        for n in self.nodes:
            if name in n.labels:
                n.labels.remove(name)

    # ── add one three-address instruction to the DAG ────────────────────
    def add(self, q: Quad):
        op = q.op
        if op in BIN_OPS or op in REL_OPS:
            ln = self._leaf(str(q.arg1))
            rn = self._leaf(str(q.arg2))
            key = (op, ln.nid, rn.nid)
            # commutative ops can match swapped operands
            keyc = (op, rn.nid, ln.nid) if op in ("+", "*", "==", "!=") else None
            node = self._interior.get(key) or (self._interior.get(keyc) if keyc else None)
            if node is None:
                node = self._new(op=op, left=ln, right=rn)
                self._interior[key] = node
            if q.result is not None:
                self._detach(str(q.result))
                node.add_label(str(q.result))
                self._var_node[str(q.result)] = node

        elif op == "=":
            src = self._leaf(str(q.arg1))
            if q.result is not None:
                self._detach(str(q.result))
                src.add_label(str(q.result))
                self._var_node[str(q.result)] = src

    # ── stats ───────────────────────────────────────────────────────────
    def common_subexpressions(self):
        """Interior nodes whose value is held by >1 variable = shared CSEs."""
        return [n for n in self.nodes if not n.is_leaf() and len(n.labels) > 1]


# =============================================================================
# Building DAGs for a whole TAC listing (one DAG per basic block)
# =============================================================================
def build_dags(quads):
    """Split the quads into basic blocks and build one DAG per block that
    contains at least one computation.  Returns a list[DAG]."""
    # Find leaders (block boundaries), reusing the standard rules.
    n = len(quads)
    if n == 0:
        return []

    label_at = {q.result: i for i, q in enumerate(quads) if q.op == "label"}
    leaders  = {0}
    for i, q in enumerate(quads):
        if q.op in ("goto", "if", "ifFalse"):
            if q.result in label_at:
                leaders.add(label_at[q.result])
            if i + 1 < n:
                leaders.add(i + 1)
        elif q.op in ("return", "endfunc", "func"):
            leaders.add(i)
            if i + 1 < n:
                leaders.add(i + 1)
        elif q.op == "label":
            leaders.add(i)

    bounds = sorted(leaders)
    dags = []
    for bi, start in enumerate(bounds):
        end = bounds[bi + 1] if bi + 1 < len(bounds) else n
        block = quads[start:end]
        if not block:
            continue
        leader_txt = block[0].to_text().strip()
        dag = DAG(bi, leader_txt)
        has_compute = False
        for q in block:
            if q.op in BIN_OPS or q.op in REL_OPS or q.op == "=":
                dag.add(q)
                has_compute = True
        if has_compute:
            dags.append(dag)
    return dags


# =============================================================================
# Text rendering
# =============================================================================
def dag_to_text(dags) -> str:
    if not dags:
        return "(no computations to build a DAG from)"
    out = []
    for dag in dags:
        out.append(f"Basic Block B{dag.block_index}   [leader: {dag.leader}]")
        for node in dag.nodes:
            labels = ("  ←  " + ", ".join(node.labels)) if node.labels else ""
            if node.is_leaf():
                out.append(f"    {node.nid}: {node.value}{labels}   (leaf)")
            else:
                out.append(
                    f"    {node.nid}: {node.op} ({node.left.nid}, {node.right.nid})"
                    f"{labels}"
                )
        cse = dag.common_subexpressions()
        if cse:
            shared = "; ".join(f"{n.nid} held by {{{', '.join(n.labels)}}}" for n in cse)
            out.append(f"    » common sub-expressions: {shared}")
        out.append("")
    return "\n".join(out)


def build(quads):
    """Convenience: build DAGs for the given quads."""
    return build_dags(quads)
