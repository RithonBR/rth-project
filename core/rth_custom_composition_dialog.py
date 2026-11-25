# -*- coding: utf-8 -*-
"""
rth_custom_composition_dialog — Dialog para composição personalizada de bandas via drag-and-drop
rth_custom_composition_dialog — Dialog for custom band composition via drag-and-drop

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QFrame, QScrollArea, QWidget, QPushButton,
    QLineEdit, QMessageBox, QAbstractItemView,
)
from qgis.PyQt.QtCore import Qt, QMimeData, pyqtSignal

# ── Compat Qt5/Qt6 ────────────────────────────────────────────────────────────
# No Qt5 (QGIS 3), enums ficavam direto na classe: Qt.CopyAction, Qt.AlignCenter
# No Qt6 (QGIS 4), foram movidos para sub-namespaces: Qt.DropAction.CopyAction
# O try/except detecta qual versão está disponível em tempo de execução.
# Definimos constantes no topo do arquivo para não repetir o try/except em
# cada uso — se um deles falhar, o erro aparece na inicialização do plugin,
# não no meio de uma operação de drag-and-drop.
try:
    _COPY_ACTION      = Qt.DropAction.CopyAction
except AttributeError:
    _COPY_ACTION      = Qt.CopyAction

try:
    _SINGLE_SELECTION = QAbstractItemView.SelectionMode.SingleSelection
except AttributeError:
    _SINGLE_SELECTION = QAbstractItemView.SingleSelection

try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _ALIGN_TOP    = Qt.AlignmentFlag.AlignTop
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter
    _ALIGN_TOP    = Qt.AlignTop

try:
    _USER_ROLE = Qt.ItemDataRole.UserRole
except AttributeError:
    _USER_ROLE = Qt.UserRole

try:
    _MB_YES = QMessageBox.StandardButton.Yes
    _MB_NO  = QMessageBox.StandardButton.No
except AttributeError:
    _MB_YES = QMessageBox.Yes
    _MB_NO  = QMessageBox.No


# ── Lista de bandas disponíveis (lado esquerdo, arrastável) ──────────────────

class _BandList(QListWidget):
    # ==========================================================================
    # _BandList / _DropSlot / _ExtraDropArea — sistema de drag-and-drop Qt
    #
    # Como funciona o drag-and-drop no Qt:
    #   1. _BandList (fonte): setDragEnabled(True) + mimeData() — ao arrastar
    #      um item, Qt chama mimeData() para empacotar os dados numa QMimeData.
    #      Aqui empacotamos "band_key|||label" como texto simples.
    #
    #   2. _DropSlot / _ExtraDropArea (destinos): setAcceptDrops(True) +
    #      dragEnterEvent() para aceitar/recusar o drag visualmente +
    #      dropEvent() para extrair os dados do QMimeData e aplicar.
    #
    #   QMimeData é o "clipboard temporário" do drag: carrega os dados de A
    #   até B sem que A e B precisem se conhecer diretamente.
    #
    # Por que "band_key|||label" com separador triple-pipe?
    #   Precisamos passar 2 informações (chave interna da API + rótulo legível).
    #   O separador "|||" é improvável de aparecer em qualquer chave de banda,
    #   garantindo que o split('|||', 1) não quebre em casos reais.
    # ==========================================================================
    """Lista de bandas disponíveis com suporte a arrastar / Available bands list with drag support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(_SINGLE_SELECTION)
        self.setMinimumWidth(200)
        self.setStyleSheet(
            'QListWidget{border:1px solid #ddd;border-radius:3px;font-size:11px;}'
            'QListWidget::item{padding:5px 8px;}'
            'QListWidget::item:selected{background:#d6e8ff;color:#003366;}'
            'QListWidget::item:hover{background:#eef4ff;}')

    def mimeTypes(self):
        return ['text/plain']

    def mimeData(self, items):
        md = QMimeData()
        if items:
            key   = items[0].data(_USER_ROLE)
            label = items[0].text()
            # Formato: "band_key|||label legível" — separado no destino / Format split at drop target
            md.setText('{}|||{}'.format(key, label))
        return md

    def supportedDropActions(self):
        return _COPY_ACTION


# ── Slot de destino para uma banda R, G ou B ──────────────────────────────────

