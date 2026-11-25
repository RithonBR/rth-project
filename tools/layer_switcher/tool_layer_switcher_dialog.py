# -*- coding: utf-8 -*-
"""
Diálogo de configuração do RTH Layer Switcher.
"""
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QRadioButton, QTabWidget, QWidget, QPushButton,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QAbstractItemView, QDialogButtonBox, QFrame,
)
from qgis.core import Qgis, QgsProject

from .tool_layer_switcher import LayerGroup, MODE_SIMPLE, MODE_MULTI


# ---------------------------------------------------------------------------
# Painel de um grupo / Single-group panel
# ---------------------------------------------------------------------------

class _GroupPanel(QWidget):

    def __init__(self, group, parent=None):
        super(_GroupPanel, self).__init__(parent)
        self._group = group
        self._build_ui()
        self._populate_group_layers()

    def tr(self, msg):
        return QCoreApplication.translate('LayerSwitcherConfigDialog', msg)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Nome do grupo / Group name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(self.tr(u'Nome do grupo / Group name:')))
        self.edit_name = QLineEdit(self._group.name)
        self.edit_name.setPlaceholderText(self.tr(u'Ex: Satélites / Satellites, Talhões / Fields, Análises / Analyses...'))
        name_row.addWidget(self.edit_name)
        layout.addLayout(name_row)

        self._sep(layout)

        # Dica / Hint
        lbl_hint = QLabel(self.tr(
            u'Selecione camadas à esquerda e use ▶ para adicioná-las ao grupo. '
            u'Use ↑ ↓ para reordenar. Duplo-clique move a camada.'))
        lbl_hint.setStyleSheet('color:#555; font-size:10px;')
        lbl_hint.setWordWrap(True)
        layout.addWidget(lbl_hint)

        # Listas de camadas / Layer lists
        lists_row = QHBoxLayout()
        lists_row.setSpacing(4)

        # Esquerda — camadas do projeto / Left — project layers
        left_col = QVBoxLayout()
        lbl_proj = QLabel(self.tr(u'Camadas do Projeto / Project Layers'))
        lbl_proj.setStyleSheet('font-weight:bold; font-size:10px;')
        left_col.addWidget(lbl_proj)
        self.list_project = QListWidget()
        self.list_project.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_project.setSortingEnabled(False)
        self.list_project.itemDoubleClicked.connect(self._add_to_group)
        left_col.addWidget(self.list_project)
        lists_row.addLayout(left_col)

        # Centro — botões / Center — buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_col.addStretch()
        for label, tip, slot in [
            (u'▶', self.tr(u'Adicionar ao grupo / Add to group'),     self._add_to_group),
            (u'◀', self.tr(u'Remover do grupo / Remove from group'),  self._remove_from_group),
        ]:
            b = QPushButton(label)
            b.setFixedWidth(32)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            btn_col.addWidget(b)

        btn_col.addSpacing(12)

        for label, tip, slot in [
            (u'↑', self.tr(u'Mover para cima / Move up'),    self._move_up),
            (u'↓', self.tr(u'Mover para baixo / Move down'), self._move_down),
        ]:
            b = QPushButton(label)
            b.setFixedWidth(32)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            btn_col.addWidget(b)

        btn_col.addStretch()
        lists_row.addLayout(btn_col)

        # Direita — camadas do grupo / Right — group layers
        right_col = QVBoxLayout()
        lbl_grp = QLabel(self.tr(u'Camadas do Grupo / Group Layers'))
        lbl_grp.setStyleSheet('font-weight:bold; font-size:10px;')
        right_col.addWidget(lbl_grp)
        self.list_group = QListWidget()
        self.list_group.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_group.setSortingEnabled(False)
        self.list_group.itemDoubleClicked.connect(self._remove_from_group)
        right_col.addWidget(self.list_group)
        lists_row.addLayout(right_col)

        layout.addLayout(lists_row)

    # ------------------------------------------------------------------
    # População das listas / List population
    # ------------------------------------------------------------------

    def populate_project_layers(self):
        """Preenche a lista esquerda com camadas do projeto (exceto as já no grupo)."""
        existing_ids = self._current_group_ids()
        self.list_project.clear()
        layers = sorted(
            QgsProject.instance().mapLayers().values(),
            key=lambda l: l.name().lower()
        )
        for lyr in layers:
            if lyr.id() not in existing_ids:
                item = QListWidgetItem(lyr.name())
                item.setData(Qt.UserRole, lyr.id())
                self.list_project.addItem(item)

    def _populate_group_layers(self):
        self.list_group.clear()
        for lid in self._group.layer_ids:
            lyr = QgsProject.instance().mapLayer(lid)
            if lyr:
                item = QListWidgetItem(lyr.name())
                item.setData(Qt.UserRole, lid)
                self.list_group.addItem(item)

    def _current_group_ids(self):
        return {
            self.list_group.item(i).data(Qt.UserRole)
            for i in range(self.list_group.count())
        }

    # ------------------------------------------------------------------
    # Ações dos botões / Button actions
    # ------------------------------------------------------------------

    def _add_to_group(self, *_):
        for item in list(self.list_project.selectedItems()):
            new_item = QListWidgetItem(item.text())
            new_item.setData(Qt.UserRole, item.data(Qt.UserRole))
            self.list_group.addItem(new_item)
            self.list_project.takeItem(self.list_project.row(item))

    def _remove_from_group(self, *_):
        for item in list(self.list_group.selectedItems()):
            lid = item.data(Qt.UserRole)
            lyr = QgsProject.instance().mapLayer(lid)
            if lyr:
                new_item = QListWidgetItem(lyr.name())
                new_item.setData(Qt.UserRole, lid)
                self.list_project.addItem(new_item)
            self.list_group.takeItem(self.list_group.row(item))
        self.list_project.sortItems()

    def _move_up(self):
        rows = sorted(self.list_group.row(it) for it in self.list_group.selectedItems())
        if not rows or rows[0] == 0:
            return
        for row in rows:
            item = self.list_group.takeItem(row)
            self.list_group.insertItem(row - 1, item)
        for row in rows:
            self.list_group.item(row - 1).setSelected(True)

    def _move_down(self):
        rows = sorted(
            (self.list_group.row(it) for it in self.list_group.selectedItems()),
            reverse=True)
        if not rows or rows[0] == self.list_group.count() - 1:
            return
        for row in rows:
            item = self.list_group.takeItem(row)
            self.list_group.insertItem(row + 1, item)
        for row in sorted(rows):
            self.list_group.item(row + 1).setSelected(True)

    # ------------------------------------------------------------------
    # Leitura do estado da UI / Read UI state
    # ------------------------------------------------------------------

    def get_group(self):
        """Retorna um LayerGroup com o estado atual da UI."""
        layer_ids = [
            self.list_group.item(i).data(Qt.UserRole)
            for i in range(self.list_group.count())
        ]
        return LayerGroup(
            name      = self.edit_name.text().strip() or self.tr(u'Grupo / Group'),
            layer_ids = layer_ids,
        )


