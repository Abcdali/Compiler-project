# =============================================================================
# code_generation.py  —  Target Code Generation (x86 assembly)
# =============================================================================
# Phase: Code Generation  (the FINAL phase of the compiler)
#
# Takes the (optimized) Three-Address Code produced by intermediate_code.py /
# code_optimization.py and emits x86-style assembly using a simple
# accumulator model:
#
#       AX  =  the working register (accumulator)
#       every variable / temporary  →  a word in the .data section
#
# The generated text is MASM / emu8086 friendly, so it can be pasted into an
# assembler.  A built-in AssemblySimulator also executes the SAME instructions
# in Python, so the GUI can show the real program output without any external
# tool installed.
# =============================================================================

from intermediate_code import Quad


BIN_ASM = {
    "+": "ADD", "-": "SUB", "*": "MUL",
    "/": "DIV", "%": "MOD", "**": "POW",
}

# Relational op  →  the conditional-jump mnemonic that makes it TRUE
REL_JUMP = {
    "==": "JE", "!=": "JNE", "<": "JL",
    ">":  "JG", "<=": "JLE", ">=": "JGE",
}

LABEL_OPS = {"label", "goto", "if", "ifFalse", "func", "endfunc"}


def _is_number(x):
    if x is None:
        return False
    try:
        float(str(x)); return True
    except ValueError:
        return False

def _is_string(x):
    return isinstance(x, str) and len(x) >= 2 and x[0] == '"' and x[-1] == '"'


# =============================================================================
# A single assembly line (instruction / label / directive / comment / blank)
# =============================================================================
class Asm:
    __slots__ = ("kind", "mnem", "args", "label", "comment")

    def __init__(self, kind, mnem=None, args=None, label=None, comment=None):
        self.kind    = kind          # "instr" | "label" | "dir" | "comment" | "blank"
        self.mnem    = mnem
        self.args    = args or []
        self.label   = label
        self.comment = comment

    def render(self) -> str:
        if self.kind == "blank":
            return ""
        if self.kind == "comment":
            return f"; {self.comment}"
        if self.kind == "label":
            return f"{self.label}:"
        if self.kind == "dir":
            line = self.mnem + (("  " + ", ".join(self.args)) if self.args else "")
            if self.comment:
                line += f"        ; {self.comment}"
            return line
        # instruction
        line = f"    {self.mnem}"
        if self.args:
            line += "  " + ", ".join(self.args)
        if self.comment:
            line = f"{line:<28}; {self.comment}"
        return line


# =============================================================================
# Real DOS I/O procedures (emu8086 / MASM runnable)
# =============================================================================
_PROC_PRINT_INT = """; ---- print signed integer in AX as decimal + newline ----
PRINT_INT PROC
    PUSH AX
    PUSH BX
    PUSH CX
    PUSH DX
    MOV  CX, 0
    MOV  BX, 10
    CMP  AX, 0
    JGE  PI_LOOP
    MOV  DL, '-'            ; print minus for negatives
    MOV  AH, 02H
    INT  21H
    NEG  AX
PI_LOOP:
    MOV  DX, 0
    DIV  BX                 ; AX = AX/10, DX = digit
    PUSH DX
    INC  CX
    CMP  AX, 0
    JNE  PI_LOOP
PI_PRINT:
    POP  DX
    ADD  DL, '0'
    MOV  AH, 02H
    INT  21H
    LOOP PI_PRINT
    MOV  DL, 0DH            ; carriage return
    MOV  AH, 02H
    INT  21H
    MOV  DL, 0AH            ; line feed
    MOV  AH, 02H
    INT  21H
    POP  DX
    POP  CX
    POP  BX
    POP  AX
    RET
PRINT_INT ENDP"""

_PROC_PRINT_STR = """; ---- print '$'-terminated string at DS:DX + newline ----
PRINT_STR PROC
    PUSH AX
    MOV  AH, 09H
    INT  21H
    MOV  DL, 0DH
    MOV  AH, 02H
    INT  21H
    MOV  DL, 0AH
    MOV  AH, 02H
    INT  21H
    POP  AX
    RET
PRINT_STR ENDP"""

