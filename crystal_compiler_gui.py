import sys
from collections import Counter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QTextEdit, QLabel,
    QStatusBar, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem,
    QTabWidget, QHeaderView, QStackedWidget,
    QGraphicsView, QGraphicsScene, QMenu,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import (QColor, QFont, QTextCursor, QTextCharFormat,
                         QShortcut, QKeySequence, QPen, QBrush, QPainter,
                         QPainterPath)

import lexer as lexer_mod
from grammer import Grammar, GRAMMAR, START, EPS, END
from parser_rules import GrammarEngine, Node
from semantic import SDDEngine

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
        self.mode   = mode    
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

            elif self.mode == "ANNOT":
              
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    SDDEngine().annotate(tree)
                    result["tree"]  = tree
                    result["annot"] = True
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "ICG":
              
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    result["tac"] = icg.generate(tree)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "DAG":
             
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    import dag
                    quads = icg.generate(tree)
                    result["tac"]        = quads
                    result["dag_blocks"] = dag.build_dags(quads)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "BACKPATCH":
               
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import backpatching as bp
                    g = bp.generate(tree)
                    result["bp"] = (g.instrs, g.log)
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "OPT":
                
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
              
                engine.build_ll1_table()
                try:
                    tree = engine.ll1_parse(self.tokens)
                    result["tree"] = tree
                    import intermediate_code as icg
                    import code_optimization as opt
                    import code_generation as cg
                    quads = icg.generate(tree)
                    quads = opt.optimize(quads)["optimized"]   
                    gen = cg.generate(quads)
                    new_code, _peep = cg.peephole(gen.code)
                    gen.code = new_code
                    result["asm_text"] = gen.to_text()
                except ValueError as pe:
                    result["parse_error"] = pe

            elif self.mode == "_PREWARM":
             
                engine.build_ll1_table()
                engine.build_lr0_table()
                engine.build_slr_table()
                engine.build_clr_table()
                result["prewarm"] = True

            self.done.emit(self.mode, result)

        except Exception as e:
            self.error.emit(self.mode, e)

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

class TreeGraphView(QGraphicsView):
    """A pannable / zoomable canvas that draws the parse tree as a real graph."""

    C_NONTERM = ("#1e3a5f", "#58a6ff", "#dbeafe") 
    C_TOKEN   = ("#14532d", "#4ade80", "#dcfce7")   
    C_VALUE   = ("#422006", "#facc15", "#fef9c3")  
    C_EPSILON = ("#3f3f46", "#a1a1aa", "#e4e4e7")   
    C_EDGE    = "#475569"

    H_GAP = 26        
    V_GAP = 84          
    NODE_H = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#0d1117")))
        self.setStyleSheet(f"border:1px solid {BORDER}; border-radius:8px;")
        self._leaf_x = 0.0

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

  
    def render_tree(self, root, annotated=False):
        """annotated=True → SDD mode: each node also shows its value (node.aval)."""
        self._scene.clear()
        if root is None:
            return
        self._annotated = annotated
        self.node_h = 50 if annotated else self.NODE_H
        self._vgap  = 104 if annotated else self.V_GAP
        self._leaf_x = 0.0
        self._measure(root)                       
        self._draw_edges(root)
        self._draw_nodes(root)
        rect = self._scene.itemsBoundingRect()
        rect.adjust(-40, -40, 40, 40)
        self._scene.setSceneRect(rect)
        self.resetTransform()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

   
    def _top_text(self, node):
        # Parse tree (non-annotated): a terminal leaf shows its GRAMMAR symbol
        # (token type — NUMBER, FLOAT, IDENTIFIER, Semi, integer, ...), NOT the
        # lexeme value. Non-terminals and the annotated tree keep node.name.
        if (not getattr(self, "_annotated", False)
                and not node.kids and getattr(node, "tok_type", None)):
            return str(node.tok_type)
        return str(node.name)

    def _val_text(self, node):
        """Bottom line for annotated mode: the SDD attribute(s) of the node,
        named like  X.val = 20 : integer  (val + type, as in the SDD rules)."""
        if not getattr(self, "_annotated", False):
            return ""
        av = getattr(node, "aval", None)
        if av is None or av == "":
            return ""
        s = str(av)
        s = s if len(s) <= 16 else s[:14] + "…"
        # attribute name: terminals carry .lexval, non-terminals carry .val
        attr = "lexval" if (not node.kids and getattr(node, "tok_type", None)) else "val"
        t = getattr(node, "stype", "") or ""
        return f".{attr} = {s}" + (f" : {t}" if t else "")

    def _label_width(self, node):
        longest = max(len(self._top_text(node)), len(self._val_text(node)))
        return max(48, 13 + longest * 8.2)

    def _measure(self, node, depth=0):
        node._gy = depth * self._vgap
        if not node.kids:
            w = self._label_width(node)
            node._gx = self._leaf_x + w / 2
            self._leaf_x += w + self.H_GAP
        else:
            for k in node.kids:
                self._measure(k, depth + 1)
            node._gx = (node.kids[0]._gx + node.kids[-1]._gx) / 2

    def _draw_edges(self, node):
        pen = QPen(QColor(self.C_EDGE))
        pen.setWidthF(1.6)
        for k in node.kids:
            path = QPainterPath()
            x1, y1 = node._gx, node._gy + self.node_h / 2
            x2, y2 = k._gx, k._gy - self.node_h / 2
            path.moveTo(x1, y1)
            midy = (y1 + y2) / 2
            path.cubicTo(x1, midy, x2, midy, x2, y2)   
            self._scene.addPath(path, pen)
            self._draw_edges(k)

    def _node_colors(self, node):
        if node.kids:
            return self.C_NONTERM
        if getattr(node, "tok_type", None):
            return self.C_TOKEN
        return self.C_EPSILON

    def _draw_nodes(self, node):
        top = self._top_text(node)
        val = self._val_text(node)
        w = self._label_width(node)
        h = self.node_h
        x = node._gx - w / 2
        y = node._gy - h / 2
        fill, border, txt = self._node_colors(node)

        rect = QRectF(x, y, w, h)
        box = QPainterPath()
        box.addRoundedRect(rect, 8, 8)
        self._scene.addPath(box, QPen(QColor(border), 2), QBrush(QColor(fill)))

        # top line — node name / lexeme
        item = self._scene.addText(top, QFont("Consolas", 10, QFont.Weight.Bold))
        item.setDefaultTextColor(QColor(txt))
        br = item.boundingRect()
        top_y = (node._gy - br.height() / 2) if not val else (node._gy - br.height() + 2)
        item.setPos(node._gx - br.width() / 2, top_y)

      
        if val:
            vitem = self._scene.addText(val, QFont("Consolas", 9, QFont.Weight.Bold))
            vitem.setDefaultTextColor(QColor("#fde68a"))
            vb = vitem.boundingRect()
            vitem.setPos(node._gx - vb.width() / 2, node._gy + 1)

        
        # Parse tree shows ONLY the grammar terminal at each leaf — no lexeme
        # value caption underneath.

        for k in node.kids:
            self._draw_nodes(k)


