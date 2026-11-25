# -*- coding: utf-8 -*-
"""
RTH Quick Style / Quick Layout — aplica estilos .qml e abre templates .qpt dinamicamente.

Fluxo de trabalho / Workflow:
  Estilos: salve um .qml em  symbology/raster/  ou  symbology/vector/  e ele
           aparece automaticamente no menu na próxima vez que abrir.
  Layouts: salve um .qpt em  layouts/  e ele aparece no menu.
"""
import os

from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    Qgis, QgsVectorLayer, QgsRasterLayer,
    QgsProject, QgsPrintLayout, QgsReadWriteContext, QgsLayoutItemMap,
)



class QuickStyleTool:
    """Gerencia estilos rápidos e layouts rápidos / Manages quick styles and quick layouts."""

    def __init__(self, iface, plugin_dir):
        self.iface           = iface
        self.plugin_dir      = plugin_dir
        self._sym_dir        = os.path.join(plugin_dir, 'symbology')
        self._lay_dir        = os.path.join(plugin_dir, 'layouts')
        self._loaded_layouts = []   # prevents GC of QgsPrintLayout objects

        # Cria as pastas na primeira execução / Create folders on first run
        for d in [
            os.path.join(self._sym_dir, 'raster'),
            os.path.join(self._sym_dir, 'vector'),
            self._lay_dir,
        ]:
            os.makedirs(d, exist_ok=True)

        # Remove our reference when QGIS removes a layout from the manager
        QgsProject.instance().layoutManager().layoutRemoved.connect(
            self._on_layout_removed)

    def _on_layout_removed(self, layout):
        self._loaded_layouts = [l for l in self._loaded_layouts if l is not layout]

    def tr(self, msg):
        return QCoreApplication.translate('QuickStyleTool', msg)

    # ------------------------------------------------------------------
    # Estilos / Styles
    # ------------------------------------------------------------------

    def rebuild_style_menu(self, menu):
        """Chamado em aboutToShow — varre as pastas e reconstrói os itens."""
        menu.clear()

        raster_dir = os.path.join(self._sym_dir, 'raster')
        vector_dir = os.path.join(self._sym_dir, 'vector')

        raster_qmls = self._list_qml(raster_dir)
        vector_qmls = self._list_qml(vector_dir)

        has_content = False

        if raster_qmls:
            sub = QMenu(self.tr(u'Raster'), menu)
            for fname in raster_qmls:
                path  = os.path.join(raster_dir, fname)
                label = self._label(fname)
                act   = QAction(label, menu)
                act.triggered.connect(lambda checked, p=path: self._apply_style(p, 'raster'))
                sub.addAction(act)
            menu.addMenu(sub)
            has_content = True

        if vector_qmls:
            sub = QMenu(self.tr(u'Vetor / Vector'), menu)
            for fname in vector_qmls:
                path  = os.path.join(vector_dir, fname)
                label = self._label(fname)
                act   = QAction(label, menu)
                act.triggered.connect(lambda checked, p=path: self._apply_style(p, 'vector'))
                sub.addAction(act)
            menu.addMenu(sub)
            has_content = True

        if not has_content:
            empty = QAction(self.tr(u'Nenhum estilo encontrado / No styles found'), menu)
            empty.setEnabled(False)
            menu.addAction(empty)

        menu.addSeparator()
        # Dica fixa — sempre visível acima do botão de pasta / Fixed hint — always visible above folder button
        hint = QAction(
            self.tr(u'↳  Coloque arquivos .qml em symbology/raster ou symbology/vector  /  Place .qml files in symbology/raster or symbology/vector'),
            menu)
        hint.setEnabled(False)
        menu.addAction(hint)
        open_act = QAction(self.tr(u'Abrir pasta de estilos / Open styles folder'), menu)
        open_act.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._sym_dir)))
        menu.addAction(open_act)

    def _apply_style(self, qml_path, expected_type):
        """Aplica o .qml na camada ativa após verificar o tipo / Applies .qml to active layer after type check."""
        layer = self.iface.activeLayer()
        if layer is None:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Nenhuma camada ativa / No active layer'),
                level=Qgis.MessageLevel.Warning, duration=3)
            return

        if expected_type == 'raster' and not isinstance(layer, QgsRasterLayer):
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Este estilo é para Raster — selecione uma camada raster / '
                        u'This style is for Raster — select a raster layer'),
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        if expected_type == 'vector' and not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Este estilo é para Vetor — selecione uma camada vetorial / '
                        u'This style is for Vector — select a vector layer'),
                level=Qgis.MessageLevel.Warning, duration=4)
            return

        msg, ok = layer.loadNamedStyle(qml_path)
        layer.triggerRepaint()
        self.iface.layerTreeView().refreshLayerSymbology(layer.id())

        if ok:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Estilo "{0}" aplicado em "{1}" / Style "{0}" applied to "{1}"').format(
                    self._label(os.path.basename(qml_path)), layer.name()),
                level=Qgis.MessageLevel.Info, duration=3)
        else:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Erro ao aplicar estilo / Error applying style: {0}').format(msg),
                level=Qgis.MessageLevel.Critical, duration=5)

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------

    def rebuild_layout_menu(self, menu):
        """Chamado em aboutToShow — varre a pasta layouts/ e reconstrói os itens."""
        menu.clear()

        qpts = self._list_ext(self._lay_dir, '.qpt')

        if qpts:
            for fname in qpts:
                path  = os.path.join(self._lay_dir, fname)
                label = self._label(fname)
                act   = QAction(label, menu)
                act.triggered.connect(lambda checked, p=path: self._open_layout(p))
                menu.addAction(act)
        else:
            empty = QAction(
                self.tr(u'Nenhum layout encontrado / No layouts found'),
                menu)
            empty.setEnabled(False)
            menu.addAction(empty)

        menu.addSeparator()
        # Dica fixa — sempre visível acima do botão de pasta / Fixed hint — always visible above folder button
        hint = QAction(
            self.tr(u'↳  Coloque arquivos .qpt em layouts/  /  Place .qpt files in layouts/'),
            menu)
        hint.setEnabled(False)
        menu.addAction(hint)
        open_act = QAction(self.tr(u'Abrir pasta de layouts / Open layouts folder'), menu)
        open_act.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._lay_dir)))
        menu.addAction(open_act)

    def _open_layout(self, qpt_path):
        """Carrega o .qpt e abre o Layout Designer / Loads .qpt and opens Layout Designer."""
        try:
            with open(qpt_path, 'r', encoding='utf-8') as f:
                content = f.read()

            doc = QDomDocument()
            doc.setContent(content)

            project     = QgsProject.instance()
            layout_name = self._label(os.path.basename(qpt_path))

            # Closing the designer window does NOT remove the layout from the
            # manager — it stays there. Remove any stale copy first so we always
            # get a fresh load with the current canvas state.
            existing = project.layoutManager().layoutByName(layout_name)
            if existing is not None:
                self._loaded_layouts = [l for l in self._loaded_layouts
                                        if l is not existing]
                project.layoutManager().removeLayout(existing)

            layout = QgsPrintLayout(project)
            # Keep a Python-side reference so the GC doesn't delete the object
            # while QGIS still holds the C++ pointer.
            self._loaded_layouts.append(layout)

            layout.initializeDefaults()

            ctx = QgsReadWriteContext()
            ctx.setPathResolver(project.pathResolver())

            # .qpt root may be <Layouts> (QGIS 3.x) or <Layout> (older exports)
            root = doc.documentElement()
            if root.tagName() in ('Layouts', 'LayoutCollection'):
                elem = root.firstChildElement('Layout')
            else:
                elem = root

            if elem.isNull():
                raise ValueError(
                    'Nenhum elemento <Layout> encontrado no arquivo .qpt.\n'
                    'No <Layout> element found in .qpt file.')

            if hasattr(layout, 'readLayoutFromXml'):
                layout.readLayoutFromXml(elem, doc, ctx)
            else:
                layout.readXml(elem, doc, ctx)

            layout.setName(self._label(os.path.basename(qpt_path)))
            project.layoutManager().addLayout(layout)

            canvas        = self.iface.mapCanvas()
            canvas_extent = canvas.extent()
            canvas_crs    = canvas.mapSettings().destinationCrs()
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    item.setKeepLayerSet(False)
                    item.setCrs(canvas_crs)
                    item.zoomToExtent(canvas_extent)

            self.iface.openLayoutDesigner(layout)

        except Exception as e:
            self.iface.messageBar().pushMessage(
                'RTH',
                self.tr(u'Erro ao abrir layout / Error opening layout: {0}').format(str(e)),
                level=Qgis.MessageLevel.Critical, duration=5)


    # ------------------------------------------------------------------
    # Utilitários / Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _list_qml(directory):
        if not os.path.isdir(directory):
            return []
        return sorted(f for f in os.listdir(directory) if f.lower().endswith('.qml'))

    @staticmethod
    def _list_ext(directory, ext):
        if not os.path.isdir(directory):
            return []
        return sorted(f for f in os.listdir(directory) if f.lower().endswith(ext))

    @staticmethod
    def _label(filename):
        """'declividade_30m.qml' → 'declividade 30m'"""
        name = filename
        for ext in ('.qml', '.qpt'):
            if name.lower().endswith(ext):
                name = name[:-len(ext)]
                break
        return name.replace('_', ' ')
