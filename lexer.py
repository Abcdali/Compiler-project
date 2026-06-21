import re


def lexer(code: str):

    code = re.sub(r'/-.*?-/', lambda m: ' ' * len(m.group()), code, flags=re.DOTALL)

    code = re.sub(r'///.*', lambda m: ' ' * len(m.group()), code)

    keywords = {
        "integer", "word", "decimal", "character",
        "display", "insrt",
        "check", "uncheck", "elif",
        "wloop", "floop", "dloop",
        "logic", "yes", "no",
        "fun", "back", "snap", "resume", "toggle",
        "khali",
        "semi",
    }

    operators = {
        "equalto",
        "plus", "minus", "mul", "div", "mode", "power",
        "is_it", "==", "not",
        "is_less=", "is_less",
        "is_grtr=", "is_grtr",
        "grtr=",    "grtr",
        "less=",    "less",
        "assign",   "assign",
    }

    delimiters = {"((", "))", "{{", "}}", "[[", "]]"}

    datatype_keywords = {"integer", "word", "decimal", "character"}

    def lexical_error(word: str) -> str:
        """Return a human-readable reason why `word` is not a valid token."""
        if '"' in word:
            return "Unterminated string literal"
        if re.fullmatch(r'\d+\.\d+\.[\d.]*', word):
            return "Malformed number (too many decimal points)"
        if re.match(r'\d', word) and re.search(r'[a-zA-Z_]', word):
            return "Invalid identifier (cannot start with a digit)"
        if re.fullmatch(r'\d+\.', word) or re.fullmatch(r'\.\d+', word):
            return "Malformed number (incomplete decimal)"
        return f"Illegal token / unrecognized symbol '{word}'"

    tokens = []
    lines  = code.split('\n')
    error_found = False 

    for line_no, line_text in enumerate(lines, start=1):
        if error_found:
            break

        string_map = {}

        def replace_string(m):
            key = f"__STR{len(string_map)}__"
        
            string_map[key] = m.group(0)
            return key + ' ' * (len(m.group(0)) - len(key))

        safe_line = re.sub(r'"[^"]*"', replace_string, line_text)

      
        safe_line = safe_line.replace('==', ' == ')
     
        for tok in ('((', '))', '{{', '}}', '[[', ']]'):
            safe_line = safe_line.replace(tok, f' {tok} ')


        for m in re.finditer(r'\S+', safe_line):
            w   = m.group()
            col = m.start() + 1         

            key = w.rstrip()
            if key in string_map:
                tokens.append({
                    "type":     "STRING",
                    "value":    string_map[key],
                    "category": "STRING",
                    "line": line_no, "col": col,
                })
                continue

            w_lower = w.lower()

            if w_lower in keywords:
                tok_type = "Semi" if w_lower == "semi" else w_lower
                tokens.append({
                    "type":     tok_type,
                    "value":    w,
                    "category": "KEYWORD",
                    "line": line_no, "col": col,
                })

            elif w_lower in operators:
                tokens.append({
                    "type":     w_lower,
                    "value":    w,
                    "category": "OPERATOR",
                    "line": line_no, "col": col,
                })

            elif w in delimiters:
                tokens.append({
                    "type":     w,
                    "value":    w,
                    "category": "DELIMITER",
                    "line": line_no, "col": col,
                })

            elif re.fullmatch(r'\d+\.\d+', w):
                tokens.append({"type": "FLOAT",      "value": w,
                                "category": "NUMBER", "line": line_no, "col": col})

            elif re.fullmatch(r'\d+', w):
                tokens.append({"type": "NUMBER",     "value": w,
                                "category": "NUMBER", "line": line_no, "col": col})

            elif re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', w):
                tokens.append({"type": "IDENTIFIER", "value": w,
                                "category": "IDENTIFIER", "line": line_no, "col": col})

            elif w == ':':
                tokens.append({"type": ":", "value": w,
                                "category": "DELIMITER", "line": line_no, "col": col})

            elif w == ',':
                tokens.append({"type": ",", "value": w,
                                "category": "DELIMITER", "line": line_no, "col": col})

            else:

                tokens.append({
                    "type":     "LEX_ERROR",
                    "value":    w,
                    "category": "ERROR",
                    "error":    lexical_error(w),
                    "line": line_no, "col": col,
                })
                error_found = True
                break

    return tokens


def lexical_errors(tokens):
    """Return the list of tokens that are lexical errors."""
    return [t for t in tokens if t.get("category") == "ERROR"]