_PROC_READ_INT = """; ---- read a decimal integer from keyboard into AX ----
READ_INT PROC
    PUSH BX
    PUSH CX
    PUSH DX
    MOV  BX, 0             ; running value
    MOV  CX, 10
RI_LOOP:
    MOV  AH, 01H
    INT  21H              ; AL = typed char
    CMP  AL, 0DH          ; Enter pressed?
    JE   RI_DONE
    SUB  AL, '0'
    MOV  AH, 0
    PUSH AX
    MOV  AX, BX
    MUL  CX               ; AX = value * 10
    MOV  BX, AX
    POP  AX
    ADD  BX, AX
    JMP  RI_LOOP
RI_DONE:
    MOV  AX, BX
    POP  DX
    POP  CX
    POP  BX
    RET
READ_INT ENDP"""


# =============================================================================
# Assembly Generator
# =============================================================================
class AssemblyGenerator:
    def __init__(self):
        self.code   = []        # list[Asm]  (the .code section)
        self.vars   = []        # ordered unique variable names
        self._vseen = set()
        self.strings = {}       # label → string literal
        self._cc = 0            # counter for compare/branch helper labels
        self.use_print_int = False
        self.use_print_str = False
        self.use_read_int  = False

    # ── helpers ────────────────────────────────────────────────────────
    def _use_var(self, name):
        if name is None or _is_number(name) or _is_string(name):
            return
        name = str(name)
        if name not in self._vseen:
            self._vseen.add(name)
            self.vars.append(name)

    def _str_label(self, literal):
        for lbl, lit in self.strings.items():
            if lit == literal:
                return lbl
        lbl = f"msg{len(self.strings)}"
        self.strings[lbl] = literal
        return lbl

    def _operand(self, x):
        """Render a TAC operand as an assembly operand."""
        if _is_number(x):
            return str(x)
        return str(x)          # variable name — same text in memory model

    def _emit(self, mnem, *args, comment=None):
        self.code.append(Asm("instr", mnem, [str(a) for a in args], comment=comment))

    def _label(self, name):
        self.code.append(Asm("label", label=name))

    def _comment(self, text):
        self.code.append(Asm("comment", comment=text))

    def _blank(self):
        self.code.append(Asm("blank"))

    # ── main entry ─────────────────────────────────────────────────────
    def generate(self, quads):
        self.code, self.vars, self._vseen = [], [], set()
        self.strings, self._cc = {}, 0
        self.use_print_int = self.use_print_str = self.use_read_int = False

        for q in quads:
            self._gen_quad(q)

        self._emit("MOV", "AX", "4C00H", comment="DOS exit / program end")
        self._emit("INT", "21H")
        return self.code

    # ── per-quad translation ───────────────────────────────────────────
    def _gen_quad(self, q):
        op = q.op

        # collect variables used / defined
        for f in (q.arg1, q.arg2):
            self._use_var(f)
        if op not in LABEL_OPS:
            self._use_var(q.result)

        if op == "=":
            self._comment(f"{q.result} = {q.arg1}")
            self._emit("MOV", "AX", self._operand(q.arg1))
            self._emit("MOV", q.result, "AX")
            self._blank()

        elif op in BIN_ASM:
            self._comment(f"{q.result} = {q.arg1} {op} {q.arg2}")
            self._emit("MOV", "AX", self._operand(q.arg1))
            mnem = BIN_ASM[op]
            if mnem == "MUL":
                # 8086: MUL multiplies AX by operand → result in AX
                self._emit("MOV", "BX", self._operand(q.arg2))
                self._emit("MUL", "BX")
            elif mnem == "DIV":
                self._emit("MOV", "DX", "0")
                self._emit("MOV", "BX", self._operand(q.arg2))
                self._emit("DIV", "BX", comment="quotient in AX")
            elif mnem == "MOD":
                self._emit("MOV", "DX", "0")
                self._emit("MOV", "BX", self._operand(q.arg2))
                self._emit("DIV", "BX", comment="remainder in DX")
                self._emit("MOV", "AX", "DX")
            elif mnem == "POW":
                # pseudo-op: AX = AX ** operand  (simulator handles it)
                self._emit("POW", "AX", self._operand(q.arg2),
                           comment="exponentiation (pseudo)")
            else:  # ADD / SUB
                self._emit(mnem, "AX", self._operand(q.arg2))
            self._emit("MOV", q.result, "AX")
            self._blank()

        elif op in REL_JUMP:
            self._comment(f"{q.result} = {q.arg1} {op} {q.arg2}")
            self._cc += 1
            l_true = f"CMP_T{self._cc}"
            l_end  = f"CMP_E{self._cc}"
            self._emit("MOV", "AX", self._operand(q.arg1))
            self._emit("CMP", "AX", self._operand(q.arg2))
            self._emit(REL_JUMP[op], l_true)
            self._emit("MOV", q.result, "0")
            self._emit("JMP", l_end)
            self._label(l_true)
            self._emit("MOV", q.result, "1")
            self._label(l_end)
            self._blank()

        elif op == "ifFalse":
            self._comment(f"ifFalse {q.arg1} goto {q.result}")
            self._emit("MOV", "AX", self._operand(q.arg1))
            self._emit("CMP", "AX", "0")
            self._emit("JE", q.result, comment="branch when false (0)")
            self._blank()

        elif op == "if":
            self._comment(f"if {q.arg1} goto {q.result}")
            self._emit("MOV", "AX", self._operand(q.arg1))
            self._emit("CMP", "AX", "0")
            self._emit("JNE", q.result, comment="branch when true (!=0)")
            self._blank()

        elif op == "goto":
            self._emit("JMP", q.result)

        elif op == "label":
            self._label(q.result)

        elif op == "display":
            if _is_string(q.arg1):
                lbl = self._str_label(q.arg1)
                self._comment(f"display {q.arg1}")
                self._emit("LEA", "DX", lbl)
                self._emit("CALL", "PRINT_STR")
                self.use_print_str = True
            else:
                self._comment(f"display {q.arg1}")
                self._emit("MOV", "AX", self._operand(q.arg1))
                self._emit("CALL", "PRINT_INT")
                self.use_print_int = True
            self._blank()

        elif op == "read":
            self._comment(f"read {q.arg1}")
            self._emit("CALL", "READ_INT")
            self._emit("MOV", q.arg1, "AX")
            self._blank()
            self.use_read_int = True

        elif op == "param":
            self._comment(f"param {q.arg1}")

        elif op == "func":
            self._blank()
            self.code.append(Asm("dir", f"{q.result} PROC"))

        elif op == "endfunc":
            self.code.append(Asm("dir", f"{q.result} ENDP"))
            self._blank()

        elif op == "return":
            if q.arg1 is not None:
                self._emit("MOV", "AX", self._operand(q.arg1), comment="return value")
            self._emit("RET")

    # ── full assembly text (with .data + .code sections) ───────────────
    def to_text(self) -> str:
        lines = []
        lines.append("; ============================================")
        lines.append(";  Crystal Compiler — Generated x86 Assembly")
        lines.append(";  (MASM / emu8086 style, accumulator model)")
        lines.append("; ============================================")
        lines.append("")
        lines.append(".MODEL SMALL")
        lines.append(".STACK 100H")
        lines.append("")
        lines.append(".DATA")
        for v in self.vars:
            lines.append(f"    {v:<8} DW 0")
        for lbl, lit in self.strings.items():
            text = lit.strip('"')
            lines.append(f'    {lbl:<8} DB "{text}", "$"')
        if not self.vars and not self.strings:
            lines.append("    ; (no variables)")
        lines.append("")
        lines.append(".CODE")
        lines.append("MAIN PROC")
        lines.append("    MOV  AX, @DATA          ; initialise data segment")
        lines.append("    MOV  DS, AX")
        lines.append("")
        for a in self.code:
            lines.append(a.render())
        lines.append("MAIN ENDP")

        # Append the real DOS I/O procedures that were actually used,
        # so the listing runs unchanged in emu8086 / MASM.
        if self.use_print_int:
            lines.append("")
            lines.append(_PROC_PRINT_INT)
        if self.use_print_str:
            lines.append("")
            lines.append(_PROC_PRINT_STR)
        if self.use_read_int:
            lines.append("")
            lines.append(_PROC_READ_INT)

        lines.append("")
        lines.append("END MAIN")
        return "\n".join(lines)


