"""
crystal_compiler_gui.py  —  Crystal Compiler  (PyQt6)
Buttons: Compile | Tokens | LR(0) Parse | SLR(1) | CLR(1) | LL(1) |
         FIRST | FOLLOW | Parse Tree | Open | Save
"""

import sys
from collections import Counter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTextEdit, QLabel,
    QStatusBar, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem,
    QTabWidget, QHeaderView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCursor, QTextCharFormat

import lexer as lexer_mod
from grammer import Grammar, GRAMMAR, START, EPS, END
from parser_rules import GrammarEngine, Node
from semantic import SDDEngine


# =============================================================================
# Background worker — builds LR/LL tables off the main thread
# =============================================================================
class ParserWorker(QThread):
    """
    Runs table construction + parsing in a background thread.
    Emits:
      done(mode, result_dict)   — on success
      error(mode, exc)          — on failure
    """
    done  = pyqtSignal(str, object)
    error = pyqtSignal(str, object)

    def __init__(self, mode: str, tokens: list, parent=None, inputs=None):
        super().__init__(parent)
        self.mode   = mode    # "LR0" | "SLR" | "CLR" | "LL1" | "SYNTAX" | "ICG" | "OPT" | "ASM"
        self.tokens = tokens
        self.inputs = inputs or []

    def run(self):
        try:
            engine = GrammarEngine()
            result = {}

            if self.mode == "LR0":
                ACTION, GOTO, states, trans, conflicts = engine.build_lr0_table()
                result["table"] = (ACTION, GOTO, states, conflicts)
                result["dfa"]   = (states, trans, "LR0")
                try:
                    result["tree"] = engine.lr_parse(self.tokens, mode="LR0")
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "SLR":
                ACTION, GOTO, states, trans, conflicts = engine.build_slr_table()
                result["table"] = (ACTION, GOTO, states, conflicts)
                result["dfa"]   = (states, trans, "SLR")
                try:
                    result["tree"] = engine.lr_parse(self.tokens, mode="SLR")
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "CLR":
                ACTION, GOTO, states, trans, conflicts = engine.build_clr_table()
                result["table"] = (ACTION, GOTO, states, conflicts)
                result["dfa"]   = (states, trans, "CLR")
                try:
                    result["tree"] = engine.lr_parse(self.tokens, mode="CLR")
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "LL1":
                result["ll1_table"] = engine.build_ll1_table()
                try:
                    result["tree"] = engine.ll1_parse(self.tokens)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "SYNTAX":
                result["ll1_table"] = engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    SDDEngine().annotate(tree)
                    result["tree"] = tree
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "ICG":
                # Intermediate Code Generation — parse, then emit three-address code
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    result["tac"] = icg.generate(tree)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "OPT":
                # Code Optimization — parse → TAC → optimize
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    import code_optimization as opt
                    quads = icg.generate(tree)
                    result["tac"] = quads
                    result["opt"] = opt.optimize(quads)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "ASM":
                # Target Code Generation — parse → TAC → optimize → assembly
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    import code_optimization as opt
                    import code_generation as cg
                    quads = icg.generate(tree)
                    quads = opt.optimize(quads)["optimized"]   # generate from optimized TAC
                    gen = cg.generate(quads)
                    result["asm_text"] = gen.to_text()
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "_PREWARM":
                # Build and cache all tables silently at startup
                engine.build_ll1_table()
                engine.build_lr0_table()
                engine.build_slr_table()
                engine.build_clr_table()
                result["prewarm"] = True

            self.done.emit(self.mode, result)

        except Exception as e:
            self.error.emit(self.mode, e)

# ── Category colours ──────────────────────────────────────────────────────────
CATEGORY_COLORS = {
    "KEYWORD":    ("#22d3ee", "#0e3a45"),
    "OPERATOR":   ("#f87171", "#450a0a"),
    "DELIMITER":  ("#f472b6", "#4a044e"),
    "NUMBER":     ("#facc15", "#422006"),
    "IDENTIFIER": ("#ffffff", "#1e293b"),
    "STRING":     ("#4ade80", "#052e16"),
    "UNKNOWN":    ("#6b7280", "#111827"),
    "ERROR":      ("#f87171", "#3b0f0f"),
}

DARK_BG   = "#0d1117"
PANEL_BG  = "#161b22"
BORDER    = "#30363d"
TEXT      = "#e6edf3"
MUTED     = "#8b949e"
ACCENT    = "#58a6ff"