def syntax_errors(tokens):
    """
    Phase 2 — Syntax errors.

    Detects unbalanced / mismatched grouping delimiters.  Unbalanced
    '(( ))', '{{ }}' and '[[ ]]' are a SYNTAX error (they break the
    grammatical structure), not a semantic one.
    """
    pairs   = {"((": "))", "{{": "}}", "[[": "]]"}
    closers = {v: k for k, v in pairs.items()}
    stack   = []
    errors  = []

    for tok in tokens:
        v = tok.get("value")
        if v in pairs:
            stack.append(tok)
        elif v in closers:
            if not stack:
                errors.append({
                    "kind": "Syntax", "line": tok.get("line"), "col": tok.get("col"),
                    "value": v, "error": f"Unmatched closing delimiter '{v}'",
                })
            else:
                top = stack.pop()
                if pairs[top["value"]] != v:
                    errors.append({
                        "kind": "Syntax", "line": tok.get("line"), "col": tok.get("col"),
                        "value": v,
                        "error": (f"Mismatched delimiter — expected "
                                  f"'{pairs[top['value']]}' to close "
                                  f"'{top['value']}' (line {top.get('line')}), "
                                  f"found '{v}'"),
                    })

    for top in stack:
        errors.append({
            "kind": "Syntax", "line": top.get("line"), "col": top.get("col"),
            "value": top["value"],
            "error": f"Unclosed delimiter '{top['value']}' — missing '{pairs[top['value']]}'",
        })

    errors.sort(key=lambda e: (e.get("line") or 0, e.get("col") or 0))
    return errors


def semantic_errors(tokens):
    """
    Phase 3 — Semantic errors (token-level).

    Detects:
      - use of an identifier that was never declared,
      - redeclaration of an already-declared variable, and
      - TYPE MISMATCH:  assigning a value of the wrong type to a variable
        (e.g.  integer a equalto "hi" semi   or   word w equalto 5 semi).
    """
    datatype_keywords = {"integer", "word", "decimal", "character", "logic"}
    n = len(tokens)
    errors        = []
    declared      = {}      # name -> first declaration token
    declared_type = {}      # name -> its declared data type

    def is_declaration(i):
        prev = tokens[i - 1]["value"].lower() if i > 0 else ""
        nxt  = tokens[i + 1]["value"]        if i + 1 < n else ""
        return prev in datatype_keywords or prev == "fun" or nxt == ":"

    # ── Pass 1: declarations + redeclaration, remember each var's type ──
    for i, tok in enumerate(tokens):
        if tok.get("category") != "IDENTIFIER" or not is_declaration(i):
            continue
        name = tok["value"]
        prev = tokens[i - 1]["value"].lower() if i > 0 else ""
        if name in declared and prev in datatype_keywords:
            errors.append({
                "kind": "Semantic", "line": tok.get("line"), "col": tok.get("col"),
                "value": name,
                "error": (f"Redeclaration of '{name}' — already declared at line "
                          f"{declared[name].get('line')}"),
            })
        else:
            declared.setdefault(name, tok)
            if prev in datatype_keywords:
                declared_type.setdefault(name, prev)

    # ── Pass 2: use of undeclared identifier ──
    for i, tok in enumerate(tokens):
        if tok.get("category") != "IDENTIFIER" or is_declaration(i):
            continue
        name = tok["value"]
        if name not in declared:
            errors.append({
                "kind": "Semantic", "line": tok.get("line"), "col": tok.get("col"),
                "value": name,
                "error": f"Use of undeclared identifier '{name}'",
            })

    # ── Pass 3: type mismatch  (var equalto <single literal> semi) ──
    def literal_type(t):
        ty = t.get("type")
        v  = str(t.get("value", "")).lower()
        if ty == "NUMBER": return "integer"
        if ty == "FLOAT":  return "decimal"
        if ty == "STRING": return "word"
        if v in ("yes", "no"): return "logic"
        return None                        # identifier / expression — skip
    compat = {
        "integer":   {"integer"},
        "decimal":   {"integer", "decimal"},
        "word":      {"word"},
        "character": {"word"},
        "logic":     {"logic"},
    }
    for i, tok in enumerate(tokens):
        if tok.get("value") != "equalto":
            continue
        # only a SINGLE literal between 'equalto' and 'semi'
        if not (i + 2 < n and tokens[i + 2].get("type") == "Semi"):
            continue
        lit = literal_type(tokens[i + 1])
        if lit is None:
            continue
        if i - 1 < 0 or tokens[i - 1].get("category") != "IDENTIFIER":
            continue
        vname = tokens[i - 1]["value"]
        if i - 2 >= 0 and tokens[i - 2]["value"].lower() in datatype_keywords:
            dtype = tokens[i - 2]["value"].lower()      # declaration
        else:
            dtype = declared_type.get(vname)            # assignment
        if dtype and lit not in compat.get(dtype, {lit}):
            errors.append({
                "kind": "Semantic",
                "line": tokens[i + 1].get("line"), "col": tokens[i + 1].get("col"),
                "value": tokens[i + 1].get("value"),
                "error": (f"Type mismatch: cannot assign {lit} value to "
                          f"{dtype} variable '{vname}'"),
            })

    errors.sort(key=lambda e: (e.get("line") or 0, e.get("col") or 0))
    return errors