# =============================================================================
# Assembly Simulator  —  executes the generated instructions in Python
# =============================================================================
class AssemblySimulator:
    """
    Runs the structured Asm list (the .code body) and returns program output.
    Supports the exact mnemonics emitted by AssemblyGenerator.
    """

    def __init__(self, code, strings, inputs=None):
        self.code    = [a for a in code if a.kind in ("instr", "label")]
        self.strings = strings
        self.inputs  = list(inputs or [])
        self.input_i = 0
        self.regs    = {"AX": 0, "BX": 0, "CX": 0, "DX": 0}
        self.mem     = {}
        self.output  = []
        self.labels  = {}
        self.trace   = []

    def _resolve(self, x):
        x = str(x)
        if x in self.regs:
            return self.regs[x]
        # hex like 4C00H
        if x.upper().endswith("H"):
            try:
                return int(x[:-1], 16)
            except ValueError:
                pass
        try:
            if "." in x:
                return float(x)
            return int(x)
        except ValueError:
            return self.mem.get(x, 0)

    def _store(self, dst, val):
        dst = str(dst)
        if dst in self.regs:
            self.regs[dst] = val
        else:
            self.mem[dst] = val

    def run(self, max_steps=100000):
        # map labels → index
        self.labels = {a.label: i for i, a in enumerate(self.code)
                       if a.kind == "label"}
        pc = 0
        steps = 0
        flag_a = flag_b = 0          # last CMP operands

        while pc < len(self.code):
            steps += 1
            if steps > max_steps:
                self.output.append("[halted: step limit reached]")
                break
            ins = self.code[pc]

            if ins.kind == "label":
                pc += 1
                continue

            m = ins.mnem
            a = ins.args

            if m == "MOV":
                self._store(a[0], self._resolve(a[1]))
            elif m == "ADD":
                self._store(a[0], self._resolve(a[0]) + self._resolve(a[1]))
            elif m == "SUB":
                self._store(a[0], self._resolve(a[0]) - self._resolve(a[1]))
            elif m == "MUL":
                self.regs["AX"] = self.regs["AX"] * self._resolve(a[0])
            elif m == "DIV":
                divisor = self._resolve(a[0])
                if divisor == 0:
                    self.output.append("[runtime error: divide by zero]")
                    break
                dividend = self.regs["AX"]
                self.regs["AX"] = int(dividend / divisor) if dividend % divisor else dividend // divisor
                self.regs["DX"] = dividend % divisor
            elif m == "POW":
                self._store(a[0], self._resolve(a[0]) ** self._resolve(a[1]))
            elif m == "CMP":
                flag_a, flag_b = self._resolve(a[0]), self._resolve(a[1])
            elif m == "JMP":
                pc = self.labels.get(a[0], pc); continue
            elif m == "JE":
                if flag_a == flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "JNE":
                if flag_a != flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "JL":
                if flag_a <  flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "JG":
                if flag_a >  flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "JLE":
                if flag_a <= flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "JGE":
                if flag_a >= flag_b: pc = self.labels.get(a[0], pc); continue
            elif m == "LEA":
                # LEA DX, msgN  — remember which string to print
                self.regs["DX"] = a[1]
            elif m == "CALL":
                target = a[0]
                if target == "PRINT_INT":
                    self.output.append(str(self.regs["AX"]))
                elif target == "PRINT_STR":
                    lbl = self.regs["DX"]
                    lit = self.strings.get(lbl, '""').strip('"')
                    self.output.append(lit)
                elif target == "READ_INT":
                    if self.input_i < len(self.inputs):
                        self.regs["AX"] = int(self.inputs[self.input_i])
                        self.input_i += 1
                    else:
                        self.regs["AX"] = 0
            elif m == "INT":
                # INT 21H after MOV AX,4C00H → program exit
                break
            elif m == "RET":
                break
            # unknown mnemonics ignored
            pc += 1

        return {
            "output": self.output,
            "registers": dict(self.regs),
            "memory": dict(self.mem),
            "steps": steps,
        }


