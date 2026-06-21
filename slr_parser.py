from parser_rules import GrammarEngine


def slr_parse(tokens):
    """
    Parse a list of token-dicts (from lexer.lexer()) using SLR(1).

    Returns:
        root Node  on success
        raises ValueError on parse error
    """
    engine = GrammarEngine()
    return engine.lr_parse(tokens, mode="SLR")


def clr_parse(tokens):
    """CLR(1) parse."""
    engine = GrammarEngine()
    return engine.lr_parse(tokens, mode="CLR")


def lr0_parse(tokens):
    """LR(0) parse."""
    engine = GrammarEngine()
    return engine.lr_parse(tokens, mode="LR0")


if __name__ == "__main__":
    import lexer
    code = 'integer x equalto 5 semi'
    toks = lexer.lexer(code)
    for mode, fn in [("SLR(1)", slr_parse), ("CLR(1)", clr_parse), ("LR(0)", lr0_parse)]:
        try:
            tree = fn(toks)
            print(f"{mode}: ACCEPT — root={tree}")
        except ValueError as e:
            print(f"{mode}: ERROR — {e}")