def build_symbol_table(tokens):
    """
    Build a symbol table from the token stream.

    Columns produced for each identifier:
      - name        : the identifier
      - data_type   : integer / decimal / word / character / logic, or '—'
      - scope       : 'global' (top level) or 'local (<func>)' (inside braces)
      - info        : additional info — kind (function / parameter / variable),
                      synthetic memory address, and a function's return value.

    Identifiers are returned in order of first appearance.
    """
    datatype_keywords = {"integer", "word", "decimal", "character", "logic"}
    type_size = {"integer": 4, "logic": 1, "decimal": 8,
                 "character": 1, "word": 8}

    symbols   = {}
    order     = []
    next_addr = 0x1000      

    brace_depth      = 0
    current_func     = None  
    func_brace_level = None   

    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        val = tok.get("value", "")
        low = val.lower()
        cat = tok.get("category")


        if val == "{{":
            brace_depth += 1
            i += 1
            continue
        if val == "}}":
            brace_depth -= 1
            if current_func is not None and brace_depth < func_brace_level:
                current_func = None
                func_brace_level = None
            i += 1
            continue

        if low == "back" and current_func and current_func in symbols:
            parts = []
            j = i + 1
            while j < n and tokens[j].get("value", "").lower() not in ("semi", "}}"):
                parts.append(tokens[j].get("value", ""))
                j += 1
            ret = " ".join(parts) if parts else "khali"
            symbols[current_func]["returns"] = ret
            i += 1
            continue

        if cat == "IDENTIFIER":
            prev = tokens[i - 1]["value"].lower() if i > 0 else ""
            nxt  = tokens[i + 1]["value"]        if i + 1 < n else ""
            nxt2 = tokens[i + 2]["value"].lower() if i + 2 < n else ""

            scope = "global" if brace_depth == 0 else \
                    (f"local ({current_func})" if current_func else "local")

            if prev == "fun":
                kind, dtype = "function", "—"
                scope = "global"
                current_func, func_brace_level = val, brace_depth + 1
            elif nxt == ":":
                
                kind  = "parameter"
                dtype = nxt2 if nxt2 in datatype_keywords else "—"
                if current_func:
                    scope = f"local ({current_func})"
            elif prev in datatype_keywords:
               
                kind, dtype = "variable", prev
            else:
                kind, dtype = "use", None    

            if val not in symbols:
                if kind == "function":
                    info = "function"
                    addr = None
                else:
                    addr = next_addr
                    next_addr += type_size.get(dtype, 4)
                    info = f"{kind} @ 0x{addr:04X}"
                symbols[val] = {
                    "name":      val,
                    "data_type": dtype or "—",
                    "scope":     scope,
                    "kind":      kind,
                    "addr":      addr,
                    "info":      info,
                    "returns":   None,
                    "count":     1,
                }
                order.append(val)
            else:
                e = symbols[val]
                e["count"] += 1
               
                if e["data_type"] == "—" and dtype and dtype != "—":
                    e["data_type"] = dtype
                if e["kind"] == "use" and kind != "use":
                    e["kind"] = kind

        i += 1

    result = []
    for name in order:
        e = symbols[name]
        bits = [e["info"]]
        if e.get("returns") is not None:
            bits.append(f"returns: {e['returns']}")
        if e["count"] > 1:
            bits.append(f"refs: {e['count']}")
        e["info"] = "  |  ".join(b for b in bits if b)
        result.append(e)
    return result
