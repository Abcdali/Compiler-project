from parser_rules import GrammarEngine


def ll1_parse(tokens):
    """
    Parse a list of token-dicts (from lexer.lexer()) using LL(1).

    Returns:
        root Node  on success
        raises ValueError on parse error
    """
    engine = GrammarEngine()
    return engine.ll1_parse(tokens)

if __name__ == "__main__":
    import lexer
    code = 'integer x equalto 5 semi'
    toks = lexer.lexer(code)
    try:
        tree = ll1_parse(toks)
        print("LL(1) ACCEPT")
        print(tree)
    except ValueError as e:
        print(f"LL(1) ERROR: {e}")