class _DropSlot(QFrame):
    """Slot que recebe drop de uma banda e exibe a atribuição / Slot receiving band drop and showing assignment."""

    changed = pyqtSignal()

    _EMPTY  = 'QFrame{{border:1px dashed #bbb;border-radius:4px;background:#fafafa;}}'
    _FILLED = 'QFrame{{border:1px solid {c};border-radius:4px;background:#f6fff8;}}'
    _HOVER  = 'QFrame{{border:2px solid {c};border-radius:4px;background:#eef6ff;}}'

    def __init__(self, slot_label, color_hex, parent=None):
        super().__init__(parent)
        self._color    = color_hex
        self._band_key = ''
        self.setAcceptDrops(True)
        self.setFixedHeight(46)
        self.setStyleSheet(self._EMPTY)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        self._lbl_slot = QLabel(slot_label)
        f = self._lbl_slot.font()
        f.setBold(True)
        f.setPointSize(13)
        self._lbl_slot.setFont(f)
        self._lbl_slot.setFixedWidth(18)
        self._lbl_slot.setStyleSheet('color:{};'.format(color_hex))
        lay.addWidget(self._lbl_slot)

        self._lbl_band = QLabel('Arraste uma banda aqui / Drag a band here')
        self._lbl_band.setStyleSheet('color:#bbb;font-style:italic;font-size:11px;')
        lay.addWidget(self._lbl_band, 1)

        self._btn_clear = QPushButton('✕')
        self._btn_clear.setFixedSize(20, 20)
        self._btn_clear.setVisible(False)
        self._btn_clear.setStyleSheet(
            'QPushButton{border:none;color:#aaa;font-size:11px;}'
            'QPushButton:hover{color:#e00;}')
        self._btn_clear.clicked.connect(self.clear_band)
        lay.addWidget(self._btn_clear)

    def set_band(self, key, label=''):
        self._band_key = key
        self._lbl_band.setText(label or key)
        self._lbl_band.setStyleSheet('color:#222;font-style:normal;font-size:11px;font-weight:bold;')
        self._btn_clear.setVisible(True)
        self.setStyleSheet(self._FILLED.format(c=self._color))
        self.changed.emit()

    def clear_band(self):
        self._band_key = ''
        self._lbl_band.setText('Arraste uma banda aqui / Drag a band here')
        self._lbl_band.setStyleSheet('color:#bbb;font-style:italic;font-size:11px;')
        self._btn_clear.setVisible(False)
        self.setStyleSheet(self._EMPTY)
        self.changed.emit()

    def band_key(self):
        return self._band_key

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            self.setStyleSheet(self._HOVER.format(c=self._color))
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._reset_style()

    def dropEvent(self, e):
        text = e.mimeData().text()
        if '|||' in text:
            key, label = text.split('|||', 1)
        else:
            key = label = text
        self.set_band(key, label)
        self._reset_style()

    def _reset_style(self):
        if self._band_key:
            self.setStyleSheet(self._FILLED.format(c=self._color))
        else:
            self.setStyleSheet(self._EMPTY)


# ── Área de drop para bandas extras de download ───────────────────────────────

