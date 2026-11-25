# -*- coding: utf-8 -*-
"""
RTH Layer Switcher — alternância de visibilidade de camadas com suporte a múltiplos grupos independentes.

Comportamento central (herdado do Layer Cycler original):
  - Cicla a VISIBILIDADE das camadas: somente uma fica visível por vez.
  - Reset restaura todas as camadas do ciclo para visível.

Modos:
  simple — selecione 2+ camadas no painel e use o atalho; o ciclo trava nessa seleção.
  multi  — cada grupo tem sua própria lista de camadas (via Configurar Grupos).
            Use "Próximo Grupo / Next Group" para trocar o grupo ativo.
            Atribua atalhos de teclado pelo gerenciador do QGIS (Settings → Keyboard Shortcuts).

Persistência: QSettings (rth_project/layer_switcher/*)
"""
import json

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTimer
from qgis.core import Qgis, QgsProject


MODE_SIMPLE = 'simple'
MODE_MULTI  = 'multi'

SETTINGS_MODE         = 'rth_project/layer_switcher/mode'
SETTINGS_GROUPS       = 'rth_project/layer_switcher/groups'
SETTINGS_AUTO_ENABLED = 'rth_project/layer_switcher/auto_enabled'
SETTINGS_AUTO_SECS    = 'rth_project/layer_switcher/auto_secs'


# ---------------------------------------------------------------------------
# Modelo de grupo / Group model
# ---------------------------------------------------------------------------

class LayerGroup:
    def __init__(self, name='Grupo 1 / Group 1', layer_ids=None):
        self.name      = name
        self.layer_ids = list(layer_ids or [])
        self._index    = None   # posição atual no ciclo

    def to_dict(self):
        return {'name': self.name, 'layer_ids': self.layer_ids}

    @classmethod
    def from_dict(cls, d):
        return cls(
            name      = d.get('name', 'Grupo 1 / Group 1'),
            layer_ids = d.get('layer_ids', []),
        )

    def resolved_layers(self):
        """Retorna as camadas presentes no projeto (ignora IDs inválidos)."""
        out = []
        for lid in self.layer_ids:
            lyr = QgsProject.instance().mapLayer(lid)
            if lyr:
                out.append(lyr)
        return out


# ---------------------------------------------------------------------------
# Ferramenta principal / Main tool
# ---------------------------------------------------------------------------