# =============================================================================
# Module-level helpers
# =============================================================================
def generate(quads):
    """Return (asm_text, generator) for the given TAC quads."""
    gen = AssemblyGenerator()
    gen.generate(quads)
    return gen


def run(gen: AssemblyGenerator, inputs=None):
    """Execute generated assembly and return the run result dict."""
    sim = AssemblySimulator(gen.code, gen.strings, inputs=inputs)
    return sim.run()


def count_reads(quads):
    """How many 'read' inputs the program needs (for prompting)."""
    return sum(1 for q in quads if q.op == "read")


# =============================================================================
# Quick standalone test
# =============================================================================
if __name__ == "__main__":
    import sys, io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    import lexer
    from parser_rules import GrammarEngine
    import intermediate_code as icg
    import code_optimization as opt

    code = (
        "integer a equalto 5 semi\n"
        "integer b equalto 3 semi\n"
        "integer c equalto a plus b semi\n"
        "display c semi\n"
        "check (( c is_grtr 6 ))\n{{\n"
        "    display \"big\" semi\n}}\n"
    )
    toks  = lexer.lexer(code)
    tree  = GrammarEngine().ll1_parse(toks)
    quads = icg.generate(tree)
    quads = opt.optimize(quads)["optimized"]

    gen = generate(quads)
    print(gen.to_text())
    print("\n=== PROGRAM OUTPUT (simulated) ===")
    result = run(gen)
    for line in result["output"]:
        print(line)
    print("\nregisters:", result["registers"])