class _ExtraDropArea(QScrollArea):
    """Área de drop para bandas adicionais (só no download) / Drop area for extra bands (download only)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setWidgetResizable(True)
        self.setMinimumHeight(80)
        self.setMaximumHeight(140)
        self._set_idle_style()

        self._inner  = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setAlignment(_ALIGN_TOP)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(4)

        self._empty = QLabel('Arraste bandas aqui / Drag bands here')
        self._empty.setAlignment(_ALIGN_CENTER)
        self._empty.setStyleSheet('color:#ccc;font-style:italic;font-size:11px;padding:16px;')
        self._layout.addWidget(self._empty)

        self.setWidget(self._inner)
        self._rows = []  # [(band_key, row_widget), ...]

    def _set_idle_style(self):
        self.setStyleSheet(
            'QScrollArea{border:1px dashed #ccc;border-radius:4px;background:#fafafa;}')

    def _set_hover_style(self):
        self.setStyleSheet(
            'QScrollArea{border:2px solid #0077cc;border-radius:4px;background:#eef6ff;}')

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            self._set_hover_style()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._set_idle_style()

    def dropEvent(self, e):
        text = e.mimeData().text()
        if '|||' in text:
            key, label = text.split('|||', 1)
        else:
            key = label = text
        self._add_band(key, label)
        self._set_idle_style()

    def _add_band(self, key, label):
        if key in [r[0] for r in self._rows]:
            return  # sem duplicatas / no duplicates
        self._empty.setVisible(False)

        row = QWidget()
        rl  = QHBoxLayout(row)
        rl.setContentsMargins(6, 3, 4, 3)
        rl.setSpacing(4)

        lbl = QLabel(label or key)
        lbl.setStyleSheet('font-size:11px;color:#333;')
        rl.addWidget(lbl, 1)

        btn = QPushButton('✕')
        btn.setFixedSize(18, 18)
        btn.setStyleSheet(
            'QPushButton{border:none;color:#aaa;font-size:10px;}'
            'QPushButton:hover{color:#e00;}')
        btn.clicked.connect(lambda _=False, r=row, k=key: self._remove_band(r, k))
        rl.addWidget(btn)

        row.setStyleSheet('background:#eef3fa;border-radius:3px;')
        self._layout.addWidget(row)
        self._rows.append((key, row))

    def _remove_band(self, row_widget, key):
        self._rows = [(k, r) for k, r in self._rows if k != key]
        row_widget.setParent(None)
        row_widget.deleteLater()
        if not self._rows:
            self._empty.setVisible(True)

    def extra_band_keys(self):
        """Retorna as chaves das bandas extras / Return extra band keys."""
        return [k for k, _ in self._rows]

    def set_initial_bands(self, keys, catalog):
        """Pré-preenche bandas (modo edição) / Pre-fill bands (edit mode)."""
        lookup = {k: lbl for k, lbl in catalog}
        for key in keys:
            self._add_band(key, lookup.get(key, key))


# ── Dialog principal ─────────────────────────────────────────────────────────

class CustomCompositionDialog(QDialog):
    """Dialog para criar ou editar composição personalizada de bandas /
    Dialog for creating or editing a custom band composition."""

    def __init__(self, collection_id, edit_name=None, parent=None):
        """
        :param collection_id: ID da coleção atual / Current collection ID
        :param edit_name: nome da composição a editar, ou None para criar / composition name to edit, or None to create
        """
        super().__init__(parent)
        self._collection_id = collection_id
        self._edit_name     = edit_name
        self._saved         = False
        self._deleted       = False

        from .rth_catalog import get_band_catalog, get_custom_compositions
        self._catalog     = get_band_catalog(collection_id)
        self._saved_comps = get_custom_compositions(collection_id)

        self.setWindowTitle('Composição Personalizada / Custom Composition')
        self.setMinimumSize(660, 500)
        self.setModal(True)

        self._build_ui()

        if edit_name:
            self._prefill_edit(edit_name)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Cabeçalho com ID da coleção / Header with collection ID
        lbl_header = QLabel('Coleção / Collection: <b>{}</b>'.format(self._collection_id))
        lbl_header.setStyleSheet('color:#555;font-size:11px;')
        root.addWidget(lbl_header)

        # ── Área principal ────────────────────────────────────────────────────
        main = QHBoxLayout()
        main.setSpacing(16)
        root.addLayout(main, 1)

        # Painel esquerdo — lista de bandas / Left panel — band list
        left = QVBoxLayout()
        left.setSpacing(4)

        lbl_avail = QLabel('Bandas disponíveis / Available bands:')
        f = lbl_avail.font()
        f.setBold(True)
        lbl_avail.setFont(f)
        lbl_avail.setStyleSheet('font-size:11px;')
        left.addWidget(lbl_avail)

        lbl_hint = QLabel('← Arraste para os slots → / ← Drag to slots →')
        lbl_hint.setStyleSheet('color:#aaa;font-size:10px;font-style:italic;')
        left.addWidget(lbl_hint)

        self._band_list = _BandList()
        for key, label in self._catalog:
            item = QListWidgetItem(label)
            item.setData(_USER_ROLE, key)
            self._band_list.addItem(item)
        left.addWidget(self._band_list, 1)
        main.addLayout(left, 1)

        # Painel direito — slots RGB + extras / Right panel — RGB slots + extras
        right = QVBoxLayout()
        right.setSpacing(8)

        lbl_rgb = QLabel('Composição RGB / RGB Composition:')
        fr = lbl_rgb.font()
        fr.setBold(True)
        lbl_rgb.setFont(fr)
        lbl_rgb.setStyleSheet('font-size:11px;')
        right.addWidget(lbl_rgb)

        self._slot_r = _DropSlot('R', '#cc2200')
        self._slot_g = _DropSlot('G', '#008833')
        self._slot_b = _DropSlot('B', '#0055cc')
        right.addWidget(self._slot_r)
        right.addWidget(self._slot_g)
        right.addWidget(self._slot_b)

        lbl_extra = QLabel('Extras — só download / Download only:')
        fe = lbl_extra.font()
        fe.setBold(True)
        lbl_extra.setFont(fe)
        lbl_extra.setStyleSheet('font-size:11px;margin-top:6px;')
        right.addWidget(lbl_extra)

        lbl_extra_hint = QLabel('Arraste bandas adicionais / Drag additional bands')
        lbl_extra_hint.setStyleSheet('color:#aaa;font-size:10px;font-style:italic;')
        right.addWidget(lbl_extra_hint)

        self._extra_area = _ExtraDropArea()
        right.addWidget(self._extra_area, 1)

        main.addLayout(right, 1)

        # ── Campo de nome ─────────────────────────────────────────────────────
        name_row = QHBoxLayout()
        lbl_name = QLabel('Nome / Name:')
        fn = lbl_name.font()
        fn.setBold(True)
        lbl_name.setFont(fn)
        lbl_name.setFixedWidth(90)
        name_row.addWidget(lbl_name)

        self._name_field = QLineEdit()
        self._name_field.setPlaceholderText(
            'Obrigatório para Salvar ★ / Required for Save ★')
        name_row.addWidget(self._name_field, 1)
        root.addLayout(name_row)

        # ── Botões de ação ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if self._edit_name:
            self._btn_delete = QPushButton('🗑  Excluir / Delete')
            self._btn_delete.setStyleSheet(
                'QPushButton{color:#cc0000;border:1px solid #cc0000;border-radius:4px;padding:4px 10px;font-size:11px;}'
                'QPushButton:hover{background:#fff0f0;}')
            self._btn_delete.clicked.connect(self._on_delete)
            btn_row.addWidget(self._btn_delete)

        btn_row.addStretch(1)

        btn_cancel = QPushButton('Cancelar / Cancel')
        btn_cancel.setStyleSheet(
            'QPushButton{border:1px solid #bbb;border-radius:4px;padding:4px 14px;font-size:11px;}'
            'QPushButton:hover{background:#f0f0f0;}')
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self._btn_save = QPushButton('★  Salvar / Save')
        self._btn_save.setEnabled(False)  # habilitado só quando nome preenchido / enabled only when name is filled
        self._btn_save.setStyleSheet(
            'QPushButton{background:#0077cc;color:white;border:none;border-radius:4px;'
            'padding:4px 16px;font-weight:bold;font-size:11px;}'
            'QPushButton:hover:enabled{background:#005fa3;}'
            'QPushButton:disabled{background:#aac8e8;}')
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_save)

        root.addLayout(btn_row)

        # Habilita Salvar somente quando o nome estiver preenchido
        # Enable Save only when the name field is filled
        self._name_field.textChanged.connect(
            lambda t: self._btn_save.setEnabled(bool(t.strip())))

    def _prefill_edit(self, edit_name):
        """Preenche os campos com a composição existente / Fill fields with existing composition."""
        self._name_field.setText(edit_name)
        lookup = {k: lbl for k, lbl in self._catalog}
        for comp in self._saved_comps:
            if comp.get('name') == edit_name:
                r_key = comp.get('r', '')
                g_key = comp.get('g', '')
                b_key = comp.get('b', '')
                if r_key:
                    self._slot_r.set_band(r_key, lookup.get(r_key, r_key))
                if g_key:
                    self._slot_g.set_band(g_key, lookup.get(g_key, g_key))
                if b_key:
                    self._slot_b.set_band(b_key, lookup.get(b_key, b_key))
                self._extra_area.set_initial_bands(comp.get('extra', []), self._catalog)
                break

    def _validate_rgb(self):
        """Valida se R, G e B foram atribuídos / Validate that R, G and B were assigned."""
        if not (self._slot_r.band_key() and self._slot_g.band_key() and self._slot_b.band_key()):
            QMessageBox.warning(
                self, 'RTH',
                'Atribua as bandas R, G e B antes de continuar.\n'
                'Assign R, G and B bands before continuing.')
            return False
        return True

    def _on_save(self):
        # QDialog tem dois modos de fechar: accept() (aceito/confirmado)
        # ou reject() (cancelado). Ambos fecham a janela, mas o código que
        # abriu o dialog pode distinguir entre eles via dialog.exec_() == QDialog.Accepted
        # ou dialog.was_saved(). Usamos self._saved = True antes de accept()
        # para que get_result() indique ao chamador o que realmente aconteceu.
        name = self._name_field.text().strip()
        if not name:
            QMessageBox.warning(
                self, 'RTH',
                'Digite um nome para a composição.\nEnter a name for the composition.')
            return
        if not self._validate_rgb():
            return
        self._saved = True
        self.accept()

    def _on_delete(self):
        reply = QMessageBox.question(
            self,
            'Excluir composição / Delete composition',
            'Excluir "{}"? Esta ação não pode ser desfeita.\n'
            'Delete "{}"? This action cannot be undone.'.format(
                self._edit_name, self._edit_name),
            _MB_YES | _MB_NO,
            _MB_NO)
        if reply == _MB_YES:
            self._deleted = True
            self.accept()

    def get_result(self):
        """Retorna o resultado da configuração / Return configuration result.

        :returns: dict com name, r, g, b, extra, saved, deleted
        :rtype: dict
        """
        return {
            'name':    self._name_field.text().strip(),
            'r':       self._slot_r.band_key(),
            'g':       self._slot_g.band_key(),
            'b':       self._slot_b.band_key(),
            'extra':   self._extra_area.extra_band_keys(),
            'saved':   self._saved,
            'deleted': self._deleted,
        }

    def was_saved(self):
        return self._saved

    def was_deleted(self):
        return self._deleted