class DagGraphView(QGraphicsView):
    C_LEAF = ("#14532d", "#4ade80", "#dcfce7")  
    C_OP   = ("#3b1d5e", "#c084fc", "#f3e8ff")  
    C_EDGE = "#64748b"
    XGAP   = 96
    YGAP   = 100
    NODE_W = 64
    NODE_H = 42

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#0d1117")))
        self.setStyleSheet(f"border:1px solid {BORDER}; border-radius:8px;")

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def render_dags(self, dags):
        self._scene.clear()
        if not dags:
            t = self._scene.addText("No computations to build a DAG from.",
                                    QFont("Consolas", 11))
            t.setDefaultTextColor(QColor("#6b7280"))
            return
        y = 0.0
        for dag in dags:
            y += self._layout_block(dag, y) + 56
        rect = self._scene.itemsBoundingRect()
        rect.adjust(-40, -40, 40, 40)
        self._scene.setSceneRect(rect)
        self.resetTransform()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _layout_block(self, dag, y0):
        nodes = dag.nodes
        if not nodes:
            return 0

       
        level = {}
        def lvl(n):
            if n.nid in level:
                return level[n.nid]
            level[n.nid] = 0 if n.is_leaf() else 1 + max(lvl(n.left), lvl(n.right))
            return level[n.nid]
        for n in nodes:
            lvl(n)
        maxlvl = max(level.values())

        by_level = {}
        for n in nodes:
            by_level.setdefault(level[n.nid], []).append(n)

      
        x = {}
        for i, n in enumerate(by_level.get(0, [])):
            x[n.nid] = i * self.XGAP
        for L in range(1, maxlvl + 1):
            for n in by_level.get(L, []):
                x[n.nid] = (x[n.left.nid] + x[n.right.nid]) / 2
            row = sorted(by_level.get(L, []), key=lambda n: x[n.nid])
            for j in range(1, len(row)):
                if x[row[j].nid] < x[row[j - 1].nid] + self.XGAP:
                    x[row[j].nid] = x[row[j - 1].nid] + self.XGAP

        header_h = 50        
        for n in nodes:
            n._dx = x[n.nid]
            n._dy = y0 + header_h + (maxlvl - level[n.nid]) * self.YGAP

     
        hdr = self._scene.addText(f"Basic Block  B{dag.block_index}",
                                  QFont("Consolas", 10, QFont.Weight.Bold))
        hdr.setDefaultTextColor(QColor("#facc15"))
        hdr.setPos(min(x.values()) - 28, y0)

   
        pen = QPen(QColor(self.C_EDGE)); pen.setWidthF(1.7)
        for n in nodes:
            if n.is_leaf():
                continue
            for child in (n.left, n.right):
                path = QPainterPath()
                x1, y1 = n._dx, n._dy + self.NODE_H / 2
                x2, y2 = child._dx, child._dy - self.NODE_H / 2
                path.moveTo(x1, y1)
                midy = (y1 + y2) / 2
                path.cubicTo(x1, midy, x2, midy, x2, y2)
                self._scene.addPath(path, pen)
        for n in nodes:
            self._draw_node(n)

        return header_h + (maxlvl + 1) * self.YGAP

    def _draw_node(self, n):
        leaf = n.is_leaf()
        fill, border, txt = self.C_LEAF if leaf else self.C_OP
        label = str(n.value) if leaf else str(n.op)

        w = max(self.NODE_W, 16 + len(label) * 10)
        h = self.NODE_H
        rect = QRectF(n._dx - w / 2, n._dy - h / 2, w, h)
        box = QPainterPath(); box.addRoundedRect(rect, 9, 9)
        self._scene.addPath(box, QPen(QColor(border), 2), QBrush(QColor(fill)))

        item = self._scene.addText(label, QFont("Consolas", 12, QFont.Weight.Bold))
        item.setDefaultTextColor(QColor(txt))
        br = item.boundingRect()
        item.setPos(n._dx - br.width() / 2, n._dy - br.height() / 2)

        
        cap = self._scene.addText(str(n.nid), QFont("Consolas", 8, QFont.Weight.Bold))
        cap.setDefaultTextColor(QColor("#7dd3fc"))
        cb = cap.boundingRect()
        cap.setPos(n._dx - cb.width() / 2, n._dy - h / 2 - cb.height() + 2)

       
        if n.labels:
            tag = self._scene.addText("← " + ", ".join(n.labels),
                                      QFont("Consolas", 8, QFont.Weight.Bold))
            tag.setDefaultTextColor(QColor("#fb923c"))
            tb = tag.boundingRect()
            tag.setPos(n._dx + w / 2 + 4, n._dy - tb.height() / 2)