class LayerSwitcherTool:
    """Controla N grupos de alternância independentes por visibilidade / Controls N independent visibility-cycling groups."""

    def __init__(self, iface):
        self.iface             = iface
        self._mode             = MODE_SIMPLE
        self._groups           = [LayerGroup()]
        self._active_group_idx = 0   # grupo ativo no modo multi

        # Modo simples: camadas travadas na seleção atual do painel
        self._simple_locked_ids = []
        self._simple_index      = None

        self._dlg = None

        # Auto-switch timer: avança automaticamente a cada N segundos /
        # Auto-switch timer: automatically advances every N seconds
        self._auto_enabled = False
        self._auto_secs    = 5
        self._auto_action  = None   # QAction do menu para sincronizar checkmark
        self._auto_timer   = QTimer()
        self._auto_timer.timeout.connect(self._auto_tick)

        self._load_config()

        # Per-project persistence: save/load groups when a QGIS project is saved/opened
        QgsProject.instance().writeProject.connect(self._save_project_config)
        QgsProject.instance().readProject.connect(self._load_project_config)

    def tr(self, msg):
        return QCoreApplication.translate('LayerSwitcherTool', msg)

    # ------------------------------------------------------------------
    # API pública / Public API
    # ------------------------------------------------------------------

    def cycle_next(self, *_):
        """Próxima camada no grupo ativo / Next layer in the active group."""
        if self._mode == MODE_SIMPLE:
            self._step_simple(+1)
        else:
            g = self._active_group()
            if g:
                self._step_group(g, +1)

    def cycle_prev(self, *_):
        """Camada anterior no grupo ativo / Previous layer in the active group."""
        if self._mode == MODE_SIMPLE:
            self._step_simple(-1)
        else:
            g = self._active_group()
            if g:
                self._step_group(g, -1)

    def next_group(self, *_):
        """Avança para o próximo grupo (modo multi) / Advance to next group (multi mode)."""
        if self._mode != MODE_MULTI:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Troca de grupo disponível apenas no modo Múltiplos Grupos / Group switch only available in Multi-Group mode'),
                level=Qgis.MessageLevel.Warning, duration=3)
            return
        n = len(self._groups)
        if n <= 1:
            return
        self._active_group_idx = (self._active_group_idx + 1) % n
        self._announce_active_group()

    def prev_group(self, *_):
        """Retrocede para o grupo anterior (modo multi) / Go back to previous group (multi mode)."""
        if self._mode != MODE_MULTI:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Troca de grupo disponível apenas no modo Múltiplos Grupos / Group switch only available in Multi-Group mode'),
                level=Qgis.MessageLevel.Warning, duration=3)
            return
        n = len(self._groups)
        if n <= 1:
            return
        self._active_group_idx = (self._active_group_idx - 1) % n
        self._announce_active_group()

    def reset(self, *_):
        """Reseta o ciclo e restaura a visibilidade de todas as camadas / Reset cycle and restore all layer visibility."""
        root = QgsProject.instance().layerTreeRoot()

        if self._mode == MODE_SIMPLE:
            for lid in self._simple_locked_ids:
                node = root.findLayer(lid)
                if node is not None:
                    node.setItemVisibilityChecked(True)
            self._simple_locked_ids = []
            self._simple_index = None

        else:
            for g in self._groups:
                for lid in g.layer_ids:
                    node = root.findLayer(lid)
                    if node is not None:
                        node.setItemVisibilityChecked(True)
                g._index = None

        self.iface.mapCanvas().refresh()
        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'Ciclo reiniciado — visibilidade restaurada / Cycle reset — visibility restored'),
            level=Qgis.MessageLevel.Info, duration=3
        )

    def configure(self, *_):
        from .tool_layer_switcher_dialog import LayerSwitcherConfigDialog
        if self._dlg is None:
            self._dlg = LayerSwitcherConfigDialog(self.iface, self, self.iface.mainWindow())
        self._dlg.reload()
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    def set_auto_action(self, action):
        """Registra a QAction do menu para manter o checkmark sincronizado.
        Register the menu QAction to keep checkmark in sync.
        """
        self._auto_action = action
        action.setChecked(self._auto_enabled)

    def set_auto(self, enabled, *_):
        """Habilita ou desabilita a alternância automática / Enable or disable auto-switching."""
        self._auto_enabled = bool(enabled)
        self._save_config()
        if self._auto_enabled:
            self._start_auto_timer()
        else:
            self._stop_auto_timer()
        if self._auto_action is not None:
            self._auto_action.setChecked(self._auto_enabled)

    def configure_auto(self, *_):
        """Abre diálogo para configurar o intervalo da alternância automática / Open dialog to configure auto-switch interval."""
        from qgis.PyQt.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QSpinBox, QDialogButtonBox,
        )

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle(self.tr(u'Alternância Automática — Intervalo / Auto Switch — Interval'))

        layout = QVBoxLayout(dlg)

        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr(u'Intervalo (segundos) / Interval (seconds):')))
        spin = QSpinBox()
        spin.setRange(1, 3600)
        spin.setValue(self._auto_secs)
        row.addWidget(spin)
        layout.addLayout(row)

        try:
            std = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        except AttributeError:
            std = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        btns = QDialogButtonBox(std)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_():
            self._auto_secs = spin.value()
            self._save_config()
            if self._auto_enabled:
                self._start_auto_timer()   # reinicia com novo intervalo / restart with new interval

    def _start_auto_timer(self):
        """Inicia o timer de alternância automática / Start the auto-switch timer."""
        self._auto_timer.stop()
        self._auto_timer.setInterval(self._auto_secs * 1000)
        self._auto_timer.start()
        if self._auto_action is not None:
            self._auto_action.setChecked(True)

    def _stop_auto_timer(self):
        """Para o timer de alternância automática / Stop the auto-switch timer."""
        self._auto_timer.stop()
        if self._auto_action is not None:
            self._auto_action.setChecked(False)

    def _auto_tick(self):
        """Chamado pelo timer a cada N segundos — avança uma camada / Called by timer every N seconds — advance one layer."""
        self.cycle_next()

    def apply_config(self, mode, groups):
        """Chamado pelo diálogo ao aplicar as configurações / Called by dialog on Apply."""
        root = QgsProject.instance().layerTreeRoot()

        if mode == MODE_SIMPLE:
            # Voltando ao modo simples: restaura visibilidade de todos os grupos,
            # pois o modo simples não os gerencia / Returning to simple mode: restore
            # all group layers' visibility since simple mode doesn't manage them
            for g in self._groups:
                for lid in g.layer_ids:
                    node = root.findLayer(lid)
                    if node is not None:
                        node.setItemVisibilityChecked(True)
        else:
            # Modo multi: restaura apenas camadas que saíram da configuração /
            # Multi mode: only restore layers removed from config
            new_ids = {lid for g in groups for lid in g.layer_ids}
            old_ids = {lid for g in self._groups for lid in g.layer_ids}
            for lid in (old_ids - new_ids):
                node = root.findLayer(lid)
                if node is not None:
                    node.setItemVisibilityChecked(True)

        self._mode   = mode
        self._groups = groups if groups else [LayerGroup()]

        # Garante que o índice ativo ainda é válido / Ensure active index is still valid
        self._active_group_idx = max(0, min(self._active_group_idx, len(self._groups) - 1))

        self._simple_locked_ids = []
        self._simple_index = None
        for g in self._groups:
            g._index = None

        self._save_config()
        self._save_project_config()

    def get_mode(self):
        return self._mode

    def get_groups(self):
        return self._groups

    def get_active_group_idx(self):
        return self._active_group_idx

    def stop(self):
        """Chamado no unload do plugin / Called on plugin unload."""
        self._stop_auto_timer()
        try:
            QgsProject.instance().writeProject.disconnect(self._save_project_config)
            QgsProject.instance().readProject.disconnect(self._load_project_config)
        except Exception:  # nosec B110
            pass

    # ------------------------------------------------------------------
    # Grupo ativo / Active group helpers
    # ------------------------------------------------------------------

    def _active_group(self):
        if not self._groups:
            return None
        idx = max(0, min(self._active_group_idx, len(self._groups) - 1))
        return self._groups[idx]

    def _announce_active_group(self):
        g = self._active_group()
        if g:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Grupo ativo / Active group: {0}  ({1}/{2})').format(
                    g.name, self._active_group_idx + 1, len(self._groups)),
                level=Qgis.MessageLevel.Info, duration=3
            )

    # ------------------------------------------------------------------
    # Ciclo de visibilidade / Visibility cycling
    # ------------------------------------------------------------------

    def _step_simple(self, direction):
        """Cicla pela visibilidade das camadas selecionadas no painel (comportamento original do Layer Cycler)."""
        selected     = self.iface.layerTreeView().selectedLayers()
        selected_ids = {lyr.id() for lyr in selected}

        # Se a seleção mudou (2+ camadas diferentes), trava a nova seleção
        if len(selected) >= 2 and selected_ids != set(self._simple_locked_ids):
            self._simple_locked_ids = self._order_bottom_to_top(selected)
            self._simple_index = None

        if not self._simple_locked_ids:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Selecione 2 ou mais camadas no painel e tente novamente / Select 2 or more layers in the panel and try again'),
                level=Qgis.MessageLevel.Warning, duration=4
            )
            return

        n = len(self._simple_locked_ids)

        if self._simple_index is None:
            self._simple_index = 0 if direction > 0 else n - 1
        else:
            self._simple_index = (self._simple_index + direction) % n

        root = QgsProject.instance().layerTreeRoot()
        for i, lid in enumerate(self._simple_locked_ids):
            node = root.findLayer(lid)
            if node is not None:
                node.setItemVisibilityChecked(i == self._simple_index)
        self.iface.mapCanvas().refresh()

        current = QgsProject.instance().mapLayer(self._simple_locked_ids[self._simple_index])
        if current:
            arrow = u'▶' if direction > 0 else u'◀'
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'{0} {1}  ({2}/{3})').format(
                    arrow, current.name(), self._simple_index + 1, n),
                level=Qgis.MessageLevel.Info, duration=2
            )

    def _step_group(self, group, direction):
        """Cicla pela visibilidade das camadas configuradas em um grupo / Cycle visibility of layers in a configured group."""
        layers = group.resolved_layers()
        if not layers:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Grupo "{0}": sem camadas configuradas. Abra Configurar Grupos. / Group "{0}": no layers configured. Open Configure Groups.').format(group.name),
                level=Qgis.MessageLevel.Warning, duration=4
            )
            return

        n = len(layers)

        if group._index is None:
            group._index = 0 if direction > 0 else n - 1
        else:
            group._index = (group._index + direction) % n

        root = QgsProject.instance().layerTreeRoot()
        for i, lyr in enumerate(layers):
            node = root.findLayer(lyr.id())
            if node is not None:
                node.setItemVisibilityChecked(i == group._index)
        self.iface.mapCanvas().refresh()

        current_lyr = layers[group._index]
        arrow = u'▶' if direction > 0 else u'◀'
        self.iface.messageBar().pushMessage(
            'RTH',
            self.tr(u'[{0}] {1} {2}  ({3}/{4})').format(
                group.name, arrow, current_lyr.name(), group._index + 1, n),
            level=Qgis.MessageLevel.Info, duration=2
        )

    # ------------------------------------------------------------------
    # Utilitários / Utilities
    # ------------------------------------------------------------------

    def _order_bottom_to_top(self, layers):
        """Ordena camadas de baixo para cima conforme o painel / Order layers bottom-to-top as in the panel."""
        root           = QgsProject.instance().layerTreeRoot()
        top_to_bot_ids = [lyr.id() for lyr in root.layerOrder()]
        layer_id_set   = {lyr.id() for lyr in layers}
        ordered        = [lid for lid in top_to_bot_ids if lid in layer_id_set]
        ordered.reverse()
        return ordered

    # ------------------------------------------------------------------
    # Persistência / Persistence
    # ------------------------------------------------------------------

    def _save_project_config(self, *_):
        """Salva configuração no projeto QGIS aberto (por projeto) / Save config in the open QGIS project (per-project)."""
        try:
            proj = QgsProject.instance()
            proj.writeEntry('rth_layer_switcher', 'mode', self._mode)
            proj.writeEntry('rth_layer_switcher', 'groups',
                            json.dumps([g.to_dict() for g in self._groups]))
        except Exception:  # nosec B110
            pass

    def _load_project_config(self, *_):
        """Carrega configuração do projeto QGIS aberto; ignora se não houver dados salvos / Load config from open QGIS project; ignore if no saved data."""
        try:
            proj = QgsProject.instance()
            mode, ok_mode = proj.readEntry('rth_layer_switcher', 'mode', '')
            raw,  ok_raw  = proj.readEntry('rth_layer_switcher', 'groups', '')

            if ok_mode and mode in (MODE_SIMPLE, MODE_MULTI):
                self._mode = mode

            if ok_raw and raw:
                data = json.loads(raw)
                groups = [LayerGroup.from_dict(d) for d in data]
                if groups:
                    self._groups = groups
                    self._active_group_idx = max(
                        0, min(self._active_group_idx, len(self._groups) - 1))
                    for g in self._groups:
                        g._index = None
        except Exception:  # nosec B110
            pass

    def _load_config(self):
        s = QSettings()
        self._mode = s.value(SETTINGS_MODE, MODE_SIMPLE)
        raw = s.value(SETTINGS_GROUPS, None)
        if raw:
            try:
                data         = json.loads(raw)
                self._groups = [LayerGroup.from_dict(d) for d in data]
                if not self._groups:
                    self._groups = [LayerGroup()]
            except Exception:
                self._groups = [LayerGroup()]
        # Auto-switch: carrega habilitado/intervalo; retoma timer se estava ativo /
        # Auto-switch: load enabled/interval; resume timer if it was active
        self._auto_enabled = s.value(SETTINGS_AUTO_ENABLED, False, type=bool)
        self._auto_secs    = s.value(SETTINGS_AUTO_SECS,    5,     type=int)
        if self._auto_enabled:
            self._start_auto_timer()

    def _save_config(self):
        s = QSettings()
        s.setValue(SETTINGS_MODE,         self._mode)
        s.setValue(SETTINGS_GROUPS,       json.dumps([g.to_dict() for g in self._groups]))
        s.setValue(SETTINGS_AUTO_ENABLED, self._auto_enabled)
        s.setValue(SETTINGS_AUTO_SECS,    self._auto_secs)
