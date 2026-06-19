from grammer import Grammar, GRAMMAR, START, EPS, END

class Node:
    def __init__(self, name, tok_type=None, value=None, line=None, col=None):
        self.name     = name      
        self.tok_type = tok_type  
        self.value    = value      
        self.line     = line     
        self.col      = col        
        self.kids     = []

    def add(self, child):
        self.kids.append(child)
        return child

    def is_terminal(self):
        return len(self.kids) == 0

    def __repr__(self):
        return f"Node({self.name!r}, kids={len(self.kids)})"

class Item:
    def __init__(self, lhs, rhs, dot=0, lookahead=None):
        self.lhs = lhs
        self.rhs = tuple(rhs)
        self.dot = dot
        self.lookahead = frozenset(lookahead or [])

    @property
    def after_dot(self):
        if self.dot < len(self.rhs):
            return self.rhs[self.dot]
        return None

    @property
    def completed(self):
        return self.dot >= len(self.rhs)

    def advance(self):
        return Item(self.lhs, self.rhs, self.dot + 1, self.lookahead)

    def core(self):
        """Item without lookahead — used for LR(0)/SLR merging."""
        return (self.lhs, self.rhs, self.dot)

    def __eq__(self, other):
        return (self.lhs, self.rhs, self.dot, self.lookahead) == \
               (other.lhs, other.rhs, other.dot, other.lookahead)

    def __hash__(self):
        return hash((self.lhs, self.rhs, self.dot, self.lookahead))

    def __repr__(self):
        rhs_str = list(self.rhs)
        rhs_str.insert(self.dot, "•")
        la = "/" + ",".join(sorted(self.lookahead)) if self.lookahead else ""
        return f"[{self.lhs} → {' '.join(rhs_str)}{la}]"