class CrystalCompilerGUI(QMainWindow):


    def __init__(self):
        super().__init__()
        self._last_tree_root = None
        self._worker = None        
        self._loading_dots = 0
        self.setWindowTitle("💎 Crystal Compiler")
        self.resize(1500, 860)
        self._apply_stylesheet()
        self._build_ui()
        self._connect_events()
        self._select_phase(0)        
        self.status.showMessage("Ready • Crystal Compiler Initialized")
    
        self._prewarm_worker = ParserWorker("_PREWARM", [], parent=self)
        self._prewarm_worker.done.connect(self._on_prewarm_done)
        self._prewarm_worker.start()

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

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 6, 10, 6)
        root_layout.setSpacing(6)

        title = QLabel("💎 Crystal Compiler")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size:26px;font-weight:bold;color:{ACCENT};padding:4px;")
        root_layout.addWidget(title)

        subtitle = QLabel("LR(0) • SLR(1) • CLR(1) • LL(1) • Lexer • Parse Tree • Crystal Language")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color:{MUTED};font-size:11px;margin-bottom:4px;")
        root_layout.addWidget(subtitle)

        root_layout.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.addWidget(self._build_editor_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([480, 900])
        root_layout.addWidget(splitter, 1)

        self.status = QStatusBar()
        self.status.setStyleSheet(f"background-color:{PANEL_BG};color:{MUTED};")
        self.setStatusBar(self.status)

    def _build_toolbar(self):
        """Two-row phased toolbar:  Row 1 = the 6 compiler phases,
        Row 2 = the actions belonging to the currently selected phase."""

        def btn(label, color):
            b = QPushButton(label)
            b.setStyleSheet(f"background-color:{color};")
            return b

        self.tokens_btn   = btn(" Tokens",            "#1f6feb")
        self.symtab_btn   = btn(" Symbol Table",      "#0e7490")
        self.errors_btn   = btn(" Errors",             "#b91c1c")

        self.lr0_btn      = btn("LR(0)",                "#7c3aed")
        self.slr1_btn     = btn("SLR(1)",               "#2563eb")
        self.clr1_btn     = btn("CLR(1)",               "#0891b2")
        self.ll1_btn      = btn("LL(1)",                "#059669")
        self.first_btn    = btn("FIRST",                "#ea580c")
        self.follow_btn   = btn("FOLLOW",               "#dc2626")
        self.tree_btn     = btn(" Parse Tree",        "#db6d28")

        self.semantics_btn = btn(" Semantics (SDD result)",  "#7e22ce")
        self.annot_btn     = btn(" Annotated Tree",   "#9333ea")
        self.sddrules_btn  = btn(" SDD Rules (definition)", "#7c3aed")

        self.compile_btn  = btn("Three-Address Code", "#238636")
        self.dag_btn      = btn(" DAG",               "#0d9488")
        self.backpatch_btn = btn(" Backpatching",     "#65a30d")

        self.opt_btn      = btn(" Optimize (machine-independent)", "#be123c")

        self.asm_btn      = btn(" Assembly + Peephole", "#0f766e")

        self._phases = [
            ("1 · Lexical",      "#1f6feb",
                [self.tokens_btn, self.symtab_btn, self.errors_btn]),
            ("2 · Syntax",       "#2563eb",
                [self.lr0_btn, self.slr1_btn, self.clr1_btn, self.ll1_btn,
                 self.first_btn, self.follow_btn, self.tree_btn]),
            ("3 · Semantic",     "#7e22ce",
                [self.semantics_btn, self.annot_btn, self.sddrules_btn]),
            ("4 · Intermediate", "#238636",
                [self.compile_btn, self.dag_btn, self.backpatch_btn]),
            ("5 · Optimization", "#be123c",
                [self.opt_btn]),
            ("6 · Code Gen",     "#0f766e",
                [self.asm_btn]),
        ]

        self._phase_buttons = []
        phase_row = QHBoxLayout()
        phase_row.setSpacing(6)
        for i, (label, color, _actions) in enumerate(self._phases):
            pb = QPushButton(label)
            pb.setCheckable(True)
            pb.setStyleSheet(self._phase_style(color, active=False))
            pb._color = color
            pb.clicked.connect(lambda _checked, idx=i: self._select_phase(idx))
            phase_row.addWidget(pb)
            self._phase_buttons.append(pb)
        phase_row.addStretch()

        self.examples_btn = QPushButton("📋 Code Examples")
        self.examples_btn.setStyleSheet(
            "background-color:#a16207;color:white;border-radius:8px;"
            "padding:8px 16px;font-size:13px;font-weight:bold;"
        )
        self.examples_btn.clicked.connect(self._show_examples_menu)
        phase_row.addWidget(self.examples_btn)

        self._sub_row = QHBoxLayout()
        self._sub_row.setSpacing(6)
        self._sub_row.addStretch()

        outer = QVBoxLayout()
        outer.setSpacing(5)
        outer.addLayout(phase_row)
        outer.addLayout(self._sub_row)
        return outer

    def _phase_style(self, color, active):
        if active:
            return (f"background-color:{color};color:white;border-radius:8px;"
                    f"padding:8px 16px;font-size:13px;font-weight:bold;"
                    f"border:2px solid white;")
        return (f"background-color:{color};color:#e6edf3;border-radius:8px;"
                f"padding:8px 16px;font-size:13px;font-weight:bold;opacity:0.85;")

    def _select_phase(self, index):
        """Show the action buttons belonging to the selected phase in row 2."""

        for i, pb in enumerate(self._phase_buttons):
            pb.setChecked(i == index)
            pb.setStyleSheet(self._phase_style(pb._color, active=(i == index)))


        while self._sub_row.count():
            item = self._sub_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        for b in self._phases[index][2]:
            b.setParent(None)
            b.show()
            self._sub_row.addWidget(b)
        self._sub_row.addStretch()

    def _build_editor_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(" Crystal Source Code")
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

    def _build_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

   
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

    
        tok_tab = QWidget()
        tok_layout = QVBoxLayout(tok_tab)
        tok_layout.setContentsMargins(6, 6, 6, 6)

        
        self.summary_frame = QWidget()
        self.summary_frame.setStyleSheet(f"QWidget{{background-color:{DARK_BG};}}")
        self.summary_layout = QHBoxLayout(self.summary_frame)
        self.summary_layout.setContentsMargins(0, 0, 0, 4)
        self.summary_layout.setSpacing(6)
        self.summary_layout.addStretch()
        tok_layout.addWidget(self.summary_frame)

        self.token_table = self._make_table(["Category", "Type", "Value"])
        tok_layout.addWidget(self.token_table)
        self.tabs.addTab(tok_tab, " Tokens")

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

        pt_split = QSplitter(Qt.Orientation.Vertical)
        pt_split.setHandleWidth(4)
        pt_split.addWidget(self.parse_table_widget)

        dfa_container = QWidget()
        dfa_box = QVBoxLayout(dfa_container)
        dfa_box.setContentsMargins(0, 6, 0, 0)
        dfa_box.setSpacing(2)

        self.dfa_label = QLabel(" DFA — Canonical Collection of LR Items")
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
        self.tabs.addTab(ptab_tab, "Parse Table")

   
        tree_tab = QWidget()
        tree_layout = QVBoxLayout(tree_tab)
        tree_layout.setContentsMargins(6, 6, 6, 6)

        tree_lbl = QLabel(" Derivation (Parse) Tree — graphical")
        tree_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;"
        )
        tree_layout.addWidget(tree_lbl)

        hint = QLabel("scroll = zoom  •  drag = pan")
        hint.setStyleSheet(f"color:{MUTED};font-size:10px;padding-bottom:2px;")
        tree_layout.addWidget(hint)

        self.tree_stack = QStackedWidget()

        self.tree_graph = TreeGraphView()
        self.tree_stack.addWidget(self.tree_graph)      

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
        self.tree_stack.addWidget(self.tree_view)       

        tree_layout.addWidget(self.tree_stack)
        self.tabs.addTab(tree_tab, " Parse Tree")

      
        syn_tab = QWidget()
        syn_layout = QVBoxLayout(syn_tab)
        syn_layout.setContentsMargins(6, 6, 6, 6)

        syn_lbl = QLabel(" Semantics Analysis — SDD Annotated AST")
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
        self.tabs.addTab(syn_tab, " Semantics")

        self.annot_tab = QWidget()
        annot_layout = QVBoxLayout(self.annot_tab)
        annot_layout.setContentsMargins(6, 6, 6, 6)

        self.annot_label = QLabel(" Semantic Annotated Tree — node.attribute = value : type")
        self.annot_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#c084fc;padding-bottom:4px;"
        )
        annot_layout.addWidget(self.annot_label)

        ahint = QLabel("each node shows its synthesised value (= …)  •  scroll = zoom  •  drag = pan")
        ahint.setStyleSheet(f"color:{MUTED};font-size:10px;padding-bottom:2px;")
        annot_layout.addWidget(ahint)

        self.annot_graph = TreeGraphView()
        annot_layout.addWidget(self.annot_graph)
        self.tabs.addTab(self.annot_tab, " Annotated Tree")

        self.sdd_tab = QWidget()
        sdd_layout = QVBoxLayout(self.sdd_tab)
        sdd_layout.setContentsMargins(6, 6, 6, 6)
        self.sdd_label = QLabel(" SDD Rules — S-attributed (LR) + L-attributed (LL1)")
        self.sdd_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#c084fc;padding-bottom:4px;"
        )
        sdd_layout.addWidget(self.sdd_label)
        self.sdd_view = self._make_code_view(
            "Click the SDD Rules button (Phase 3) to view the formal SDD."
        )
        sdd_layout.addWidget(self.sdd_view)
        self.tabs.addTab(self.sdd_tab, " SDD Rules")

        sym_tab = QWidget()
        sym_layout = QVBoxLayout(sym_tab)
        sym_layout.setContentsMargins(6, 6, 6, 6)

        sym_lbl = QLabel(" Symbol Table — Identifiers")
        sym_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;color:{ACCENT};padding-bottom:4px;"
        )
        sym_layout.addWidget(sym_lbl)

        self.symbol_table = self._make_table(
            ["Name", "Data Type", "Scope", "Additional Info"]
        )
        sym_layout.addWidget(self.symbol_table)
        self.tabs.addTab(sym_tab, " Symbol Table")

        err_tab = QWidget()
        err_layout = QVBoxLayout(err_tab)
        err_layout.setContentsMargins(6, 6, 6, 6)

        err_lbl = QLabel(" Errors — Lexical • Syntax • Semantic")
        err_lbl.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#f87171;padding-bottom:4px;"
        )
        err_layout.addWidget(err_lbl)

        self.error_table = self._make_table(
            ["Phase", "Line", "Col", "Value", "Description"]
        )
        err_layout.addWidget(self.error_table)
        self.tabs.addTab(err_tab, "⚠ Errors")

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

        tables_container = QWidget()
        tables_row = QHBoxLayout(tables_container)
        tables_row.setContentsMargins(0, 6, 0, 0)
        tables_row.setSpacing(8)

        quad_box = QVBoxLayout()
        quad_box.setSpacing(2)
        quad_lbl = QLabel("Quadruples  (op, arg1, arg2, result)")
        quad_lbl.setStyleSheet("color:#22d3ee;font-size:11px;font-weight:bold;")
        quad_box.addWidget(quad_lbl)
        self.quad_table = self._make_table(["#", "op", "arg1", "arg2", "result"])
        quad_box.addWidget(self.quad_table)
        tables_row.addLayout(quad_box)

        trip_box = QVBoxLayout()
        trip_box.setSpacing(2)
        trip_lbl = QLabel("Triples  (op, arg1, arg2 — temps become (i) refs)")
        trip_lbl.setStyleSheet("color:#facc15;font-size:11px;font-weight:bold;")
        trip_box.addWidget(trip_lbl)
        self.triple_table = self._make_table(["index", "op", "arg1", "arg2"])
        trip_box.addWidget(self.triple_table)
        tables_row.addLayout(trip_box)

        icg_split.addWidget(tables_container)

        icg_split.setStretchFactor(0, 3)
        icg_split.setStretchFactor(1, 2)
        icg_split.setSizes([420, 300])
        icg_layout.addWidget(icg_split, 1)
        self.tabs.addTab(self.icg_tab, "Intermediate Code")

        self.dag_tab = QWidget()
        dag_layout = QVBoxLayout(self.dag_tab)
        dag_layout.setContentsMargins(6, 6, 6, 6)
        self.dag_label = QLabel(" DAG — graphical (common sub-expressions merged)")
        self.dag_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#2dd4bf;padding-bottom:4px;"
        )
        dag_layout.addWidget(self.dag_label)

        dhint = QLabel("green = leaf (var/const)   •   purple = operator   •   "
                       "← shows which variables hold a node   •   scroll = zoom, drag = pan")
        dhint.setStyleSheet(f"color:{MUTED};font-size:10px;padding-bottom:2px;")
        dag_layout.addWidget(dhint)

        self.dag_graph = DagGraphView()
        dag_layout.addWidget(self.dag_graph)
        self.tabs.addTab(self.dag_tab, " DAG")

        self.bp_tab = QWidget()
        bp_layout = QVBoxLayout(self.bp_tab)
        bp_layout.setContentsMargins(6, 6, 6, 6)
        self.bp_label = QLabel(" Backpatching — one-pass jump code")
        self.bp_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#a3e635;padding-bottom:4px;"
        )
        bp_layout.addWidget(self.bp_label)
        self.bp_view = self._make_code_view(
            "Click “ Backpatching” to generate jump code in one pass "
            "with truelist / falselist / backpatch."
        )
        bp_layout.addWidget(self.bp_view)
        self.tabs.addTab(self.bp_tab, " Backpatching")

        self.opt_tab = QWidget()
        opt_layout = QVBoxLayout(self.opt_tab)
        opt_layout.setContentsMargins(6, 6, 6, 6)

        self.opt_label = QLabel(" Code Optimization — Machine-Independent")
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
            '“ Code Optimization” to build basic blocks, the control-flow '
            'graph (PFG), detect loops, and apply machine-independent '
            'optimizations.</p>'
        )
        opt_layout.addWidget(self.opt_view, 1)
        self.tabs.addTab(self.opt_tab, " Optimization")

        self.asm_tab = QWidget()
        asm_layout = QVBoxLayout(self.asm_tab)
        asm_layout.setContentsMargins(6, 6, 6, 6)

        asm_head = QHBoxLayout()
        self.asm_label = QLabel(" Assembly Code — x86 (MASM / emu8086)")
        self.asm_label.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#2dd4bf;padding-bottom:4px;"
        )
        asm_head.addWidget(self.asm_label)
        asm_head.addStretch()
        self.save_asm_btn = QPushButton(" Save .asm")
        self.save_asm_btn.setStyleSheet("background-color:#30363d;color:white;"
                                        "border-radius:6px;padding:3px 10px;font-size:11px;")
        asm_head.addWidget(self.save_asm_btn)
        asm_layout.addLayout(asm_head)

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

        self._last_asm_text = ""    

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

    def _make_code_view(self, placeholder=""):
        """A read-only monospace HTML view (for TAC / DAG / backpatch / asm)."""
        v = QTextEdit()
        v.setReadOnly(True)
        v.setStyleSheet(f"""
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
        if placeholder:
            v.setHtml(f'<p style="color:#6b7280;font-family:Consolas;">{placeholder}</p>')
        return v

    # =========================================================================
    # EVENT WIRING
    # =========================================================================

    def _connect_events(self):
        # Phase 1 — Lexical
        self.tokens_btn.clicked.connect(self.load_tokens)
        self.symtab_btn.clicked.connect(self.show_symbol_tab)
        self.errors_btn.clicked.connect(self.show_errors_tab)
        # Phase 2 — Syntax
        self.lr0_btn.clicked.connect(self.run_lr0)
        self.slr1_btn.clicked.connect(self.run_slr)
        self.clr1_btn.clicked.connect(self.run_clr)
        self.ll1_btn.clicked.connect(self.run_ll1)
        self.first_btn.clicked.connect(self.run_first)
        self.follow_btn.clicked.connect(self.run_follow)
        self.tree_btn.clicked.connect(self.show_current_tree)
        # Phase 3 — Semantic
        self.semantics_btn.clicked.connect(self.run_syntax)
        self.annot_btn.clicked.connect(self.run_annot)
        self.sddrules_btn.clicked.connect(self.show_sdd_rules)
        # Phase 4 — Intermediate Code
        self.compile_btn.clicked.connect(self.run_icg)
        self.dag_btn.clicked.connect(self.run_dag)
        self.backpatch_btn.clicked.connect(self.run_backpatch)
        # Phase 5 — Optimization
        self.opt_btn.clicked.connect(self.run_opt)
        # Phase 6 — Code Generation
        self.asm_btn.clicked.connect(self.run_asm)
        self.save_asm_btn.clicked.connect(self.save_assembly)

        # Open / Save moved off the toolbar — available via Ctrl+O / Ctrl+S
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self.open_file)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save_file)

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

    def _clear_dfa(self, title=""):
        """Non-LR mode with no automaton to show — explanatory note."""
        self.dfa_label.setText(" DFA / Automaton")
        msg = (f"{title} has no item-set automaton to display.<br>"
               "Run LR(0) / SLR(1) / CLR(1) for the LR DFA, or LL(1) for "
               "the top-down transition diagrams.")
        self.dfa_view.setHtml(
            f'<p style="color:#6b7280;font-family:Consolas;font-size:12px;">{msg}</p>'
        )

    def _show_ll1_transition_diagrams(self):
        """
        Top-down 'DFA' for the predictive parser: one transition diagram per
        non-terminal (states + symbol-labelled edges), the LL(1) equivalent of
        the LR item-set automaton.
        """
        diagrams = self._get_engine().transition_diagrams()

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        def sym_html(sym):
            if sym == EPS:
                return '<span style="color:#a78bfa;font-weight:bold;">ε</span>'
            if sym in GRAMMAR:          # non-terminal
                return f'<span style="color:#67e8f9;">&lt;{esc(sym)}&gt;</span>'
            return f'<span style="color:#4ade80;font-weight:bold;">{esc(sym)}</span>'

        def state_html(nt, sid, start, final):
            mark = ""
            if sid == start:
                mark = ' <span style="color:#22d3ee;">▸start</span>'
            if sid == final:
                mark = ' <span style="color:#fb923c;">((final))</span>'
            return (f'<span style="color:#facc15;font-weight:bold;">{esc(nt)}{sid}</span>'
                    + mark)

        lines = []
        for nt, d in diagrams.items():
            start, final = d["start"], d["final"]
            lines.append(
                f'<div style="margin:8px 0 2px 0;">'
                f'<span style="color:#c084fc;font-weight:bold;background:#1e293b;'
                f'padding:1px 8px;border-radius:4px;">&lt;{esc(nt)}&gt;</span>'
                f'<span style="color:#475569;">   start </span>'
                f'<span style="color:#22d3ee;">{esc(nt)}{start}</span>'
                f'<span style="color:#475569;">,  final </span>'
                f'<span style="color:#fb923c;">{esc(nt)}{final}</span></div>'
            )
            for (src, sym, dst) in d["edges"]:
                lines.append(
                    f'<div style="margin-left:18px;line-height:1.5;">'
                    f'<span style="color:#facc15;">{esc(nt)}{src}</span>'
                    f'<span style="color:#475569;"> ──[ </span>{sym_html(sym)}'
                    f'<span style="color:#475569;"> ]──▶ </span>'
                    f'<span style="color:#facc15;">{esc(nt)}{dst}</span>'
                    + (' <span style="color:#fb923c;">((final))</span>'
                       if dst == final else "")
                    + '</div>'
                )

        n_states = sum(len(d["states"]) for d in diagrams.values())
        n_edges  = sum(len(d["edges"]) for d in diagrams.values())
        self.dfa_label.setText(
            f" Top-Down DFA — LL(1) Transition Diagrams "
            f"({len(diagrams)} non-terminals, {n_states} states, {n_edges} edges)"
        )
        body = "\n".join(lines)
        self.dfa_view.setHtml(
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:12px;background:#0d1117;color:#a5f3fc;">{body}</div>'
        )
        self.dfa_view.verticalScrollBar().setValue(0)

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

            for sym, dst in sorted(out.get(i, [])):
                lines.append(
                    f'<div style="margin:0 0 0 30px;line-height:1.4;">'
                    f'<span style="color:#475569;">goto on </span>'
                    f'<span style="color:#4ade80;font-weight:bold;">{esc(sym)}</span>'
                    f'<span style="color:#475569;"> → </span>'
                    f'<span style="color:#fb923c;font-weight:bold;">I{dst}</span></div>'
                )

        self.dfa_label.setText(
            f" {title} DFA — {len(states)} states, {len(trans)} transitions"
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
        self.tree_stack.setCurrentIndex(1)        # show the text error card
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
            "ANNOT": "Annotated Tree",
            "ICG": "Intermediate Code", "DAG": "DAG",
            "BACKPATCH": "Backpatching", "OPT": "Code Optimization",
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
        for b in (self.compile_btn, self.dag_btn, self.backpatch_btn,
                  self.opt_btn, self.asm_btn, self.semantics_btn, self.annot_btn,
                  self.lr0_btn, self.slr1_btn, self.clr1_btn, self.ll1_btn,
                  self.first_btn, self.follow_btn, self.tree_btn):
            b.setEnabled(enabled)

    def _on_worker_done(self, mode: str, result: dict):
        self._set_buttons_enabled(True)

        labels = {
            "LR0": "LR(0)", "SLR": "SLR(1)",
            "CLR": "CLR(1)", "LL1": "LL(1)", "SYNTAX": "Syntax",
            "ANNOT": "Annotated Tree",
            "ICG": "Intermediate Code", "DAG": "DAG",
            "BACKPATCH": "Backpatching", "OPT": "Code Optimization",
            "ASM": "Assembly Code",
        }
        name = labels.get(mode, mode)

        # ── Show parse table (LR modes) ──
        if "table" in result:
            ACTION, GOTO, states, conflicts = result["table"]
            self._show_lr_table(ACTION, GOTO, states, conflicts, name)

        # ── Show DFA: LR item-set automaton, or LL(1) transition diagrams ──
        if "dfa" in result:
            states, trans, dfa_mode = result["dfa"]
            self._show_dfa(states, trans, name)
        elif mode == "LL1":
            self._show_ll1_transition_diagrams()
        elif mode == "SYNTAX":
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
            elif mode == "DAG":
                self._show_dag(result.get("dag_blocks", []))
                self.status.showMessage(
                    f"DAG built — {len(result.get('dag_blocks', []))} basic block(s)"
                )
            elif mode == "BACKPATCH":
                instrs, log = result.get("bp", ([], []))
                self._show_backpatch(instrs, log)
                self.status.showMessage(
                    f"Backpatching complete — {len(instrs)} quad(s), "
                    f"{len(log)} list operation(s)"
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
                self.status.showMessage("Register-machine assembly generated ✔")
            elif mode == "SYNTAX":
                html = self._syntax_to_html(tree)
                self.syntax_view.setHtml(html)
                self.syntax_view.verticalScrollBar().setValue(0)
                self.tabs.setCurrentIndex(3)
                self.status.showMessage("Syntax Analysis complete — SDD annotated AST shown")
            elif mode == "ANNOT":
                self._show_annotated_tree(tree)
                self.status.showMessage(
                    "Semantic Annotated Tree built — nodes decorated with values"
                )
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
    def run_annot(self):  self._start_worker("ANNOT")

    def show_sdd_rules(self):
        """Render the formal SDD specification (sdd_rules.py) into its tab."""
        import sdd_rules as sdd

        def esc(x):
            return (str(x).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        def head(t, c):
            return (f'<div style="color:{c};font-weight:bold;font-size:14px;'
                    f'margin:14px 0 6px 0;border-bottom:1px solid #1e293b;'
                    f'padding-bottom:3px;">{esc(t)}</div>')

        out = []
        out.append('<div style="color:#a78bfa;font-weight:bold;font-size:15px;'
                   'margin-bottom:4px;">SYNTAX-DIRECTED DEFINITIONS (SDD)</div>')
        out.append('<div style="color:#64748b;margin-bottom:6px;">'
                   'Running engine = semantic.py (L-attributed) &nbsp;•&nbsp; '
                   'this reference = both styles for all 4 parsers.</div>')

        # 1. Attributes
        out.append(head("1)  ATTRIBUTES  (non-terminal : kind)", "#22d3ee"))
        for nt, attrs in sdd.ATTRIBUTES.items():
            parts = []
            for n, k in attrs:
                col = "#fb923c" if k == "inherited" else "#4ade80"
                parts.append(f'<span style="color:{col};">{esc(n)} ({esc(k)})</span>')
            out.append(f'<div style="margin-left:12px;">'
                       f'<span style="color:#67e8f9;font-weight:bold;">{esc(nt)}</span>'
                       f'<span style="color:#475569;"> : </span>{", ".join(parts)}</div>')

        # 2. S-attributed
        out.append(head("2)  S-ATTRIBUTED SDD  —  LR(0) / SLR(1) / CLR(1) (bottom-up)",
                        "#4ade80"))
        for prod, rules in sdd.S_ATTRIBUTED_SDD:
            out.append(f'<div style="margin-top:5px;color:#a5f3fc;font-weight:bold;">'
                       f'{esc(prod)}</div>')
            for r in rules:
                out.append(f'<div style="margin-left:22px;color:#86efac;">'
                           f'{{ {esc(r)} }}</div>')

        # 3. L-attributed
        out.append(head("3)  L-ATTRIBUTED SDD  —  LL(1) (top-down)", "#fb923c"))
        for prod, rules in sdd.L_ATTRIBUTED_SDD:
            out.append(f'<div style="margin-top:5px;color:#a5f3fc;font-weight:bold;">'
                       f'{esc(prod)}</div>')
            for r in rules:
                out.append(f'<div style="margin-left:22px;color:#fdba74;">'
                           f'{{ {esc(r)} }}</div>')

        # 4. Parser mapping
        out.append(head("4)  WHICH PARSER USES WHICH SDD", "#c084fc"))
        for p, desc in sdd.PARSER_APPLICABILITY.items():
            out.append(f'<div style="margin-left:12px;margin-top:3px;">'
                       f'<span style="color:#facc15;font-weight:bold;">{esc(p)}</span>'
                       f'<span style="color:#94a3b8;"> — {esc(desc)}</span></div>')

        body = "\n".join(out)
        html = ('<div style="font-family:Consolas,monospace;'
                'font-size:12px;line-height:1.5;background:#0d1117;">'
                + body + "</div>")
        self.sdd_view.setHtml(html)
        self.sdd_view.verticalScrollBar().setValue(0)
        idx = self.tabs.indexOf(self.sdd_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)
        self.status.showMessage("SDD Rules shown — S-attributed (LR) + L-attributed (LL1)")

    def run_icg(self):    self._start_worker("ICG")
    def run_dag(self):    self._start_worker("DAG")
    def run_backpatch(self): self._start_worker("BACKPATCH")
    def run_opt(self):    self._start_worker("OPT")

    def run_asm(self):    self._start_worker("ASM")

    # ── Phase-1 helpers: run the lexer then show the relevant tab ─────────
    def show_symbol_tab(self):
        self.load_tokens()
        idx = self.tabs.indexOf(self.symbol_table.parentWidget())
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    def show_errors_tab(self):
        self.load_tokens()
        idx = self.tabs.indexOf(self.error_table.parentWidget())
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

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

    def _used_nonterminals(self, tokens):
        """
        Return the non-terminals that actually appear in the leftmost
        derivation of the editor's code (in order of first use).

        Runs the predictive LL(1) parser but only records which non-terminals
        get expanded — it stops gracefully at the first error / incomplete
        point, so it works while you are still typing.
        """
        engine = self._get_engine()
        table  = engine.build_ll1_table()
        tok_types = [t["type"] for t in tokens] + [END]

        used, seen = [], set()
        stack = [END, START]
        i, guard = 0, 0
        while stack and guard < 100000:
            guard += 1
            sym = stack.pop()
            if sym == END:
                break
            if sym in GRAMMAR:                      # non-terminal → expand
                if sym not in seen:
                    seen.add(sym); used.append(sym)
                prod = table.get((sym, tok_types[i]))
                if prod is None:
                    break                           # error / incomplete — stop here
                if prod != [EPS]:
                    for s in reversed(prod):
                        stack.append(s)
            else:                                   # terminal → must match
                if i < len(tok_types) and sym == tok_types[i]:
                    i += 1
                else:
                    break
        return used

    def run_first(self):
        engine = self._get_engine()
        first  = engine.first_sets()
        used   = self._used_nonterminals(self._get_tokens())
        self._show_set_table(first, "FIRST", only=used)
        self.tabs.setCurrentIndex(0)
        if used:
            self.status.showMessage(
                f"FIRST sets for YOUR code — {len(used)} non-terminal(s) used ✔"
            )
        else:
            self.status.showMessage("FIRST sets — full grammar (editor is empty)")

    def run_follow(self):
        engine = self._get_engine()
        follow = engine.follow_sets()
        used   = self._used_nonterminals(self._get_tokens())
        self._show_set_table(follow, "FOLLOW", only=used)
        self.tabs.setCurrentIndex(0)
        if used:
            self.status.showMessage(
                f"FOLLOW sets for YOUR code — {len(used)} non-terminal(s) used ✔"
            )
        else:
            self.status.showMessage("FOLLOW sets — full grammar (editor is empty)")

    def _show_set_table(self, data, title, only=None):
        """Populate token_table with { NT: set } data.

        If `only` is a non-empty list, show just those non-terminals (in that
        order) — used to restrict FIRST/FOLLOW to the editor's code.
        """
        self.token_table.clearContents()
        self.token_table.setColumnCount(2)
        self.token_table.setHorizontalHeaderLabels([f"{title}( Non-Terminal )", "Terminals"])
        self.token_table.horizontalHeader().setStretchLastSection(True)

        if only:
            rows = [(nt, data[nt]) for nt in only if nt in data]
        else:
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
            self.tree_stack.setCurrentIndex(1)
            self.tabs.setCurrentIndex(2)
            return

        # Draw the colourful graphical tree (page 0 of the stack).
        self.tree_graph.render_tree(root_node)
        self.tree_stack.setCurrentIndex(0)
        self.tabs.setCurrentIndex(2)

    def show_current_tree(self):
        if self._last_tree_root is None:
            self.status.showMessage("No parse tree yet — run a parser first")
        else:
            self._display_tree(self._last_tree_root)
            self.status.showMessage("Parse Tree displayed ✔")

    # =========================================================================
    # SEMANTIC ANNOTATED TREE  (parse tree decorated with synthesised values)
    # =========================================================================

    def _annot_to_html(self, root: Node) -> str:
        """
        Render the parse tree decorated with each node's synthesised VALUE
        attribute (node.aval), e.g.  Expr  { val = 30 }.
        """
        lines: list[str] = []

        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        def span(text, color, bold=False, italic=False):
            b  = "font-weight:bold;"  if bold   else ""
            it = "font-style:italic;" if italic else ""
            return f'<span style="color:{color};{b}{it}">{esc(text)}</span>'

        def val_badge(node):
            aval = getattr(node, "aval", None)
            if aval is None or aval == "":
                return ""
            return ("  " + f'<span style="color:#fde68a;background:#1e293b;'
                    f'border:1px solid #fde68a55;border-radius:4px;padding:0 6px;'
                    f'font-size:11px;">val = {esc(aval)}</span>')

        def node_label(node):
            is_real = node.is_terminal() and bool(node.tok_type)
            is_eps  = node.is_terminal() and not node.tok_type
            if is_real:
                lbl  = span(node.tok_type, "#4ade80", bold=True)
                lbl += "  " + span(f"«{node.name}»", "#7dd3fc")
            elif is_eps:
                lbl = span(node.name, "#475569", italic=True)
            else:
                lbl = span(node.name, "#67e8f9", bold=True)
            return lbl + val_badge(node)

        def render(node, prefix, is_last):
            connector = "└── " if is_last else "├── "
            lines.append(
                '<p style="margin:0;padding:0;line-height:1.6;white-space:nowrap;">'
                + span(prefix + connector, "#334155")
                + node_label(node)
                + "</p>"
            )
            if node.kids:
                child_prefix = prefix + ("    " if is_last else "│   ")
                for i, child in enumerate(node.kids):
                    render(child, child_prefix, i == len(node.kids) - 1)

        # Header + legend
        lines.append(
            '<p style="margin:0 0 8px 0;padding:6px 0;line-height:2;'
            'border-bottom:1px solid #1e293b;">'
            + span("SEMANTIC ANNOTATED PARSE TREE", "#c084fc", bold=True)
            + "  " + span("— each node synthesises a value", "#64748b", italic=True)
            + "</p>"
        )

        # Root
        lines.append(
            '<p style="margin:0;padding:0;line-height:1.6;">'
            + node_label(root) + "</p>"
        )
        for i, child in enumerate(root.kids):
            render(child, "", i == len(root.kids) - 1)

        body = "\n".join(lines)
        return (
            f'<div style="font-family:Consolas,\'Courier New\',monospace;'
            f'font-size:13px;background:#0d1117;color:#a5f3fc;padding:10px;">'
            + body + "</div>"
        )

    def _show_annotated_tree(self, root: Node):
        # Draw the colourful graphical SDD tree with each node's value.
        self.annot_graph.render_tree(root, annotated=True)
        idx = self.tabs.indexOf(self.annot_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

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

        # Collect Lexical + Syntax + Semantic errors and show them together.
        errors = self._collect_errors(all_tokens, tokens)
        self._show_errors(errors)

        # Symbol table is generated ONLY when the program has NO errors.
        # If any error exists, the symbol table is not built.
        if errors:
            self._clear_symbol_table(
                f"Symbol table not generated — fix the {len(errors)} error(s) "
                f"in the ⚠ Errors tab first."
            )
        else:
            self._show_symbol_table(tokens)

        # Always clear the old red highlight; re-highlight only if errors remain.
        self._clear_highlights()
        if not live:
            self.tabs.setCurrentIndex(0)
            if errors:
                # Highlight the first offending line in the editor.
                self._highlight_error_line(errors[0].get("line"))

        if errors:
            kinds = Counter(e["kind"] for e in errors)
            summary = ", ".join(f"{v} {k.lower()}" for k, v in kinds.items())
            self.status.showMessage(
                f"  {len(tokens)} tokens  •  {len(errors)} error(s) "
                f"({summary}) — see ⚠ Errors tab"
            )
        else:
            self.status.showMessage(
                f"  {len(tokens)} tokens  •  " +
                "  ".join(f"{k}: {v}" for k, v in counts.items())
            )

    def _collect_errors(self, all_tokens, valid_tokens):
        """
        Gather Lexical, Syntax and Semantic errors into one unified list,
        respecting compiler phase order:

          • Lexical  — illegal tokens (always reported).
          • Syntax   — unbalanced delimiters AND real grammar errors from the
                       LL(1) parser. Only reported if lexing is clean.
          • Semantic — undeclared / redeclared identifiers. Only reported if
                       the program is lexically and syntactically valid (so we
                       don't emit false 'undeclared' noise on broken code).
        """
        errors = []

        # ── Phase 1: Lexical ────────────────────────────────────────────
        lex = lexer_mod.lexical_errors(all_tokens)
        for e in lex:
            errors.append({
                "kind":  "Lexical",
                "line":  e.get("line"),
                "col":   e.get("col"),
                "value": e.get("value"),
                "error": e.get("error", "Lexical error"),
            })
        if lex:
            return self._sort_errors(errors)

        # ── Phase 2: Syntax ─────────────────────────────────────────────
        syntax = list(lexer_mod.syntax_errors(valid_tokens))   # unbalanced ((, {{, [[

        # Real grammar errors from the LL(1) parser (only when brackets balance).
        if not syntax:
            try:
                self._get_engine().ll1_parse(valid_tokens)
            except ValueError as pe:
                a   = pe.args
                msg = (a[0] if a else str(pe)).splitlines()[0]
                ln  = a[1] if len(a) > 1 else None
                col = a[2] if len(a) > 2 else None
                # find the offending token's value for the table, if any
                val = ""
                for t in valid_tokens:
                    if t.get("line") == ln and t.get("col") == col:
                        val = t.get("value", "")
                        break
                syntax.append({
                    "kind": "Syntax", "line": ln, "col": col,
                    "value": val, "error": msg,
                })

        errors += syntax
        if syntax:
            return self._sort_errors(errors)

        # ── Phase 3: Semantic ───────────────────────────────────────────
        errors += lexer_mod.semantic_errors(valid_tokens)
        return self._sort_errors(errors)

    @staticmethod
    def _sort_errors(errors):
        order = {"Lexical": 0, "Syntax": 1, "Semantic": 2}
        errors.sort(key=lambda e: (e.get("line") or 0, e.get("col") or 0,
                                   order.get(e["kind"], 9)))
        return errors

    def _show_symbol_table(self, tokens):
        """Fill the Symbol Table tab: Name | Data Type | Scope | Additional Info."""
        symbols = lexer_mod.build_symbol_table(tokens)

        self.symbol_table.clearContents()
        self.symbol_table.clearSpans()        # remove any span left by the error note
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

    def _clear_symbol_table(self, reason: str):
        """Empty the symbol table — used when the program has errors so the
        symbol table is NOT generated."""
        self.symbol_table.clearContents()
        self.symbol_table.clearSpans()
        self.symbol_table.setColumnCount(4)
        self.symbol_table.setHorizontalHeaderLabels(
            ["Name", "Data Type", "Scope", "Additional Info"]
        )
        self.symbol_table.setRowCount(1)
        item = QTableWidgetItem("⚠ " + reason)
        item.setForeground(QColor("#fca5a5"))
        item.setBackground(QColor(DARK_BG))
        self.symbol_table.setItem(0, 0, item)
        self.symbol_table.setSpan(0, 0, 1, 4)        # span across all columns
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
        width = len(str(len(quads)))           # for aligned line numbers
        lines = []
        for i, q in enumerate(quads, start=1):
            num = (f'<span style="color:#475569;">{str(i).rjust(width)}│ </span>')
            txt = self._esc(q.to_text())
            if q.op == "label":
                # Labels flush-left, highlighted.
                lines.append(
                    f'<div>{num}<span style="color:#facc15;font-weight:bold;">{txt}</span></div>'
                )
            elif q.op in ("func", "endfunc"):
                lines.append(
                    f'<div>{num}<span style="color:#c084fc;font-weight:bold;">{txt}</span></div>'
                )
            elif q.op in ("goto", "ifFalse", "if"):
                lines.append(f'<div>{num}<span style="color:#fb923c;">{txt}</span></div>')
            elif q.op in ("display", "read", "param", "return"):
                lines.append(f'<div>{num}<span style="color:#4ade80;">{txt}</span></div>')
            else:
                lines.append(f'<div>{num}<span style="color:#a5f3fc;">{txt}</span></div>')

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

        # ── Triples table ─────────────────────────────────────────────────
        import intermediate_code as icg
        triples = icg.to_triples(quads)
        self.triple_table.clearContents()
        self.triple_table.setColumnCount(4)
        self.triple_table.setHorizontalHeaderLabels(["index", "op", "arg1", "arg2"])
        self.triple_table.setRowCount(len(triples))
        self.triple_table.horizontalHeader().setStretchLastSection(True)

        for row, t in enumerate(triples):
            cells = [
                (f"({t['idx']})", "#8b949e"),
                (t["op"],         "#22d3ee"),
                (t["arg1"],       "#e2e8f0"),
                (t["arg2"],       "#fde68a"),     # (i) back-refs in amber
            ]
            for col, (text, fg) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(DARK_BG))
                self.triple_table.setItem(row, col, item)

        self.triple_table.resizeColumnsToContents()
        self.triple_table.horizontalHeader().setStretchLastSection(True)

        self.icg_label.setText(
            f"⚙ Intermediate Code — Three-Address Code (label-based) "
            f"— {len(quads)} instructions, {len(triples)} triples"
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

        # ── 5. Before / After code (with line numbers) ──────────────────
        out.append(h("5️⃣  RESULT  —  Before vs After", "#fb7185"))

        def numbered(quads):
            if not quads:
                return "(empty)"
            width = len(str(len(quads)))
            rows = []
            for i, q in enumerate(quads, start=1):
                rows.append(
                    f'<span style="color:#475569;">{str(i).rjust(width)}│ </span>'
                    + esc(q.to_text())
                )
            return "\n".join(rows)

        before_txt = numbered(res["original"])
        after_txt  = numbered(res["optimized"])
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
        """Render the generated assembly listing (clean code only — copyable)."""
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

        self.asm_label.setText("🖥 Assembly Code — x86 Intel syntax (emu8086 / MASM)")
        idx = self.tabs.indexOf(self.asm_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    # =========================================================================
    # DAG + BACKPATCHING DISPLAY
    # =========================================================================

    def _show_dag(self, dags):
        """Render the DAG of every basic block as a colourful graph."""
        self.dag_graph.render_dags(dags)
        n_cse = sum(len(d.common_subexpressions()) for d in dags)
        self.dag_label.setText(
            f" DAG — graphical ({len(dags)} basic block(s), "
            f"{n_cse} shared sub-expression(s) merged)"
        )
        idx = self.tabs.indexOf(self.dag_tab)
        if idx != -1:
            self.tabs.setCurrentIndex(idx)

    def _show_backpatch(self, instrs, log):
        """Render backpatched instructions (top) and the backpatch log."""
        def esc(s):
            return (str(s).replace("&", "&amp;")
                          .replace("<", "&lt;").replace(">", "&gt;"))

        code_lines = []
        for ins in instrs:
            body = esc(ins.text())
            if ins.kind in ("cond", "goto"):
                code_lines.append(
                    f'<div><span style="color:#facc15;">{ins.idx}:</span>  '
                    f'<span style="color:#fb923c;">{body}</span></div>'
                )
            else:
                code_lines.append(
                    f'<div><span style="color:#facc15;">{ins.idx}:</span>  '
                    f'<span style="color:#a5f3fc;">{body}</span></div>'
                )

        log_lines = [
            f'<div style="color:#a3e635;">• {esc(c)}</div>' for c in log
        ]

        html = (
            '<div style="font-family:Consolas,\'Courier New\',monospace;'
            'font-size:13px;line-height:1.5;background:#0d1117;">'
            '<div style="color:#5eead4;font-weight:bold;margin-bottom:4px;">'
            'Generated quads (targets backpatched)</div>'
            + "\n".join(code_lines)
            + '<div style="color:#5eead4;font-weight:bold;margin:10px 0 4px 0;'
              'border-top:1px solid #1e293b;padding-top:8px;">'
              'Backpatch list operations</div>'
            + ("\n".join(log_lines) if log_lines
               else '<div style="color:#64748b;">(no jump lists — straight-line code)</div>')
            + "</div>"
        )
        self.bp_view.setHtml(html)
        self.bp_view.verticalScrollBar().setValue(0)
        idx = self.tabs.indexOf(self.bp_tab)
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
    # CODE EXAMPLES  (insert a ready-made program into the editor)
    # =========================================================================

    def _show_examples_menu(self):
        """Pop up a menu of sample programs; the chosen one fills the editor."""
        try:
            from code_examples import EXAMPLES
        except Exception as e:
            QMessageBox.warning(self, "Examples", f"Could not load examples:\n{e}")
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color:{PANEL_BG}; color:{TEXT};
                     border:1px solid {BORDER}; padding:4px; }}
            QMenu::item {{ padding:6px 22px; border-radius:4px; }}
            QMenu::item:selected {{ background-color:#1f6feb33; color:white; }}
        """)
        for name, code in EXAMPLES:
            act = menu.addAction(name)
            act.triggered.connect(lambda _checked, c=code, n=name: self._insert_example(c, n))
        # show the menu just under the button
        menu.exec(self.examples_btn.mapToGlobal(
            self.examples_btn.rect().bottomLeft()))

    def _insert_example(self, code, name):
        """Replace the editor contents with the chosen sample program."""
        self.editor.setPlainText(code)
        self.status.showMessage(f"Inserted example: {name}  •  now click any phase to run it")

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