# ---------------------------------------------------------------------------
# Diálogo principal / Main dialog
# ---------------------------------------------------------------------------

class LayerSwitcherConfigDialog(QDialog):

    def __init__(self, iface, tool, parent=None):
        super(LayerSwitcherConfigDialog, self).__init__(parent)
        self.iface = iface
        self.tool  = tool
        self.setWindowTitle(self.tr(u'RTH Layer Switcher — Configurar Grupos / Configure Groups'))
        self.setMinimumSize(660, 500)
        self._build_ui()

    def tr(self, msg):
        return QCoreApplication.translate('LayerSwitcherConfigDialog', msg)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Modo / Mode ────────────────────────────────────────────────
        mode_box = QGroupBox(self.tr(u'Modo de Alternância / Switching Mode'))
        mode_layout = QVBoxLayout(mode_box)

        self.radio_simple = QRadioButton(
            self.tr(u'Simples — selecione 2+ camadas no painel e use o atalho / Simple — select 2+ layers in panel and use shortcut'))
        self.radio_multi = QRadioButton(
            self.tr(u'Múltiplos Grupos — configure grupos abaixo e use "Próximo Grupo" para alternar / Multi-Group — configure groups below and use "Next Group" to switch'))
        self.radio_simple.setChecked(True)

        lbl_tip = QLabel(self.tr(
            u'Dica: atribua atalhos de teclado em  Configurações → Atalhos do Teclado  '
            u'(procure por "RTH") / Tip: assign keyboard shortcuts in  Settings → Keyboard Shortcuts  (search "RTH")'))
        lbl_tip.setStyleSheet('color:#1a73e8; font-size:10px;')
        lbl_tip.setWordWrap(True)

        mode_layout.addWidget(self.radio_simple)
        mode_layout.addWidget(self.radio_multi)
        mode_layout.addWidget(lbl_tip)
        layout.addWidget(mode_box)

        # ── Abas de grupos / Group tabs ────────────────────────────────
        self._lbl_groups_disabled = QLabel(self.tr(
            u'ℹ  No modo Simples os grupos ficam salvos mas não são usados. '
            u'Selecione "Múltiplos Grupos" para editá-los. / '
            u'In Simple mode groups are saved but not used. Select "Multi-Group" to edit them.'))
        self._lbl_groups_disabled.setStyleSheet(
            'color:#888; font-size:10px; font-style:italic; padding:4px;')
        self._lbl_groups_disabled.setWordWrap(True)
        self._lbl_groups_disabled.setVisible(True)
        layout.addWidget(self._lbl_groups_disabled)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tab_widget.setEnabled(False)
        layout.addWidget(self.tab_widget)

        # ── Botão adicionar grupo / Add group button ───────────────────
        btn_row = QHBoxLayout()
        self._btn_add_group = QPushButton(self.tr(u'+ Adicionar Grupo / Add Group'))
        self._btn_add_group.setFixedWidth(220)
        self._btn_add_group.clicked.connect(self._add_group_tab)
        self._btn_add_group.setEnabled(False)
        btn_row.addWidget(self._btn_add_group)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Liga rádio buttons ao estado dos controles de grupo / Wire radio buttons to group controls state
        self.radio_simple.toggled.connect(self._on_mode_toggled)
        self.radio_multi.toggled.connect(self._on_mode_toggled)

        # ── Botões Apply / Close ───────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Apply).setText(self.tr(u'Aplicar / Apply'))
        btns.button(QDialogButtonBox.Close).setText(self.tr(u'Fechar / Close'))
        btns.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.hide)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # Recarga / Reload
    # ------------------------------------------------------------------

    def reload(self):
        """Sincroniza a UI com o estado atual da ferramenta."""
        mode = self.tool.get_mode()
        (self.radio_multi if mode == MODE_MULTI else self.radio_simple).setChecked(True)

        self.tab_widget.blockSignals(True)
        self.tab_widget.clear()
        self.tab_widget.blockSignals(False)

        for group in self.tool.get_groups():
            self._add_group_tab(group=group)

        # Destaca o grupo ativo / Highlight active group
        active_idx = self.tool.get_active_group_idx()
        if 0 <= active_idx < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(active_idx)

        self._on_mode_toggled()

    def _on_mode_toggled(self, *_):
        """Habilita/desabilita controles de grupo conforme o modo selecionado."""
        is_multi = self.radio_multi.isChecked()
        self.tab_widget.setEnabled(is_multi)
        self._btn_add_group.setEnabled(is_multi)
        self._lbl_groups_disabled.setVisible(not is_multi)

    # ------------------------------------------------------------------
    # Abas / Tabs
    # ------------------------------------------------------------------

    def _add_group_tab(self, checked=False, group=None):
        if not isinstance(group, LayerGroup):
            group = LayerGroup(
                name=self.tr(u'Grupo / Group {0}').format(self.tab_widget.count() + 1))

        panel = _GroupPanel(group, self)
        panel.populate_project_layers()

        idx = self.tab_widget.addTab(panel, group.name)
        self.tab_widget.setCurrentIndex(idx)

        panel.edit_name.textChanged.connect(
            lambda text, p=panel: self._sync_tab_title(p, text))

    def _sync_tab_title(self, panel, text):
        idx = self.tab_widget.indexOf(panel)
        if idx >= 0:
            self.tab_widget.setTabText(idx, text.strip() or u'…')

    def _on_tab_close_requested(self, idx):
        if self.tab_widget.count() <= 1:
            panel = self.tab_widget.widget(0)
            if panel:
                panel.edit_name.setText(self.tr(u'Grupo 1 / Group 1'))
                panel.list_group.clear()
                panel.populate_project_layers()
        else:
            self.tab_widget.removeTab(idx)

    # ------------------------------------------------------------------
    # Aplicar / Apply
    # ------------------------------------------------------------------

    def _on_apply(self):
        mode = MODE_MULTI if self.radio_multi.isChecked() else MODE_SIMPLE

        groups = []
        for i in range(self.tab_widget.count()):
            panel = self.tab_widget.widget(i)
            if panel:
                groups.append(panel.get_group())

        if not groups:
            groups = [LayerGroup()]

        self.tool.apply_config(mode, groups)

        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Layer Switcher: configuração salva / configuration saved'),
            level=Qgis.MessageLevel.Info, duration=3
        )