class GrammarEngine:

    _CACHE: dict = {}

    def __init__(self, rules=None, start=None):
        self.g = Grammar(rules, start)
        self.rules = self.g.rules
        self.start = self.g.start
        self._first  = None
        self._follow = None

      
        self.aug_start = self.start + "'"
      
        self._aug_prods = [(self.aug_start, [self.start])]
        for lhs, prods in self.rules.items():
            for prod in prods:
                rhs = [] if prod == [EPS] else list(prod)
                self._aug_prods.append((lhs, rhs))

  
    def first_sets(self):
        if self._first is None:
            self._first = self.g.first_sets()
        return self._first

    def follow_sets(self):
        if self._follow is None:
            self._follow = self.g.follow_sets()
        return self._follow

    def first_of_seq(self, seq):
        first = self.first_sets()
        result = set()
        for sym in seq:
            fs = first.get(sym, {sym})
            result |= (fs - {EPS})
            if EPS not in fs:
                break
        else:
            result.add(EPS)
        return result

    def _closure(self, items, mode="CLR"):
        """Compute closure of an item set."""
        closure = set(items)
        queue = list(items)
        while queue:
            item = queue.pop()
            B = item.after_dot
            if B is None or B not in self.rules:
                continue
            for prod in self.rules[B]:
                rhs = [] if prod == [EPS] else list(prod)
                if mode == "CLR":

                    beta = list(item.rhs[item.dot + 1:])
                    la = set()
                    for a in item.lookahead:
                      
                        la |= self.first_of_seq(beta + [a]) - {EPS}
                    new_item = Item(B, rhs, 0, la)
                else:
                   
                    new_item = Item(B, rhs, 0)
                if new_item not in closure:
                    closure.add(new_item)
                    queue.append(new_item)
        return frozenset(closure)

    def _goto(self, items, symbol, mode="CLR"):
        moved = {item.advance() for item in items if item.after_dot == symbol}
        return self._closure(moved, mode) if moved else frozenset()

    def build_lr0_automaton(self):
        """Returns (states_list, transitions_dict)."""
        return self._build_automaton(mode="LR0")

    def build_slr_automaton(self):
        return self._build_automaton(mode="SLR")

    def build_clr_automaton(self):
        return self._build_automaton(mode="CLR")

    def _build_automaton(self, mode):
        start_item = Item(self.aug_start, [self.start], 0,
                          {END} if mode == "CLR" else None)
        i0 = self._closure({start_item}, mode)
        states = [i0]
        state_map = {i0: 0}
        transitions = {}    
        queue = [i0]

        while queue:
            current = queue.pop(0)
            idx = state_map[current]
      
            symbols = {item.after_dot for item in current if item.after_dot}
            for sym in symbols:
                goto = self._goto(current, sym, mode)
                if not goto:
                    continue
                if goto not in state_map:
                    state_map[goto] = len(states)
                    states.append(goto)
                    queue.append(goto)
                transitions[(idx, sym)] = state_map[goto]

        return states, transitions

    def build_lr0_table(self):
        if "lr0" in GrammarEngine._CACHE:
            return GrammarEngine._CACHE["lr0"]
        states, trans = self.build_lr0_automaton()
        follow = self.follow_sets()
        ACTION = {}
        GOTO   = {}
        conflicts = []

        for i, state in enumerate(states):
            for item in state:
                sym = item.after_dot
                if sym is not None:
                    j = trans.get((i, sym))
                    if j is None:
                        continue
                    if sym in self.rules or sym == self.aug_start:
                        GOTO[(i, sym)] = j
                    else:
                        key = (i, sym)
                        entry = ("shift", j)
                        if key in ACTION and ACTION[key] != entry:
                            conflicts.append(f"LR(0) conflict at state {i} on '{sym}'")
                        ACTION[key] = entry
                else:
                  
                    if item.lhs == self.aug_start:
                        ACTION[(i, END)] = ("accept",)
                    else:
                        prod_idx = self._prod_index(item.lhs, list(item.rhs))
                        for t in follow.get(item.lhs, set()):
                            key = (i, t)
                            entry = ("reduce", item.lhs, list(item.rhs), prod_idx)
                            if key in ACTION and ACTION[key] != entry:
                                conflicts.append(f"LR(0) conflict at state {i} on '{t}'")
                            ACTION[key] = entry

        GrammarEngine._CACHE["lr0"] = (ACTION, GOTO, states, trans, conflicts)
        return ACTION, GOTO, states, trans, conflicts

    def build_slr_table(self):
        if "slr" in GrammarEngine._CACHE:
            return GrammarEngine._CACHE["slr"]
        states, trans = self.build_slr_automaton()
        follow = self.follow_sets()
        ACTION = {}
        GOTO   = {}
        conflicts = []

        for i, state in enumerate(states):
            for item in state:
                sym = item.after_dot
                if sym is not None:
                    j = trans.get((i, sym))
                    if j is None:
                        continue
                    if sym in self.rules or sym == self.aug_start:
                        GOTO[(i, sym)] = j
                    else:
                        key = (i, sym)
                        entry = ("shift", j)
                        if key in ACTION and ACTION[key] != entry:
                            conflicts.append(f"SLR conflict at state {i} on '{sym}'")
                        ACTION[key] = entry
                else:
                    if item.lhs == self.aug_start:
                        ACTION[(i, END)] = ("accept",)
                    else:
                        prod_idx = self._prod_index(item.lhs, list(item.rhs))
                        for t in follow.get(item.lhs, set()):
                            key = (i, t)
                            entry = ("reduce", item.lhs, list(item.rhs), prod_idx)
                            if key in ACTION and ACTION[key] != entry:
                                conflicts.append(f"SLR conflict at state {i} on '{t}'")
                            ACTION[key] = entry

        GrammarEngine._CACHE["slr"] = (ACTION, GOTO, states, trans, conflicts)
        return ACTION, GOTO, states, trans, conflicts

    def build_clr_table(self):
        if "clr" in GrammarEngine._CACHE:
            return GrammarEngine._CACHE["clr"]
        states, trans = self.build_clr_automaton()
        ACTION = {}
        GOTO   = {}
        conflicts = []

        for i, state in enumerate(states):
            for item in state:
                sym = item.after_dot
                if sym is not None:
                    j = trans.get((i, sym))
                    if j is None:
                        continue
                    if sym in self.rules or sym == self.aug_start:
                        GOTO[(i, sym)] = j
                    else:
                        key = (i, sym)
                        entry = ("shift", j)
                        if key in ACTION and ACTION[key] != entry:
                            conflicts.append(f"CLR conflict at state {i} on '{sym}'")
                        ACTION[key] = entry
                else:
                    if item.lhs == self.aug_start:
                        for la in item.lookahead:
                            ACTION[(i, la)] = ("accept",)
                    else:
                        prod_idx = self._prod_index(item.lhs, list(item.rhs))
                        for la in item.lookahead:
                            key = (i, la)
                            entry = ("reduce", item.lhs, list(item.rhs), prod_idx)
                            if key in ACTION and ACTION[key] != entry:
                                conflicts.append(f"CLR conflict at state {i} on '{la}'")
                            ACTION[key] = entry

        GrammarEngine._CACHE["clr"] = (ACTION, GOTO, states, trans, conflicts)
        return ACTION, GOTO, states, trans, conflicts

    def lr_parse(self, tokens, mode="SLR"):
        """
        Parse a list of token-dicts from lexer.
        Returns root Node on success, or raises ValueError on error.
        """
        tok_types = [t["type"] for t in tokens] + [END]

        if mode == "SLR":
            ACTION, GOTO, states, _, conflicts = self.build_slr_table()
        elif mode == "CLR":
            ACTION, GOTO, states, _, conflicts = self.build_clr_table()
        else:
            ACTION, GOTO, states, _, conflicts = self.build_lr0_table()

        stack_states = [0]
        stack_nodes  = []
        i = 0

        while True:
            s = stack_states[-1]
            a = tok_types[i]

            action = ACTION.get((s, a))
            if action is None:
                tok = tokens[i] if i < len(tokens) else {}
                ln  = tok.get("line", "?")
                col = tok.get("col",  "?")
                raise ValueError(
                    f"Syntax Error — line {ln}, col {col}: "
                    f"unexpected token '{tok.get('value', a)}' (type: {a})\n"
                    f"Parser state: {s}",
                    ln, col
                )

            if action[0] == "shift":
                tok = tokens[i] if i < len(tokens) else {}
                n = Node(
                    name     = tok.get("value", END),
                    tok_type = tok.get("type",  END),
                    value    = tok.get("value", END),
                    line     = tok.get("line"),
                    col      = tok.get("col"),
                )
                stack_states.append(action[1])
                stack_nodes.append(n)
                i += 1

            elif action[0] == "reduce":
                _, lhs, rhs, _ = action
                length = len(rhs)
                children = []
                for _ in range(length):
                    stack_states.pop()
                    children.insert(0, stack_nodes.pop())
                node = Node(lhs)
                node.kids = children

                node.value = " ".join(
                    c.value for c in children if c.value is not None
                ) or None
                top = stack_states[-1]
                stack_states.append(GOTO[(top, lhs)])
                stack_nodes.append(node)

            elif action[0] == "accept":
                root = Node(self.aug_start)
                root.kids = stack_nodes[:]
                root.value = " ".join(
                    c.value for c in root.kids if c.value is not None
                )
                return root

    def transition_diagrams(self):
        """
        Build a transition diagram for every non-terminal — the top-down
        equivalent of the LR item-set DFA (Dragon Book §4.4.3).

        For A → X1 X2 ... Xk a path of states is created from the start
        state to the single final state, with edges labelled X1..Xk.
        An ε-production gives a direct  start --ε--> final  edge.

        Returns: { NT: {"start": int, "final": int,
                        "states": [int...], "edges": [(src, sym, dst)...] } }
        """
        diagrams = {}
        for A, prods in self.rules.items():
            counter = [0]
            def new_state():
                counter[0] += 1
                return counter[0]
            start = 0
            final = new_state()
            states = {start, final}
            edges  = []
            for prod in prods:
                syms = [] if prod == [EPS] else list(prod)
                cur = start
                if not syms:
                    edges.append((cur, EPS, final))
                    continue
                for i, sym in enumerate(syms):
                    nxt = final if i == len(syms) - 1 else new_state()
                    states.add(nxt)
                    edges.append((cur, sym, nxt))
                    cur = nxt
            diagrams[A] = {
                "start": start, "final": final,
                "states": sorted(states), "edges": edges,
            }
        return diagrams


    def build_ll1_table(self):
        if "ll1" in GrammarEngine._CACHE:
            return GrammarEngine._CACHE["ll1"]
        first  = self.first_sets()
        follow = self.follow_sets()
        table  = {}  

        for nt, prods in self.rules.items():
            for prod in prods:
                f = self.g._first_of_seq(prod, first)
                for t in f:
                    if t != EPS:
                        key = (nt, t)
                        if key in table:
                            pass
                        table[key] = prod
                if EPS in f:
                    for t in follow.get(nt, set()):
                        key = (nt, t)
                        if key not in table:
                            table[key] = prod

        GrammarEngine._CACHE["ll1"] = table
        return table

    def ll1_parse(self, tokens):
        """
        LL(1) parse. Returns root Node or raises ValueError.
        ValueError args: (message, line, col)
        """
        table     = self.build_ll1_table()
        tok_types = [t["type"] for t in tokens] + [END]

        root  = Node(self.start)
        stack = [(END, None), (self.start, root)]
        i     = 0

        while stack:
            sym, node = stack[-1]
            look      = tok_types[i]

            if sym == END:
                if look == END:
                    
                    self._propagate(root)
                    return root
                tok = tokens[i] if i < len(tokens) else {}
                raise ValueError(
                    f"Syntax Error — line {tok.get('line','?')}, "
                    f"col {tok.get('col','?')}: "
                    f"unexpected token '{tok.get('value', look)}' after end",
                    tok.get("line"), tok.get("col")
                )

            if sym not in self.rules:
          
                if sym == look:
                    tok = tokens[i] if i < len(tokens) else {}
                    node.name     = tok.get("value", END)
                    node.tok_type = tok.get("type",  sym)
                    node.value    = tok.get("value", END)
                    node.line     = tok.get("line")
                    node.col      = tok.get("col")
                    stack.pop()
                    i += 1
                else:
                    tok = tokens[i] if i < len(tokens) else {}
                    ln  = tok.get("line", "?")
                    col = tok.get("col",  "?")
                    raise ValueError(
                        f"Syntax Error — line {ln}, col {col}: "
                        f"expected '{sym}' but got "
                        f"'{tok.get('value', look)}' (type: {look})",
                        ln, col
                    )
            else:
              
                prod = table.get((sym, look))
                if prod is None:
                    tok = tokens[i] if i < len(tokens) else {}
                    ln  = tok.get("line", "?")
                    col = tok.get("col",  "?")
                    raise ValueError(
                        f"Syntax Error — line {ln}, col {col}: "
                        f"unexpected '{tok.get('value', look)}' "
                        f"inside <{sym}>",
                        ln, col
                    )
                stack.pop()
                if prod != [EPS]:
                    child_nodes = []
                    for s in prod:
                        child = node.add(Node(s))
                        child_nodes.append((s, child))
                    for pair in reversed(child_nodes):
                        stack.append(pair)

        return root

    def _propagate(self, node: "Node"):
        """Post-order: set node.value = space-joined leaf values."""
        for child in node.kids:
            self._propagate(child)
        if not node.kids:
            return   
        node.value = " ".join(
            c.value for c in node.kids if c.value is not None
        ) or None

    def _prod_index(self, lhs, rhs):
        """Return 0-based index of (lhs, rhs) in augmented productions."""
        for idx, (l, r) in enumerate(self._aug_prods):
            if l == lhs and r == rhs:
                return idx
        return -1