# =============================================================================
class CrystalCompilerGUI(QMainWindow):
# =============================================================================

    def __init__(self):
        super().__init__()
        self._last_tree_root = None
        self._worker = None          # active background worker
        self._loading_dots = 0
        self.setWindowTitle("💎 Crystal Compiler")
        self.resize(1500, 860)
        self._apply_stylesheet()
        self._build_ui()
        self._connect_events()
        self.status.showMessage("Ready • Crystal Compiler Initialized")
        # Pre-warm all parser tables in background so first button click is instant
        self._prewarm_worker = ParserWorker("_PREWARM", [], parent=self)
        self._prewarm_worker.done.connect(self._on_prewarm_done)
        self._prewarm_worker.start()

    # =========================================================================
    # STYLESHEET
    # =========================================================================

    def _apply_stylesheet(self):
        self.setStyleSheet(f"""
        QMainWindow   {{ background-color: {DARK_BG}; }}
        QWidget       {{ background-color: {DARK_BG}; color: white; }}
        QLabel        {{ color: white; background: transparent; }}
        QTextEdit     {{ background-color:{PANEL_BG}; color:{TEXT};
                         border:1px solid {BORDER}; border-radius:8px;
                         padding:8px; font-family:Consolas; font-size:14px; }}
        QTreeWidget   {{ background-color:{PANEL_BG}; color:white;
                         border:1px solid {BORDER}; border-radius:8px;
                         padding:4px; font-family:Consolas; font-size:12px; }}
        QTreeWidget::item {{ padding: 2px 4px; }}
        QTreeWidget::item:hover {{ background-color:#1f2937; }}
        QTableWidget  {{ background-color:{PANEL_BG}; color:{TEXT};
                         border:1px solid {BORDER}; border-radius:8px;
                         gridline-color:{BORDER}; font-family:Consolas;
                         font-size:12px; }}
        QHeaderView::section {{ background-color:#21262d; color:white;
                                  padding:5px 8px; border:none;
                                  border-bottom:1px solid {BORDER};
                                  font-size:11px; font-weight:bold; }}
        QTabWidget::pane   {{ border:1px solid {BORDER}; border-radius:6px; }}
        QTabBar::tab       {{ background:{PANEL_BG}; color:{MUTED};
                              padding:8px 16px; border-radius:4px 4px 0 0;
                              font-size:12px; font-weight:bold; margin-right:2px; }}
        QTabBar::tab:selected {{ background:#21262d; color:white;
                                  border-bottom:2px solid {ACCENT}; }}
        QTabBar::tab:hover     {{ color:white; }}
        QPushButton {{ color:white; border-radius:8px; padding:8px 14px;
                       font-size:12px; font-weight:bold; }}
        QPushButton:hover {{ border:1px solid white; }}
        QSplitter::handle {{ background:{BORDER}; }}
        QScrollBar:vertical   {{ background:{PANEL_BG}; width:8px; }}
        QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:4px; }}
        QScrollBar:horizontal {{ background:{PANEL_BG}; height:8px; }}
        QScrollBar::handle:horizontal {{ background:{BORDER}; border-radius:4px; }}
        """)

    # =========================================================================
    # UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 6, 10, 6)
        root_layout.setSpacing(6)

        # Title bar
        title = QLabel("💎 Crystal Compiler")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:26px;font-weight:bold;color:{ACCENT};padding:4px;")
        root_layout.addWidget(title)

        subtitle = QLabel("LR(0) • SLR(1) • CLR(1) • LL(1) • Lexer • Parse Tree • Crystal Language")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color:{MUTED};font-size:11px;margin-bottom:4px;")
        root_layout.addWidget(subtitle)

        # Toolbar
        root_layout.addLayout(self._build_toolbar())

        # Main horizontal splitter: editor | right panel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.addWidget(self._build_editor_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([480, 900])
        root_layout.addWidget(splitter, 1)

        # Status bar
        self.status = QStatusBar()
        self.status.setStyleSheet(f"background-color:{PANEL_BG};color:{MUTED};")
        self.setStatusBar(self.status)

    # -------------------------------------------------------------------------
    def _build_toolbar(self):
        tb = QHBoxLayout()
        tb.setSpacing(6)

        def btn(label, color):
            b = QPushButton(label)
            b.setStyleSheet(f"background-color:{color};")
            return b

       
        self.tokens_btn  = btn("🧾 Tokens",       "#1f6feb")
        self.semantics_btn  = btn("🔍 Semantics",       "#7e22ce")
        self.lr0_btn     = btn("LR(0) Parse",     "#7c3aed")
        self.slr1_btn    = btn("SLR(1)",           "#2563eb")
        self.clr1_btn    = btn("CLR(1)",           "#0891b2")
        self.ll1_btn     = btn("LL(1)",            "#059669")
        self.first_btn   = btn("FIRST",            "#ea580c")
        self.follow_btn  = btn("FOLLOW",           "#dc2626")
        self.tree_btn    = btn("🌳 Parse Tree",    "#db6d28")
        self.open_btn    = btn("📂 Open",          "#30363d")
        self.save_btn    = btn("💾 Save",          "#30363d")
        self.compile_btn = btn("⚙ Intermediate Code Generator", "#238636")
        self.opt_btn     = btn("🚀 Code Optimization", "#be123c")
        self.asm_btn     = btn("🖥 Assembly Code", "#0f766e")

        for b in (self.tokens_btn, self.semantics_btn,
                  self.lr0_btn, self.slr1_btn, self.clr1_btn, self.ll1_btn,
                  self.first_btn, self.follow_btn, self.tree_btn,
                  self.compile_btn, self.opt_btn, self.asm_btn):
            tb.addWidget(b)
        tb.addStretch()
        tb.addWidget(self.open_btn)
        tb.addWidget(self.save_btn)
        return tb

    # -------------------------------------------------------------------------
    def _build_editor_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("📝 Crystal Source Code")
        lbl.setStyleSheet(f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;")
        layout.addWidget(lbl)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "integer age equalto 20 semi\n\n"
            "display \"Hello World\" semi\n\n"
            "check (( age is_grtr 18 ))\n{{\n    display \"Adult\" semi\n}}"
        )
        layout.addWidget(self.editor)
        return widget

    # -------------------------------------------------------------------------
    def _build_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget: Tokens | Parse Table | Parse Tree
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # ── Tab 0: Tokens ──────────────────────────────────────────────────
        tok_tab = QWidget()
        tok_layout = QVBoxLayout(tok_tab)
        tok_layout.setContentsMargins(6, 6, 6, 6)

        # Summary badges row
        self.summary_frame = QWidget()
        self.summary_frame.setStyleSheet(f"QWidget{{background-color:{DARK_BG};}}")
        self.summary_layout = QHBoxLayout(self.summary_frame)
        self.summary_layout.setContentsMargins(0, 0, 0, 4)
        self.summary_layout.setSpacing(6)
        self.summary_layout.addStretch()
        tok_layout.addWidget(self.summary_frame)

        self.token_table = self._make_table(["Category", "Type", "Value"])
        tok_layout.addWidget(self.token_table)
        self.tabs.addTab(tok_tab, "🧾 Tokens")

        # ── Tab 1: Parse Table ─────────────────────────────────────────────
        ptab_tab = QWidget()
        ptab_layout = QVBoxLayout(ptab_tab)
        ptab_layout.setContentsMargins(6, 6, 6, 6)

        self.parse_table_label = QLabel("Parse Table")
        self.parse_table_label.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;"
        )
        ptab_layout.addWidget(self.parse_table_label)

        self.parse_table_widget = QTableWidget()
        self.parse_table_widget.setStyleSheet(f"""
            QTableWidget {{ background-color:{PANEL_BG}; border:1px solid {BORDER};
                            border-radius:8px; font-family:Consolas; font-size:11px; }}
            QTableWidget::item {{ padding:3px 6px; border-bottom:1px solid #1c2128; }}
            QTableWidget::item:selected {{ background-color:#1f6feb33; }}
        """)
        self.parse_table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.parse_table_widget.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        # ── Parse table (top) + DFA (bottom) inside a vertical splitter ────
        pt_split = QSplitter(Qt.Orientation.Vertical)
        pt_split.setHandleWidth(4)
        pt_split.addWidget(self.parse_table_widget)

        dfa_container = QWidget()
        dfa_box = QVBoxLayout(dfa_container)
        dfa_box.setContentsMargins(0, 6, 0, 0)
        dfa_box.setSpacing(2)

        self.dfa_label = QLabel("🔵 DFA — Canonical Collection of LR Items")
        self.dfa_label.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:#22d3ee;padding-bottom:2px;"
        )
        dfa_box.addWidget(self.dfa_label)

        self.dfa_view = QTextEdit()
        self.dfa_view.setReadOnly(True)
        self.dfa_view.setStyleSheet(f"""
            QTextEdit {{
                background-color:#0d1117; border:1px solid {BORDER};
                border-radius:8px; padding:8px;
                font-family:Consolas,'Courier New',monospace; font-size:12px;
                color:#a5f3fc; selection-background-color:#1f3a5f;
            }}
            QScrollBar:vertical   {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        self.dfa_view.setHtml(
            '<p style="color:#6b7280;font-family:Consolas;">Run LR(0) / SLR(1) / '
            'CLR(1) to view the DFA (item-set automaton).</p>'
        )
        dfa_box.addWidget(self.dfa_view)

        pt_split.addWidget(dfa_container)
        pt_split.setStretchFactor(0, 3)
        pt_split.setStretchFactor(1, 2)
        pt_split.setSizes([420, 320])
        ptab_layout.addWidget(pt_split, 1)
        self.tabs.addTab(ptab_tab, "📊 Parse Table")

        # ── Tab 2: Parse Tree ──────────────────────────────────────────────
        tree_tab = QWidget()
        tree_layout = QVBoxLayout(tree_tab)
        tree_layout.setContentsMargins(6, 6, 6, 6)

        tree_lbl = QLabel("🌳 Derivation (Parse) Tree")
        tree_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;"
        )
        tree_layout.addWidget(tree_lbl)

        self.tree_view = QTextEdit()
        self.tree_view.setReadOnly(True)
        self.tree_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0d1117;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 10px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
                color: #a5f3fc;
                selection-background-color: #1f3a5f;
            }}
            QScrollBar:vertical {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        tree_layout.addWidget(self.tree_view)
        self.tabs.addTab(tree_tab, "🌳 Parse Tree")

        # ── Tab 3: Syntax Analysis (SDD + Annotated AST) ──────────────────
        syn_tab = QWidget()
        syn_layout = QVBoxLayout(syn_tab)
        syn_layout.setContentsMargins(6, 6, 6, 6)

        syn_lbl = QLabel("🔍 Semantics Analysis — SDD Annotated AST")
        syn_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:#c084fc;padding-bottom:4px;"
        )
        syn_layout.addWidget(syn_lbl)

        self.syntax_view = QTextEdit()
        self.syntax_view.setReadOnly(True)
        self.syntax_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: #0d1117;
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 10px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
                color: #e2e8f0;
                selection-background-color: #1f3a5f;
            }}
            QScrollBar:vertical   {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        syn_layout.addWidget(self.syntax_view)
        self.tabs.addTab(syn_tab, "🔍 Semantics")

        # ── Tab 4: Symbol Table ────────────────────────────────────────────
        sym_tab = QWidget()
        sym_layout = QVBoxLayout(sym_tab)
        sym_layout.setContentsMargins(6, 6, 6, 6)

        sym_lbl = QLabel("🔣 Symbol Table — Identifiers")
        sym_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;"
        )
        sym_layout.addWidget(sym_lbl)

        self.symbol_table = self._make_table(
            ["Name", "Data Type", "Scope", "Additional Info"]
        )
        sym_layout.addWidget(self.symbol_table)
        self.tabs.addTab(sym_tab, "🔣 Symbol Table")

        # ── Tab 5: Lexical Errors ──────────────────────────────────────────
        err_tab = QWidget()
        err_layout = QVBoxLayout(err_tab)
        err_layout.setContentsMargins(6, 6, 6, 6)

        err_lbl = QLabel("⚠ Errors — Lexical • Syntax • Semantic")
        err_lbl.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#f87171;padding-bottom:4px;"
        )
        err_layout.addWidget(err_lbl)

        self.error_table = self._make_table(
            ["Phase", "Line", "Col", "Value", "Description"]
        )
        err_layout.addWidget(self.error_table)
        self.tabs.addTab(err_tab, "⚠ Errors")

        # ── Tab 6: Intermediate Code (Three-Address Code) ──────────────────
        self.icg_tab = QWidget()
        icg_layout = QVBoxLayout(self.icg_tab)
        icg_layout.setContentsMargins(6, 6, 6, 6)

        self.icg_label = QLabel("⚙ Intermediate Code — Three-Address Code")
        self.icg_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#238636;padding-bottom:4px;"
        )
        icg_layout.addWidget(self.icg_label)

        icg_split = QSplitter(Qt.Orientation.Vertical)
        icg_split.setHandleWidth(4)

        # TAC listing (text) on top
        self.tac_view = QTextEdit()
        self.tac_view.setReadOnly(True)
        self.tac_view.setStyleSheet(f"""
            QTextEdit {{
                background-color:#0d1117; border:1px solid {BORDER};
                border-radius:8px; padding:10px;
                font-family:Consolas,'Courier New',monospace; font-size:13px;
                color:#a5f3fc; selection-background-color:#1f3a5f;
            }}
            QScrollBar:vertical   {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        self.tac_view.setHtml(
            '<p style="color:#6b7280;font-family:Consolas;">Click '
            '“⚙ Intermediate Code Generator” to produce three-address code.</p>'
        )
        icg_split.addWidget(self.tac_view)

        # Quadruple table on the bottom
        quad_container = QWidget()
        quad_box = QVBoxLayout(quad_container)
        quad_box.setContentsMargins(0, 6, 0, 0)
        quad_box.setSpacing(2)
        quad_lbl = QLabel("Quadruples")
        quad_lbl.setStyleSheet("color:#8b949e;font-size:11px;font-weight:bold;")
        quad_box.addWidget(quad_lbl)
        self.quad_table = self._make_table(["#", "op", "arg1", "arg2", "result"])
        quad_box.addWidget(self.quad_table)
        icg_split.addWidget(quad_container)

        icg_split.setStretchFactor(0, 3)
        icg_split.setStretchFactor(1, 2)
        icg_split.setSizes([420, 300])
        icg_layout.addWidget(icg_split, 1)
        self.tabs.addTab(self.icg_tab, "⚙ Intermediate Code")

        # ── Tab 7: Code Optimization ────────────────────────────────────────
        self.opt_tab = QWidget()
        opt_layout = QVBoxLayout(self.opt_tab)
        opt_layout.setContentsMargins(6, 6, 6, 6)

        self.opt_label = QLabel("🚀 Code Optimization — Machine-Independent")
        self.opt_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#fb7185;padding-bottom:4px;"
        )
        opt_layout.addWidget(self.opt_label)

        self.opt_view = QTextEdit()
        self.opt_view.setReadOnly(True)
        self.opt_view.setStyleSheet(f"""
            QTextEdit {{
                background-color:#0d1117; border:1px solid {BORDER};
                border-radius:8px; padding:10px;
                font-family:Consolas,'Courier New',monospace; font-size:13px;
                color:#e2e8f0; selection-background-color:#1f3a5f;
            }}
            QScrollBar:vertical   {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        self.opt_view.setHtml(
            '<p style="color:#6b7280;font-family:Consolas;">Click '
            '“🚀 Code Optimization” to build basic blocks, the control-flow '
            'graph (PFG), detect loops, and apply machine-independent '
            'optimizations.</p>'
        )
        opt_layout.addWidget(self.opt_view, 1)
        self.tabs.addTab(self.opt_tab, "🚀 Optimization")

        # ── Tab 8: Assembly / Target Code ───────────────────────────────────
        self.asm_tab = QWidget()
        asm_layout = QVBoxLayout(self.asm_tab)
        asm_layout.setContentsMargins(6, 6, 6, 6)

        # Header row: title + Save .asm button
        asm_head = QHBoxLayout()
        self.asm_label = QLabel("🖥 Assembly Code — x86 (MASM / emu8086)")
        self.asm_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#2dd4bf;padding-bottom:4px;"
        )
        asm_head.addWidget(self.asm_label)
        asm_head.addStretch()
        self.save_asm_btn = QPushButton("💾 Save .asm")
        self.save_asm_btn.setStyleSheet("background-color:#30363d;color:white;"
                                        "border-radius:6px;padding:3px 10px;font-size:11px;")
        asm_head.addWidget(self.save_asm_btn)
        asm_layout.addLayout(asm_head)

        # Assembly listing (full height — no output panel)
        self.asm_view = QTextEdit()
        self.asm_view.setReadOnly(True)
        self.asm_view.setStyleSheet(f"""
            QTextEdit {{
                background-color:#0d1117; border:1px solid {BORDER};
                border-radius:8px; padding:10px;
                font-family:Consolas,'Courier New',monospace; font-size:13px;
                color:#5eead4; selection-background-color:#1f3a5f;
            }}
            QScrollBar:vertical   {{ background:#161b22; width:8px; border-radius:4px; }}
            QScrollBar::handle:vertical {{ background:#30363d; border-radius:4px; }}
            QScrollBar:horizontal {{ background:#161b22; height:8px; border-radius:4px; }}
            QScrollBar::handle:horizontal {{ background:#30363d; border-radius:4px; }}
        """)
        self.asm_view.setHtml(
            '<p style="color:#6b7280;font-family:Consolas;">Click '
            '“🖥 Assembly Code” to generate x86 assembly.</p>'
        )
        asm_layout.addWidget(self.asm_view, 1)
        self.tabs.addTab(self.asm_tab, "🖥 Assembly")

        self._last_asm_text = ""    # for the Save .asm button

        layout.addWidget(self.tabs)
        return widget

    def _make_table(self, headers):
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setStyleSheet(f"""
            QTableWidget {{ background-color:{DARK_BG}; border:1px solid {BORDER};
                            border-radius:8px; font-family:Consolas; font-size:12px; }}
            QTableWidget::item {{ padding:4px 8px; border-bottom:1px solid #1c2128; }}
            QTableWidget::item:selected {{ background-color:#1f6feb33; }}
        """)
        return t

    # =========================================================================
    # EVENT WIRING
    # =========================================================================

    def _connect_events(self):
        self.open_btn.clicked.connect(self.open_file)
        self.save_btn.clicked.connect(self.save_file)
        self.tokens_btn.clicked.connect(self.load_tokens)
        self.semantics_btn.clicked.connect(self.run_syntax)
        self.lr0_btn.clicked.connect(self.run_lr0)
        self.slr1_btn.clicked.connect(self.run_slr)
        self.clr1_btn.clicked.connect(self.run_clr)
        self.ll1_btn.clicked.connect(self.run_ll1)
        self.first_btn.clicked.connect(self.run_first)
        self.follow_btn.clicked.connect(self.run_follow)
        self.tree_btn.clicked.connect(self.show_current_tree)
        self.compile_btn.clicked.connect(self.run_icg)
        self.opt_btn.clicked.connect(self.run_opt)
        self.asm_btn.clicked.connect(self.run_asm)
        self.save_asm_btn.clicked.connect(self.save_assembly)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _get_tokens(self):
        return lexer_mod.lexer(self.editor.toPlainText())

    def _get_engine(self):
        return GrammarEngine()

    # =========================================================================
    # LR PARSE TABLE DISPLAY
    # =========================================================================

    def _show_lr_table(self, ACTION, GOTO, states, conflicts, title):
        """Render ACTION/GOTO table — fast sparse fill, updates disabled during load."""
        terminals    = sorted({a for (_, a) in ACTION.keys()})
        nonterminals = sorted({nt for (_, nt) in GOTO.keys()})
        all_cols     = terminals + nonterminals
        n_states     = len(states)
        terminal_set = set(terminals)

        tw = self.parse_table_widget

        # ── Freeze all rendering while we fill ────────────────────────────
        tw.setUpdatesEnabled(False)
        tw.setSortingEnabled(False)
        tw.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        tw.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        tw.clearContents()
        tw.setRowCount(n_states)
        tw.setColumnCount(len(all_cols))
        tw.setHorizontalHeaderLabels(all_cols)
        tw.setVerticalHeaderLabels([f"I{i}" for i in range(n_states)])
        tw.verticalHeader().setVisible(True)
        tw.verticalHeader().setStyleSheet(
            "QHeaderView::section { background:#21262d; color:#f472b6;"
            " padding:4px; border:none; border-right:1px solid #30363d;"
            " font-family:Consolas; font-size:11px; }"
        )

        # Pre-build colour objects once
        c_shift  = (QColor("#22d3ee"), QColor("#0e3a45"))
        c_reduce = (QColor("#f472b6"), QColor("#2d0b2e"))
        c_accept = (QColor("#4ade80"), QColor("#052e16"))
        c_goto   = (QColor("#facc15"), QColor("#422006"))
        align    = Qt.AlignmentFlag.AlignCenter
        bold_font = QFont("Consolas", 11)
        bold_font.setBold(True)

        # ── Only create items where cells are non-empty (sparse) ──────────
        for (state_idx, sym), entry in ACTION.items():
            if state_idx >= n_states:
                continue
            col = all_cols.index(sym) if sym in all_cols else -1
            if col < 0:
                continue
            if entry[0] == "shift":
                text, fg, bg = f"S{entry[1]}", *c_shift
            elif entry[0] == "reduce":
                rhs_str = " ".join(entry[2]) if entry[2] else "e"
                text, fg, bg = f"R:{entry[1]}", *c_reduce
            elif entry[0] == "accept":
                text, fg, bg = "ACC", *c_accept
            else:
                continue
            item = QTableWidgetItem(text)
            item.setForeground(fg); item.setBackground(bg)
            item.setTextAlignment(align)
            if text == "ACC":
                item.setFont(bold_font)
            tw.setItem(state_idx, col, item)

        for (state_idx, sym), dest in GOTO.items():
            if state_idx >= n_states:
                continue
            col = all_cols.index(sym) if sym in all_cols else -1
            if col < 0:
                continue
            item = QTableWidgetItem(str(dest))
            item.setForeground(c_goto[0]); item.setBackground(c_goto[1])
            item.setTextAlignment(align)
            tw.setItem(state_idx, col, item)

        # ── Unfreeze and resize only filled columns ────────────────────────
        tw.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        tw.setUpdatesEnabled(True)

        conflict_info = f"  {len(conflicts)} conflict(s)" if conflicts else "  no conflicts"
        self.parse_table_label.setText(
            f"{title} Parse Table — {n_states} states —{conflict_info}"
        )
        self.tabs.setCurrentIndex(1)

    # =========================================================================
    # DFA DISPLAY  (canonical collection of LR item sets + transitions)
    # =========================================================================

    def _clear_dfa(self, title=""):
        """LL(1) has no DFA — show an explanatory note."""
        self.dfa_label.setText("🔵 DFA — Canonical Collection of LR Items")
        msg = (f"{title} is a top-down (predictive) parser — it has no LR "
               "item-set automaton.<br>Run LR(0) / SLR(1) / CLR(1) to view the DFA.")
        self.dfa_view.setHtml(
            f'<p style="color:#6b7280;font-family:Consolas;font-size:12px;">{msg}</p>'
        )

    def _format_item(self, item, show_lookahead: bool) -> str:
        """Render one LR item as 'LHS → α • β   , lookahead'."""
        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        rhs = list(item.rhs)
        rhs.insert(item.dot, "•")
        body = " ".join(rhs) if rhs else "•"

        html = (f'<span style="color:#67e8f9;font-weight:bold;">{esc(item.lhs)}</span>'
                f'<span style="color:#475569;"> → </span>')
        parts = []
        for sym in rhs:
            if sym == "•":
                parts.append('<span style="color:#f87171;font-weight:bold;">•</span>')
            else:
                parts.append(f'<span style="color:#a5f3fc;">{esc(sym)}</span>')
        html += " ".join(parts)

        if show_lookahead and item.lookahead:
            la = ", ".join(sorted(item.lookahead))
            html += (f'<span style="color:#475569;"> , </span>'
                     f'<span style="color:#fbbf24;">{esc(la)}</span>')
        return html

    def _show_dfa(self, states, trans, title):
        """
        Render the LR automaton: each state's item set plus the GOTO/shift
        transitions leaving it.  CLR shows lookaheads, LR(0)/SLR do not.
        """
        show_la = title.startswith("CLR")

        # Group transitions by source state for quick lookup.
        out = {}
        for (src, sym), dst in trans.items():
            out.setdefault(src, []).append((sym, dst))

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        lines = []
        for i, state in enumerate(states):
            # Sort items: kernel first (dot > 0 or augmented start), then by name.
            items = sorted(
                state,
                key=lambda it: (not (it.dot > 0 or it.lhs.endswith("'")),
                                it.lhs, it.rhs, it.dot)
            )

            lines.append(
                f'<div style="margin:6px 0 2px 0;">'
                f'<span style="color:#facc15;font-weight:bold;background:#21262d;'
                f'padding:1px 8px;border-radius:4px;">I{i}</span></div>'
            )
            for it in items:
                lines.append(
                    f'<div style="margin:0 0 0 14px;line-height:1.5;">'
                    f'{self._format_item(it, show_la)}</div>'
                )

            # Transitions out of this state.
            for sym, dst in sorted(out.get(i, [])):
                lines.append(
                    f'<div style="margin:0 0 0 30px;line-height:1.4;">'
                    f'<span style="color:#475569;">goto on </span>'
                    f'<span style="color:#4ade80;font-weight:bold;">{esc(sym)}</span>'
                    f'<span style="color:#475569;"> → </span>'
                    f'<span style="color:#fb923c;font-weight:bold;">I{dst}</span></div>'
                )

        self.dfa_label.setText(
            f"🔵 {title} DFA — {len(states)} states, {len(trans)} transitions"
        )
        body = "\n".join(lines)
        self.dfa_view.setHtml(
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:12px;background:#0d1117;color:#a5f3fc;">{body}</div>'
        )
        self.dfa_view.verticalScrollBar().setValue(0)

    # =========================================================================
    # LL(1) TABLE DISPLAY
    # =========================================================================

    def _show_ll1_table(self, table, title="LL(1)"):
        """Render LL(1) parse table: rows = NTs, cols = terminals."""
        nts = list(GRAMMAR.keys())
        terminals_set = set()
        for (nt, t) in table.keys():
            terminals_set.add(t)
        terminals = sorted(terminals_set)

        self.parse_table_widget.clearContents()
        self.parse_table_widget.setRowCount(len(nts))
        self.parse_table_widget.setColumnCount(len(terminals))
        self.parse_table_widget.setHorizontalHeaderLabels(terminals)
        self.parse_table_widget.setVerticalHeaderLabels(nts)
        self.parse_table_widget.verticalHeader().setVisible(True)
        self.parse_table_widget.verticalHeader().setStyleSheet(
            f"QHeaderView::section {{ background:#21262d; color:#22d3ee; padding:4px; "
            f"border:none; border-right:1px solid {BORDER}; font-family:Consolas; "
            f"font-size:11px; font-weight:bold; }}"
        )

        for row, nt in enumerate(nts):
            for col, t in enumerate(terminals):
                prod = table.get((nt, t))
                if prod is not None:
                    rhs = " ".join(prod) if prod != [EPS] else "ε"
                    text = f"{nt} → {rhs}"
                    item = QTableWidgetItem(text)
                    item.setForeground(QColor("#e2e8f0"))
                    item.setBackground(QColor("#1a2233"))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    self.parse_table_widget.setItem(row, col, item)

        self.parse_table_label.setText(f"{title} Parse Table")
        self.tabs.setCurrentIndex(1)

    # =========================================================================
    # ERROR HIGHLIGHT HELPERS
    # =========================================================================

    def _clear_highlights(self):
        """Remove all extra formatting from the editor."""
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#161b22"))   # default bg
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.NoUnderline)
        cursor.setCharFormat(fmt)
        cursor.clearSelection()
        self.editor.setTextCursor(cursor)

    def _highlight_error_line(self, line: int):
        """
        Highlight the entire error line in red and scroll to it.
        line is 1-based.
        """
        self._clear_highlights()
        if line is None or line == "?":
            return
        try:
            line = int(line)
        except (TypeError, ValueError):
            return

        doc    = self.editor.document()
        block  = doc.findBlockByLineNumber(line - 1)   # 0-based
        if not block.isValid():
            return

        cursor = QTextCursor(block)
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)

        # Red background + red wavy underline
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#3b0f0f"))
        fmt.setUnderlineColor(QColor("#f87171"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        cursor.setCharFormat(fmt)

        # Scroll editor to that line
        scroll_cur = QTextCursor(block)
        self.editor.setTextCursor(scroll_cur)
        self.editor.ensureCursorVisible()

    def _show_syntax_error(self, exc: ValueError, parser_name: str):
        """Display a rich error panel in the Parse Tree tab."""
        args    = exc.args
        message = args[0] if args else str(exc)
        line    = args[1] if len(args) > 1 else None
        col     = args[2] if len(args) > 2 else None

        self._highlight_error_line(line)

        # Show in tree view as styled error card
        loc = f"Line {line}, Col {col}" if line not in (None, "?") else "Unknown location"
        html = f"""
        <div style="font-family:Consolas,'Courier New',monospace;
                    font-size:13px; background:#0d1117; padding:16px;">
          <p style="color:#f87171;font-size:15px;font-weight:bold;margin:0 0 10px 0;">
            &#9888; Syntax Error — {parser_name}
          </p>
          <div style="background:#1a0a0a;border:1px solid #7f1d1d;
                      border-radius:6px;padding:12px;margin-bottom:12px;">
            <span style="color:#fca5a5;">{self._esc(message)}</span>
          </div>
          <p style="color:#6b7280;margin:0;">
            <span style="color:#94a3b8;">Location:</span>
            <span style="color:#fbbf24;"> {loc}</span>
          </p>
          <p style="color:#475569;margin:8px 0 0 0;font-size:11px;">
            Fix the highlighted line in the editor and try again.
          </p>
        </div>
        """
        self.tree_view.setHtml(html)
        self.tabs.setCurrentIndex(2)
        self.status.showMessage(f"{parser_name} Syntax Error — {loc} — {message.splitlines()[0]}")

    @staticmethod
    def _esc(s: str) -> str:
        return (str(s).replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;")
                      .replace("\n", "<br>"))

    # =========================================================================
    # PARSER ACTIONS
    # =========================================================================

    # ── shared: start a background worker ────────────────────────────────────

    def _start_worker(self, mode: str):
        """Disable buttons, start worker thread, show animated status."""
        if self._worker and self._worker.isRunning():
            return   # already busy

        tokens = self._get_tokens()
        self._set_buttons_enabled(False)
        self._clear_highlights()

        labels = {
            "LR0": "LR(0)", "SLR": "SLR(1)",
            "CLR": "CLR(1)", "LL1": "LL(1)", "SYNTAX": "Syntax",
            "ICG": "Intermediate Code", "OPT": "Code Optimization",
            "ASM": "Assembly Code",
        }
        self.status.showMessage(
            f"Building {labels.get(mode, mode)} tables... please wait"
        )

        self._worker = ParserWorker(mode, tokens, parent=self)
        self._worker.done.connect(self._on_worker_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _set_buttons_enabled(self, enabled: bool):
        for b in (self.compile_btn, self.opt_btn, self.asm_btn, self.semantics_btn,
                  self.lr0_btn, self.slr1_btn, self.clr1_btn, self.ll1_btn,
                  self.first_btn, self.follow_btn, self.tree_btn):
            b.setEnabled(enabled)
        # Grey out when disabled
        style_off = "opacity:0.5;" if not enabled else ""
        for b in (self.compile_btn, self.opt_btn, self.asm_btn, self.semantics_btn,
                  self.lr0_btn, self.slr1_btn, self.clr1_btn, self.ll1_btn):
            b.setStyleSheet(b.styleSheet().replace("opacity:0.5;", "")
                            + style_off)

    def _on_worker_done(self, mode: str, result: dict):
        self._set_buttons_enabled(True)

        labels = {
            "LR0": "LR(0)", "SLR": "SLR(1)",
            "CLR": "CLR(1)", "LL1": "LL(1)", "SYNTAX": "Syntax",
            "ICG": "Intermediate Code", "OPT": "Code Optimization",
            "ASM": "Assembly Code",
        }
        name = labels.get(mode, mode)

        # ── Show parse table (LR modes) ──
        if "table" in result:
            ACTION, GOTO, states, conflicts = result["table"]
            self._show_lr_table(ACTION, GOTO, states, conflicts, name)

        # ── Show DFA (LR modes) or clear it (LL(1)) ──
        if "dfa" in result:
            states, trans, dfa_mode = result["dfa"]
            self._show_dfa(states, trans, name)
        elif mode in ("LL1", "SYNTAX"):
            self._clear_dfa(name)

        # ── Show LL(1) table ──
        if "ll1_table" in result and mode == "LL1":
            self._show_ll1_table(result["ll1_table"], "LL(1)")

        # ── Show tree or error ──
        if "parse_error" in result:
            self._show_syntax_error(result["parse_error"], name)
            if "table" in result:
                n = len(result["table"][2])
                self.status.showMessage(
                    f"{name}: {n} states built — parse error (see Parse Tree tab)"
                )
        elif "tree" in result:
            tree = result["tree"]
            self._last_tree_root = tree
            self._display_tree(tree)

            if mode == "ICG":
                quads = result.get("tac", [])
                self._show_tac(quads)
                self.status.showMessage(
                    f"Intermediate Code generated — {len(quads)} instruction(s)"
                )
            elif mode == "OPT":
                quads = result.get("tac", [])
                self._show_tac(quads)          # keep ICG tab populated too
                opt_res = result.get("opt")
                if opt_res:
                    self._show_optimization(opt_res)
                    s = opt_res["stats"]
                    self.status.showMessage(
                        f"Optimization complete — {s['before']} → {s['after']} "
                        f"instructions ({s['removed']} removed), "
                        f"{len(opt_res['loops'])} loop(s) detected"
                    )
            elif mode == "ASM":
                asm_text = result.get("asm_text", "")
                self._show_assembly(asm_text)
                self.status.showMessage("Assembly code generated ✔")
            elif mode == "SYNTAX":
                html = self._syntax_to_html(tree)
                self.syntax_view.setHtml(html)
                self.syntax_view.verticalScrollBar().setValue(0)
                self.tabs.setCurrentIndex(3)
                self.status.showMessage("Syntax Analysis complete — SDD annotated AST shown")
            elif "table" in result:
                n = len(result["table"][2])
                self.status.showMessage(f"{name}: {n} states — ACCEPT")
            else:
                self.status.showMessage(f"{name} Parsing: ACCEPT")

    def _on_worker_error(self, mode: str, exc: Exception):
        self._set_buttons_enabled(True)
        if mode != "_PREWARM":
            QMessageBox.warning(self, f"{mode} Error", str(exc))
        self.status.showMessage(f"{mode} failed: {exc}")

    def _on_prewarm_done(self, mode: str, result: dict):
        if result.get("prewarm"):
            self.status.showMessage(
                "Ready  •  All parser tables cached — buttons respond instantly"
            )

    # ── Public parser actions (each just starts a worker) ─────────────────

    def run_lr0(self):    self._start_worker("LR0")
    def run_slr(self):    self._start_worker("SLR")
    def run_clr(self):    self._start_worker("CLR")
    def run_ll1(self):    self._start_worker("LL1")
    def run_syntax(self): self._start_worker("SYNTAX")
    def run_icg(self):    self._start_worker("ICG")
    def run_opt(self):    self._start_worker("OPT")

    def run_asm(self):    self._start_worker("ASM")

    def save_assembly(self):
        """Save the generated assembly to a .asm file for emu8086 / MASM."""
        if not self._last_asm_text:
            self.status.showMessage("Generate assembly first")
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "Save Assembly", "output.asm",
            "Assembly Files (*.asm);;All Files (*)"
        )
        if name:
            try:
                with open(name, "w", encoding="utf-8") as f:
                    f.write(self._last_asm_text)
                self.status.showMessage(f"Assembly saved: {name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    # ── SDD colours ──────────────────────────────────────────────────────────
    _S_HEAD    = "#c084fc"   # section header — violet
    _S_NT      = "#67e8f9"   # non-terminal name — cyan
    _S_LEAF    = "#4ade80"   # terminal leaf — green
    _S_VAL     = "#fde68a"   # «value» — amber
    _S_MEANING = "#a78bfa"   # SDD meaning — purple
    _S_TYPE    = "#34d399"   # type badge — emerald
    _S_SVAL    = "#fb923c"   # synthesised value — orange
    _S_BRANCH  = "#334155"   # tree connectors
    _S_POS     = "#475569"   # line:col

    def _syntax_to_html(self, root: Node) -> str:
        """
        Two-panel HTML:
          Left column  = annotated tree (connectors + node name)
          Right column = SDD meaning + type + value
        Rendered as a single pre-formatted HTML block.
        """
        lines: list[str] = []

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))

        def sp(text, color, bold=False, italic=False):
            b  = "font-weight:bold;"   if bold   else ""
            it = "font-style:italic;"  if italic else ""
            return f'<span style="color:{color};{b}{it}">{esc(text)}</span>'

        def br(text):
            return f'<span style="color:{self._S_BRANCH};">{esc(text)}</span>'

        def badge(text, color):
            return (
                f'<span style="color:{color};background:#1e293b;'
                f'border:1px solid {color}55;border-radius:4px;'
                f'padding:0 6px;font-size:11px;">{esc(text)}</span>'
            )

        def render(node: Node, prefix: str, is_last: bool):
            connector = "└── " if is_last else "├── "
            is_leaf   = node.is_terminal()

            # ── Node label (left part) ────────────────────────────────────
            if is_leaf:
                tok = node.tok_type or node.name
                node_label = sp(tok, self._S_LEAF, bold=True)
                node_label += "  " + sp(f"«{node.name}»", self._S_VAL)
                if node.line:
                    node_label += sp(f" (L{node.line}:C{node.col})", self._S_POS, italic=True)
            else:
                node_label = sp(node.name, self._S_NT, bold=True)

            # ── SDD annotation badges (right part) ────────────────────────
            annotation = ""
            if hasattr(node, "meaning") and node.meaning:
                annotation += "  " + sp(f"→ {node.meaning}", self._S_MEANING, italic=True)
            if hasattr(node, "stype") and node.stype and not is_leaf:
                annotation += "  " + badge(f"type:{node.stype}", self._S_TYPE)
            if hasattr(node, "sval") and node.sval and not is_leaf:
                v = node.sval if len(str(node.sval)) <= 30 else str(node.sval)[:27] + "..."
                annotation += "  " + badge(f"val:{v}", self._S_SVAL)

            lines.append(
                '<p style="margin:0;padding:0;line-height:1.7;white-space:nowrap;">'
                + br(prefix + connector)
                + node_label
                + annotation
                + "</p>"
            )

            if node.kids:
                child_prefix = prefix + ("    " if is_last else "│   ")
                for i, child in enumerate(node.kids):
                    render(child, child_prefix, i == len(node.kids) - 1)

        # ── Header ──
        lines.append(
            '<p style="margin:0 0 10px 0;padding:6px 0;line-height:2;'
            f'border-bottom:1px solid #1e293b;">'
            + sp("SYNTAX ANALYSIS", self._S_HEAD, bold=True)
            + "  "
            + sp("— SDD Annotated AST with Semantic Meanings", "#64748b", italic=True)
            + "</p>"
        )

        # ── Legend ──
        lines.append(
            '<p style="margin:0 0 10px 0;padding:0;line-height:1.6;font-size:11px;">'
            + badge("type:T", self._S_TYPE) + "  data type   "
            + badge("val:V", self._S_SVAL)  + "  synthesised value   "
            + sp("→ SDD meaning", self._S_MEANING, italic=True)
            + "</p>"
        )

        # ── Root ──
        root_label = sp(root.name, self._S_NT, bold=True)
        annotation = ""
        if hasattr(root, "meaning") and root.meaning:
            annotation += "  " + sp(f"→ {root.meaning}", self._S_MEANING, italic=True)
        lines.append(
            f'<p style="margin:0;padding:0;line-height:1.7;">'
            + root_label + annotation + "</p>"
        )

        for i, child in enumerate(root.kids):
            render(child, "", i == len(root.kids) - 1)

        body = "\n".join(lines)
        return (
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:13px;background:#0d1117;color:#a5f3fc;padding:10px;">'
            + body + "</div>"
        )

    # =========================================================================

    def run_first(self):
        engine = self._get_engine()
        first = engine.first_sets()
        self._show_set_table(first, "FIRST")
        self.tabs.setCurrentIndex(0)
        self.status.showMessage("FIRST Sets shown ✔")

    def run_follow(self):
        engine = self._get_engine()
        follow = engine.follow_sets()
        self._show_set_table(follow, "FOLLOW")
        self.tabs.setCurrentIndex(0)
        self.status.showMessage("FOLLOW Sets shown ✔")

    def _show_set_table(self, data, title):
        """Populate token_table with { NT: set } data."""
        self.token_table.clearContents()
        self.token_table.setColumnCount(2)
        self.token_table.setHorizontalHeaderLabels([f"{title}( Non-Terminal )", "Terminals"])
        self.token_table.horizontalHeader().setStretchLastSection(True)

        rows = [(nt, v) for nt, v in data.items() if nt in GRAMMAR]
        self.token_table.setRowCount(len(rows))

        for row, (nt, tset) in enumerate(rows):
            nt_item = QTableWidgetItem(nt)
            nt_item.setForeground(QColor("#22d3ee"))
            nt_item.setBackground(QColor("#0e3a45"))
            font = QFont("Consolas", 11)
            font.setBold(True)
            nt_item.setFont(font)

            val_item = QTableWidgetItem("{ " + ",  ".join(sorted(tset)) + " }")
            val_item.setForeground(QColor("#e2e8f0"))
            val_item.setBackground(QColor(DARK_BG))

            self.token_table.setItem(row, 0, nt_item)
            self.token_table.setItem(row, 1, val_item)

        self.token_table.resizeColumnsToContents()
        self.token_table.horizontalHeader().setStretchLastSection(True)

    # =========================================================================
    # PARSE TREE DISPLAY  (text-based, image-style)
    # =========================================================================

    # HTML colour constants for the tree renderer
    _C_NT     = "#67e8f9"   # non-terminal  — cyan
    _C_LEAF   = "#4ade80"   # terminal leaf — green
    _C_VAL    = "#fde68a"   # «value» part  — amber
    _C_BRANCH = "#334155"   # connector lines — muted blue-grey
    _C_TITLE  = "#7dd3fc"   # PARSE TREE header — sky

    def _node_is_terminal(self, node: Node) -> bool:
        """A node is a terminal leaf if it has no children."""
        return len(node.kids) == 0

    def _tree_to_html(self, root: Node) -> str:
        """
        Render AST with values at each level:

        PARSE TREE
        Program                     [= integer age equalto 20 semi]
        ├── FuncList                [= ε]
        └── StmtList                [= integer age equalto 20 semi]
            └── Stmt
                └── DeclStmt        [= integer age equalto 20 semi]
                    ├── DataType    [= integer]
                    │   └── integer  «integer»    (line 1, col 1)
                    ├── age  «age»                (line 1, col 9)
                    └── DeclTail    [= equalto 20 semi]
        """
        lines: list[str] = []

        def esc(s: str) -> str:
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))

        def span(text, color, bold=False, italic=False):
            b = "font-weight:bold;"  if bold   else ""
            it = "font-style:italic;" if italic else ""
            return f'<span style="color:{color};{b}{it}">{esc(text)}</span>'

        def branch_span(text):
            return f'<span style="color:{self._C_BRANCH};">{esc(text)}</span>'

        def render(node: Node, prefix: str, is_last: bool):
            connector = "└── " if is_last else "├── "

            # A real terminal = has tok_type set from lexer (actual token matched)
            # Epsilon/collapsed nodes = no kids AND no tok_type → just show name
            is_real_token = node.is_terminal() and bool(node.tok_type)
            is_epsilon    = node.is_terminal() and not node.tok_type

            if is_real_token:
                # Real terminal: tok_type green + «value» amber
                label = span(node.tok_type, self._C_LEAF, bold=True)
                label += "  " + span(f"«{node.name}»", self._C_VAL)
            elif is_epsilon:
                # Epsilon (empty) node: muted, no «»
                label = span(node.name, "#475569", italic=True)
            else:
                # Non-terminal: just the name, no value annotation
                label = span(node.name, self._C_NT, bold=True)

            lines.append(
                '<p style="margin:0;padding:0;line-height:1.6;">'
                + branch_span(prefix + connector)
                + label
                + "</p>"
            )

            if node.kids:
                child_prefix = prefix + ("    " if is_last else "│   ")
                for idx, child in enumerate(node.kids):
                    render(child, child_prefix, idx == len(node.kids) - 1)

        # ── Header ──
        lines.append(
            '<p style="margin:0 0 8px 0;padding:0;line-height:1.9;'
            'border-bottom:1px solid #1e293b;">'
            + span("PARSE TREE", self._C_TITLE, bold=True)
            + "</p>"
        )

        # ── Root node ──
        lines.append(
            f'<p style="margin:0;padding:0;line-height:1.6;">'
            + span(root.name, self._C_NT, bold=True)
            + "</p>"
        )

        for idx, child in enumerate(root.kids):
            render(child, "", idx == len(root.kids) - 1)

        body = "\n".join(lines)
        return (
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:13px;background:#0d1117;color:#a5f3fc;'
            f'padding:10px;white-space:pre;">'
            + body
            + "</div>"
        )

    def _display_tree(self, root_node: Node):
        if root_node is None:
            self.tree_view.setHtml(
                '<p style="color:#6b7280;font-family:Consolas;">No parse tree.</p>'
            )
            self.tabs.setCurrentIndex(2)
            return

        html = self._tree_to_html(root_node)
        self.tree_view.setHtml(html)
        # Scroll to top
        self.tree_view.verticalScrollBar().setValue(0)
        self.tabs.setCurrentIndex(2)

    def show_current_tree(self):
        if self._last_tree_root is None:
            self.status.showMessage("No parse tree yet — run a parser first")
        else:
            self._display_tree(self._last_tree_root)
            self.status.showMessage("Parse Tree displayed ✔")

    # =========================================================================
    # TOKENS
    # =========================================================================

    def load_tokens(self, live: bool = False):
        all_tokens = self._get_tokens()
        # Error tokens are NOT real tokens — exclude them from the token list
        # and from the Total count; they belong in the ⚠ Errors tab.
        tokens = [t for t in all_tokens if t.get("category") != "ERROR"]

        self.token_table.clearContents()
        self.token_table.setColumnCount(3)
        self.token_table.setHorizontalHeaderLabels(["Category", "Type", "Value"])
        self.token_table.setRowCount(len(tokens))
        self.token_table.horizontalHeader().setStretchLastSection(True)

        counts = Counter(tok.get("category", "UNKNOWN") for tok in tokens)

        for row, tok in enumerate(tokens):
            category = str(tok.get("category", "UNKNOWN"))
            typ      = str(tok.get("type", ""))
            value    = str(tok.get("value", ""))

            fg_hex, bg_hex = CATEGORY_COLORS.get(category, ("#e6edf3", "#161b22"))
            fg = QColor(fg_hex)
            bg = QColor(bg_hex)

            cat_item = QTableWidgetItem(category)
            cat_item.setForeground(fg)
            cat_item.setBackground(bg)
            font = QFont("Consolas", 11)
            font.setBold(True)
            cat_item.setFont(font)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

            type_item = QTableWidgetItem(typ)
            type_item.setForeground(QColor("#9ca3af"))
            type_item.setBackground(QColor(DARK_BG))

            val_item = QTableWidgetItem(value)
            val_item.setForeground(QColor("#e2e8f0"))
            val_item.setBackground(QColor(DARK_BG))

            self.token_table.setItem(row, 0, cat_item)
            self.token_table.setItem(row, 1, type_item)
            self.token_table.setItem(row, 2, val_item)

        self.token_table.resizeColumnsToContents()
        self.token_table.horizontalHeader().setStretchLastSection(True)

        # Rebuild summary badges
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.summary_layout.addWidget(
            self._make_badge(f"Total  {len(tokens)}", ACCENT, "#0c2340")
        )
        for cat in ["KEYWORD", "IDENTIFIER", "NUMBER", "STRING", "OPERATOR", "DELIMITER", "UNKNOWN"]:
            if cat in counts:
                fg_hex, bg_hex = CATEGORY_COLORS.get(cat, ("#e6edf3", "#21262d"))
                self.summary_layout.addWidget(
                    self._make_badge(f"{cat}  {counts[cat]}", fg_hex, bg_hex)
                )
        self.summary_layout.addStretch()

        # Symbol table is built from the valid tokens.
        self._show_symbol_table(tokens)

        # Collect Lexical + Syntax + Semantic errors and show them together.
        errors = self._collect_errors(all_tokens, tokens)
        self._show_errors(errors)

        if not live:
            self.tabs.setCurrentIndex(0)
            if errors:
                # Highlight the first offending line in the editor.
                self._highlight_error_line(errors[0].get("line"))

        if errors:
            kinds = Counter(e["kind"] for e in errors)
            summary = ", ".join(f"{v} {k.lower()}" for k, v in kinds.items())
            self.status.showMessage(
                f"⚠  {len(tokens)} tokens  •  {len(errors)} error(s) "
                f"({summary}) — see ⚠ Errors tab"
            )
        else:
            self.status.showMessage(
                f"✅  {len(tokens)} tokens  •  " +
                "  ".join(f"{k}: {v}" for k, v in counts.items())
            )

    def _collect_errors(self, all_tokens, valid_tokens):
        """Gather Lexical, Syntax and Semantic errors into one unified list."""
        errors = []

        # Lexical — from the raw lexer output (these tokens carry .error).
        for e in lexer_mod.lexical_errors(all_tokens):
            errors.append({
                "kind":  "Lexical",
                "line":  e.get("line"),
                "col":   e.get("col"),
                "value": e.get("value"),
                "error": e.get("error", "Lexical error"),
            })

        # Syntax + Semantic — run on the valid token stream.
        errors += lexer_mod.syntax_errors(valid_tokens)
        errors += lexer_mod.semantic_errors(valid_tokens)

        # Lexical first, then by source position.
        order = {"Lexical": 0, "Syntax": 1, "Semantic": 2}
        errors.sort(key=lambda e: (e.get("line") or 0, e.get("col") or 0,
                                   order.get(e["kind"], 9)))
        return errors

    def _show_symbol_table(self, tokens):
        """Fill the Symbol Table tab: Name | Data Type | Scope | Additional Info."""
        symbols = lexer_mod.build_symbol_table(tokens)

        self.symbol_table.clearContents()
        self.symbol_table.setColumnCount(4)
        self.symbol_table.setHorizontalHeaderLabels(
            ["Name", "Data Type", "Scope", "Additional Info"]
        )
        self.symbol_table.setRowCount(len(symbols))
        self.symbol_table.horizontalHeader().setStretchLastSection(True)

        for row, sym in enumerate(symbols):
            scope     = str(sym.get("scope", "—"))
            scope_fg  = "#fb923c" if scope.startswith("local") else "#4ade80"
            cells = [
                (sym["name"],                "#ffffff", True),
                (str(sym["data_type"]),      "#22d3ee", False),
                (scope,                      scope_fg,  False),
                (str(sym.get("info", "")),   "#9ca3af", False),
            ]
            for col, (text, fg, bold) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(DARK_BG))
                if bold:
                    f = QFont("Consolas", 11)
                    f.setBold(True)
                    item.setFont(f)
                self.symbol_table.setItem(row, col, item)

        self.symbol_table.resizeColumnsToContents()
        self.symbol_table.horizontalHeader().setStretchLastSection(True)

    # Per-phase colours for the Errors tab.
    _PHASE_COLORS = {
        "Lexical":  ("#fca5a5", "#2a0a0a"),   # red
        "Syntax":   ("#fdba74", "#2a1605"),   # orange
        "Semantic": ("#c4b5fd", "#1c1230"),   # violet
    }

    def _show_errors(self, errors):
        """Fill the unified Errors tab: Phase | Line | Col | Value | Description."""
        self.error_table.clearContents()
        self.error_table.setColumnCount(5)
        self.error_table.setHorizontalHeaderLabels(
            ["Phase", "Line", "Col", "Value", "Description"]
        )
        self.error_table.setRowCount(len(errors))
        self.error_table.horizontalHeader().setStretchLastSection(True)

        for row, err in enumerate(errors):
            kind = err.get("kind", "Lexical")
            fg, bg = self._PHASE_COLORS.get(kind, ("#fca5a5", "#1a0a0a"))
            cells = [
                str(kind),
                str(err.get("line", "?")),
                str(err.get("col", "?")),
                str(err.get("value", "")),
                str(err.get("error", "Error")),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(bg))
                if col == 0:
                    f = QFont("Consolas", 11)
                    f.setBold(True)
                    item.setFont(f)
                self.error_table.setItem(row, col, item)

        self.error_table.resizeColumnsToContents()
        self.error_table.horizontalHeader().setStretchLastSection(True)

        # Update the Errors tab label with a live count.
        idx = self.tabs.indexOf(self.error_table.parentWidget())
        if idx != -1:
            self.tabs.setTabText(
                idx, f"⚠ Errors ({len(errors)})" if errors else "⚠ Errors"
            )

        return errors

    # =========================================================================
    # INTERMEDIATE CODE (Three-Address Code) DISPLAY
    # =========================================================================

    def _show_tac(self, quads):
        """Render TAC as a code listing (top) and a quadruple table (bottom)."""
        # ── Code listing ──────────────────────────────────────────────────
        lines = []
        for q in quads:
            txt = self._esc(q.to_text())
            if q.op == "label":
                # Labels flush-left, highlighted.
                lines.append(
                    f'<div style="color:#facc15;font-weight:bold;">{txt}</div>'
                )
            elif q.op in ("func", "endfunc"):
                lines.append(
                    f'<div style="color:#c084fc;font-weight:bold;">{txt}</div>'
                )
            elif q.op in ("goto", "ifFalse", "if"):
                lines.append(f'<div style="color:#fb923c;">{txt}</div>')
            elif q.op in ("display", "read", "param", "return"):
                lines.append(f'<div style="color:#4ade80;">{txt}</div>')
            else:
                lines.append(f'<div style="color:#a5f3fc;">{txt}</div>')

        if not lines:
            lines.append('<div style="color:#6b7280;">No code generated.</div>')

        body = "\n".join(lines)
        self.tac_view.setHtml(
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:13px;line-height:1.55;background:#0d1117;'
            f'white-space:pre;">{body}</div>'
        )
        self.tac_view.verticalScrollBar().setValue(0)

        # ── Quadruple table ───────────────────────────────────────────────
        self.quad_table.clearContents()
        self.quad_table.setColumnCount(5)
        self.quad_table.setHorizontalHeaderLabels(["#", "op", "arg1", "arg2", "result"])
        self.quad_table.setRowCount(len(quads))
        self.quad_table.horizontalHeader().setStretchLastSection(True)

        for row, q in enumerate(quads):
            op, a1, a2, res = q.as_row()
            cells = [
                (str(row + 1), "#8b949e"),
                (op,           "#22d3ee"),
                (a1,           "#e2e8f0"),
                (a2,           "#e2e8f0"),
                (res,          "#fb923c"),
            ]
            for col, (text, fg) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(DARK_BG))
                self.quad_table.setItem(row, col, item)

        self.quad_table.resizeColumnsToContents()
        self.quad_table.horizontalHeader().setStretchLastSection(True)

        self.icg_label.setText(
            f"⚙ Intermediate Code — Three-Address Code ({len(quads)} instructions)"
        )

        idx = self.tabs.indexOf(self.icg_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    # =========================================================================
    # CODE OPTIMIZATION DISPLAY
    # =========================================================================

    def _show_optimization(self, res):
        """Render the full optimization report into the Optimization tab."""
        import intermediate_code as icg

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        def h(text, color):
            return (f'<div style="color:{color};font-weight:bold;font-size:14px;'
                    f'margin:14px 0 6px 0;border-bottom:1px solid #1e293b;'
                    f'padding-bottom:3px;">{esc(text)}</div>')

        out = []

        # ── Header / stats ──────────────────────────────────────────────
        s = res["stats"]
        out.append(
            '<div style="font-size:14px;font-weight:bold;color:#fb7185;'
            'margin-bottom:6px;">🚀 CODE OPTIMIZATION  —  Machine-Independent</div>'
        )
        out.append(
            f'<div style="color:#8b949e;">Instructions: '
            f'<span style="color:#4ade80;font-weight:bold;">{s["before"]}</span> '
            f'→ <span style="color:#22d3ee;font-weight:bold;">{s["after"]}</span>'
            f'  ({s["removed"]} removed)  •  '
            f'<span style="color:#facc15;">{len(res["loops"])}</span> loop(s) detected'
            f'</div>'
        )

        # ── 1. Basic Blocks ─────────────────────────────────────────────
        out.append(h("1️⃣  BASIC BLOCKS  (leaders → blocks)", "#22d3ee"))
        for blk in res["orig_blocks"]:
            succ = ", ".join(f"B{x}" for x in sorted(blk.succs)) or "—"
            out.append(
                f'<div style="color:#f472b6;font-weight:bold;margin-top:6px;">'
                f'B{blk.idx}: <span style="color:#6b7280;font-weight:normal;">'
                f'(successors: {esc(succ)})</span></div>'
            )
            for q in blk.quads:
                out.append(
                    f'<div style="color:#a5f3fc;margin-left:18px;">'
                    f'{esc(q.to_text().strip())}</div>'
                )

        # ── 2. Control-Flow Graph (PFG) ─────────────────────────────────
        out.append(h("2️⃣  CONTROL-FLOW GRAPH  (Program Flow Graph)", "#34d399"))
        edge_colors = {"fall": "#8b949e", "jump": "#facc15",
                       "branch": "#fb923c"}
        if res["orig_cfg_edges"]:
            for (sx, dx, kind) in res["orig_cfg_edges"]:
                c = edge_colors.get(kind, "#8b949e")
                out.append(
                    f'<div style="margin-left:10px;">'
                    f'<span style="color:#67e8f9;font-weight:bold;">B{sx}</span>'
                    f'<span style="color:{c};">  ──{esc(kind)}──▶  </span>'
                    f'<span style="color:#67e8f9;font-weight:bold;">B{dx}</span>'
                    f'</div>'
                )
        else:
            out.append('<div style="color:#6b7280;margin-left:10px;">(linear code — no branches)</div>')

        # ── 3. Loop Detection ───────────────────────────────────────────
        out.append(h("3️⃣  LOOP DETECTION  (dominators → back edges)", "#facc15"))
        if res["orig_loops"]:
            for L in res["orig_loops"]:
                nodes = ", ".join(f"B{x}" for x in L["nodes"])
                be = L["back_edge"]
                out.append(
                    f'<div style="margin-left:10px;margin-top:4px;">'
                    f'<span style="color:#facc15;font-weight:bold;">Loop:</span> '
                    f'header <span style="color:#67e8f9;">B{L["header"]}</span>, '
                    f'nodes {{<span style="color:#a5f3fc;">{esc(nodes)}</span>}}, '
                    f'back edge <span style="color:#fb923c;">B{be[0]}→B{be[1]}</span>'
                    f'</div>'
                )
        else:
            out.append('<div style="color:#6b7280;margin-left:10px;">(no loops found)</div>')

        # ── 4. Optimization Passes ──────────────────────────────────────
        out.append(h("4️⃣  OPTIMIZATIONS APPLIED", "#c084fc"))
        if res["passes"]:
            for p in res["passes"]:
                out.append(
                    f'<div style="color:#c084fc;font-weight:bold;margin-top:8px;">'
                    f'▸ {esc(p["name"])}  '
                    f'<span style="color:#6b7280;font-weight:normal;">'
                    f'({len(p["changes"])} change(s))</span></div>'
                )
                for c in p["changes"]:
                    out.append(
                        f'<div style="color:#e2e8f0;margin-left:18px;">'
                        f'{esc(c)}</div>'
                    )
        else:
            out.append('<div style="color:#6b7280;margin-left:10px;">(nothing to optimize)</div>')

        # ── 5. Before / After code ──────────────────────────────────────
        out.append(h("5️⃣  RESULT  —  Before vs After", "#fb7185"))
        before_txt = esc(icg.to_text(res["original"]))
        after_txt  = esc(icg.to_text(res["optimized"]))
        out.append(
            '<table width="100%" cellspacing="0" cellpadding="6" '
            'style="margin-top:6px;"><tr style="vertical-align:top;">'
            '<td width="50%" style="background:#161b22;border:1px solid #30363d;">'
            '<div style="color:#f87171;font-weight:bold;margin-bottom:4px;">'
            'BEFORE (un-optimized)</div>'
            f'<div style="color:#94a3b8;white-space:pre;">{before_txt}</div></td>'
            '<td width="50%" style="background:#0d1f17;border:1px solid #14532d;">'
            '<div style="color:#4ade80;font-weight:bold;margin-bottom:4px;">'
            'AFTER (optimized)</div>'
            f'<div style="color:#a5f3fc;white-space:pre;">{after_txt}</div></td>'
            '</tr></table>'
        )

        html = (
            '<div style="font-family:Consolas,\'Courier New\',monospace;'
            'font-size:13px;line-height:1.5;background:#0d1117;">'
            + "\n".join(out) + "</div>"
        )
        self.opt_view.setHtml(html)
        self.opt_view.verticalScrollBar().setValue(0)
        self.opt_label.setText(
            f"🚀 Code Optimization — {s['before']}→{s['after']} instructions, "
            f"{len(res['loops'])} loop(s)"
        )
        idx = self.tabs.indexOf(self.opt_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    # =========================================================================
    # ASSEMBLY DISPLAY
    # =========================================================================

    def _show_assembly(self, asm_text):
        """Render the generated assembly listing (code only)."""
        self._last_asm_text = asm_text

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        # ── Syntax-colour the assembly listing ──────────────────────────
        lines = []
        for raw in asm_text.split("\n"):
            t = raw.rstrip()
            stripped = t.strip()
            if not stripped:
                lines.append("<div>&nbsp;</div>")
                continue
            if stripped.startswith(";"):
                lines.append(f'<div style="color:#6b7280;">{esc(t)}</div>')
            elif stripped.startswith(".") or stripped.endswith(("PROC", "ENDP")) \
                    or stripped.startswith("END") or stripped.startswith("MAIN"):
                lines.append(f'<div style="color:#c084fc;font-weight:bold;">{esc(t)}</div>')
            elif stripped.endswith(":"):
                lines.append(f'<div style="color:#facc15;font-weight:bold;">{esc(t)}</div>')
            elif " DW " in t or " DB " in t:
                lines.append(f'<div style="color:#fb923c;">{esc(t)}</div>')
            else:
                # split mnemonic from comment
                if ";" in t:
                    code_part, _, cmt = t.partition(";")
                    lines.append(
                        f'<div><span style="color:#5eead4;">{esc(code_part)}</span>'
                        f'<span style="color:#475569;">;{esc(cmt)}</span></div>'
                    )
                else:
                    lines.append(f'<div style="color:#5eead4;">{esc(t)}</div>')

        html = (
            '<div style="font-family:Consolas,\'Courier New\',monospace;'
            'font-size:13px;line-height:1.45;white-space:pre;background:#0d1117;">'
            + "\n".join(lines) + "</div>"
        )
        self.asm_view.setHtml(html)
        self.asm_view.verticalScrollBar().setValue(0)

        self.asm_label.setText("🖥 Assembly Code — x86 (MASM / emu8086)")
        idx = self.tabs.indexOf(self.asm_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    def _make_badge(self, text, fg_hex, bg_hex):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            QLabel {{
                color:{fg_hex}; background-color:{bg_hex};
                border:1px solid {fg_hex}55; border-radius:10px;
                padding:2px 10px; font-family:Consolas;
                font-size:11px; font-weight:bold;
            }}
        """)
        lbl.setFixedHeight(22)
        return lbl

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    def open_file(self):
        name, _ = QFileDialog.getOpenFileName(
            self, "Open Crystal File", "",
            "Crystal Files (*.crystal *.txt);;All Files (*)"
        )
        if name:
            try:
                with open(name, "r", encoding="utf-8") as f:
                    self.editor.setText(f.read())
                self.status.showMessage(f"Opened: {name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def save_file(self):
        name, _ = QFileDialog.getSaveFileName(
            self, "Save Crystal File", "",
            "Crystal Files (*.crystal);;Text Files (*.txt)"
        )
        if name:
            try:
                with open(name, "w", encoding="utf-8") as f:
                    f.write(self.editor.toPlainText())
                self.status.showMessage(f"Saved: {name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))


# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CrystalCompilerGUI()
    window.show()
    sys.exit(app.exec())
