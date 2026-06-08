import re


def lexer(code: str):
    # Remove block comments  /- ... -/
    code = re.sub(r'/-.*?-/', lambda m: ' ' * len(m.group()), code, flags=re.DOTALL)
    # Remove line comments  /// ...
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
        "is_it", "not",
        "is_less=", "is_less",
        "is_grtr=", "is_grtr",
        "grtr=",    "grtr",
        "less=",    "less",
    }

    delimiters = {"((", "))", "{{", "}}", "[[", "]]"}

    tokens = []
    lines  = code.split('\n')

    for line_no, line_text in enumerate(lines, start=1):
        # Tokenise one line at a time so we have accurate line numbers.
        # First, protect string literals.
        string_map = {}

        def replace_string(m):
            key = f"__STR{len(string_map)}__"
            # pad to same length so column positions stay correct
            string_map[key] = m.group(0)
            return key + ' ' * (len(m.group(0)) - len(key))

        safe_line = re.sub(r'"[^"]*"', replace_string, line_text)

        # Pad double-char delimiters
        for tok in ('((', '))', '{{', '}}', '[[', ']]'):
            safe_line = safe_line.replace(tok, f' {tok} ')

        # Find every word with its column
        for m in re.finditer(r'\S+', safe_line):
            w   = m.group()
            col = m.start() + 1          # 1-based column

            # Restore string literal
            if w.rstrip() in string_map:
                w = string_map[w.rstrip()]

            w_lower = w.lower()

            if w in string_map:
                tokens.append({
                    "type":     "STRING",
                    "value":    string_map[w],
                    "category": "STRING",
                    "line": line_no, "col": col,
                })

            elif w_lower in keywords:
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
                tokens.append({"type": "UNKNOWN", "value": w,
                                "category": "UNKNOWN", "line": line_no, "col": col})

    return tokens
