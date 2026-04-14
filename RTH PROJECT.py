# -*- coding: utf-8 -*-
"""
RTH PROJECT — Plugin QGIS para Mapeamento Agrícola
RTH PROJECT — QGIS Plugin for Agricultural Mapping

Plugin criado para a comunidade open-source para auxiliar no mapeamento agrícola
de diferentes áreas do mundo. Desenvolvido com Plugin Builder 3 e Claude Agent
como assistente, reunindo ferramentas utilizadas ao longo da vida profissional do autor.

Plugin created for the open-source community to assist in agricultural mapping
of different areas of the world. Developed with Plugin Builder 3 and Claude Agent
as assistant, gathering tools used throughout the author's professional life.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos de arquivo / Standard library for file paths
import os
# Biblioteca padrão para manipulação do caminho de módulos Python / Standard library for Python module path manipulation
import sys
# Importação dinâmica de módulos com nomes contendo espaços / Dynamic module import for filenames with spaces
import importlib.util

# Importações do Qt para configurações, tradução e aplicação / Qt imports for settings, translation and application
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QUrl
# Importações do Qt para ícones / Qt imports for icons
from qgis.PyQt.QtGui import QIcon
# Importação do Qt para ações da barra de ferramentas e abertura de URLs / Qt import for toolbar actions and URL opening
from qgis.PyQt.QtWidgets import QAction, QToolButton, QMenu
# Abre URLs no navegador padrão do sistema / Opens URLs in the system default browser
from qgis.PyQt.QtGui import QDesktopServices

# Adiciona o diretório do plugin ao sys.path para permitir importar os módulos de ferramentas
# Add plugin directory to sys.path to allow importing tool modules
_plugin_dir = os.path.dirname(__file__)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

# Importa as classes de cada ferramenta a partir de seus módulos dedicados
# Import each tool class from its dedicated module
from tool_lat_long_picker import LatLongPickerTool       # ferramenta Lat/Long / LatLong tool  # noqa: E402
from tool_catch_json import CatchJsonTool               # ferramenta Catch JSON / Catch JSON tool  # noqa: E402
from tool_send_to_google import SendToGoogleTool        # ferramenta Google Earth / Google Earth tool  # noqa: E402
from tool_calc_area import CalcAreaTool                 # ferramenta Cálculo de Área / Area Calc tool  # noqa: E402
from tool_dem_downloader import DEMDownloaderTool       # ferramenta DEM Downloader / DEM Downloader tool  # noqa: E402
from tool_point_grid import PointGridTool               # ferramenta Grid de Pontos / Point Grid tool  # noqa: E402
from tool_export_csv import ExportGridCSVTool           # ferramenta Export CSV / Export CSV tool  # noqa: E402
from tool_import_csv import ImportCSVTool               # ferramenta Import CSV / Import CSV tool  # noqa: E402
from tool_planting_lines import PlantingLinesTool       # ferramenta Linhas de Plantio/Colheita / Planting/Harvest Lines tool  # noqa: E402
from tool_points_to_polygon import PointsToPolygonTool  # ferramenta Pontos de GPS para Polígono / GPS Points to Polygon tool  # noqa: E402
from tool_layer_cycler import LayerCyclerTool           # ferramenta Alternar Camadas / Layer Cycler tool  # noqa: E402

# Carrega dinamicamente o resources.py (nome de arquivo com espaço no diretório pai)
# Dynamically load resources.py (filename with space in parent directory)
try:
    # Monta o caminho absoluto para resources.py / Build absolute path to resources.py
    _res_path = os.path.join(_plugin_dir, 'resources.py')
    # Cria a spec do módulo a partir do arquivo / Create module spec from file
    _spec_res = importlib.util.spec_from_file_location('rthproject_resources', _res_path)
    # Instancia o módulo / Instantiate module
    _res_mod = importlib.util.module_from_spec(_spec_res)
    # Executa o módulo para registrar os recursos Qt / Execute module to register Qt resources
    _spec_res.loader.exec_module(_res_mod)
    # Exporta todos os símbolos públicos para o escopo global / Export all public symbols to global scope
    for _k, _v in vars(_res_mod).items():
        if not _k.startswith('__'):
            globals()[_k] = _v
except Exception:
    # Fallback para importação direta / Fallback to direct import
    try:
        from resources import *  # type: ignore  # noqa: F401, F403
    except Exception:
        pass  # Ignora se resources não estiver disponível / Ignore if resources not available


class rthproject:
    """Plugin principal RTH PROJECT para mapeamento agrícola / Main RTH PROJECT plugin for agricultural mapping."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # Diretório raiz do plugin / Plugin root directory
        self.plugin_dir = _plugin_dir

        # Instancia cada ferramenta passando a interface QGIS / Instantiate each tool passing QGIS interface
        self.tool_latlong = LatLongPickerTool(iface)        # Lat/Long Picker
        self.tool_catch_json = CatchJsonTool(iface)         # Catch JSON
        self.tool_send_google = SendToGoogleTool(iface)     # Send to Google Earth Pro
        self.tool_calc_area = CalcAreaTool(iface)           # Calc Area (ha)
        self.tool_dem = DEMDownloaderTool(iface)            # RTH DEM Downloader
        self.tool_point_grid = PointGridTool(iface)         # Grid de Pontos / Point Grid
        self.tool_export_csv = ExportGridCSVTool(iface)     # Export CSV
        self.tool_import_csv = ImportCSVTool(iface)         # Import CSV
        self.tool_planting_lines = PlantingLinesTool(iface)    # Linhas de Plantio/Colheita / Planting/Harvest Lines
        self.tool_pts_to_poly = PointsToPolygonTool(iface)     # Pontos de GPS para Polígono / GPS Points to Polygon
        self.tool_layer_cycler = LayerCyclerTool(iface)        # Alternar Camadas / Layer Cycler

        # Carrega dinamicamente o módulo de diálogo (nome com espaço) / Dynamically load dialog module (name with space)
        try:
            # Caminho para o arquivo de diálogo / Path to dialog file
            dialog_path = os.path.join(self.plugin_dir, 'RTH PROJECT_dialog.py')
            # Cria spec do módulo de diálogo / Create spec for dialog module
            spec = importlib.util.spec_from_file_location('rthproject_dialog', dialog_path)
            # Instancia o módulo de diálogo / Instantiate dialog module
            dialog_mod = importlib.util.module_from_spec(spec)
            # Executa o módulo de diálogo / Execute dialog module
            spec.loader.exec_module(dialog_mod)
            # Obtém a classe de diálogo do módulo / Get dialog class from module
            self.dialog_class = getattr(dialog_mod, 'rthprojectDialog')
        except Exception:
            # Se falhar, define como None para tratar depois / If fails, set to None to handle later
            self.dialog_class = None

        # Lê o locale do usuário para carregar tradução / Read user locale to load translation
        locale = QSettings().value('locale/userLocale')[0:2]
        # Monta o caminho para o arquivo de tradução / Build path to translation file
        locale_path = os.path.join(self.plugin_dir, 'i18n', 'rthproject_{}.qm'.format(locale))
        # Instala o tradutor se o arquivo existir / Install translator if file exists
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Lista de ações registradas na barra de ferramentas / List of actions registered in toolbar
        self.actions = []
        # Nome do menu do plugin / Plugin menu name
        self.menu = self.tr(u'&RTH Agriculture Mapping Tools')

    def tr(self, message):
        """Traduz uma mensagem usando o contexto do plugin / Translate a message using the plugin context."""
        return QCoreApplication.translate('rthproject', message)

    def add_action(self, icon_path, text, callback, enabled_flag=True,
                   add_to_menu=True, add_to_toolbar=True,
                   status_tip=None, whats_this=None, parent=None):
        """Cria e registra uma ação na barra de ferramentas e no menu / Create and register an action in toolbar and menu."""
        # Cria o ícone a partir do caminho / Create icon from path
        icon = QIcon(icon_path)
        # Cria a ação Qt com o ícone e o texto / Create Qt action with icon and text
        action = QAction(icon, text, parent)
        # Conecta o sinal de ativação ao callback / Connect activation signal to callback
        action.triggered.connect(callback)
        # Habilita ou desabilita a ação / Enable or disable the action
        action.setEnabled(enabled_flag)
        # Define a dica de status se fornecida / Set status tip if provided
        if status_tip is not None:
            action.setStatusTip(status_tip)
        # Define o texto de ajuda contextual se fornecido / Set contextual help text if provided
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        # Adiciona à barra de ferramentas se solicitado / Add to toolbar if requested
        if add_to_toolbar:
            self.iface.addToolBarIcon(action)
        # Adiciona ao menu se solicitado / Add to menu if requested
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)
        # Armazena a ação para remoção posterior / Store action for later removal
        self.actions.append(action)
        return action

    def _icon(self, name):
        """Retorna o caminho absoluto do ícone na pasta do plugin / Return the absolute icon path inside the plugin folder."""
        return os.path.join(self.plugin_dir, name)

    def initGui(self):
        """Inicializa a interface gráfica do plugin / Initialize the plugin graphical interface."""

        # ── RTH Series ────────────────────────────────────────────────────────
        # Botão que abre o app RTH Series no navegador / Button that opens RTH Series app in browser
        self.add_action(
            self._icon('rthseries.png'),
            text=self.tr(u'RTH Análise / Analysis'),
            callback=self.open_rth_series,
            parent=self.iface.mainWindow())

        # ── RTH Series Veg Time ───────────────────────────────────────────────
        # Botão que abre o app RTH Series Veg Time no navegador / Button that opens RTH Series Veg Time app in browser
        self.add_action(
            self._icon('rthvegtime.png'),
            text=self.tr(u'RTH Vegtime'),
            callback=self.open_rth_vegtime,
            parent=self.iface.mainWindow())

        # ── RTH Climate Viewer ────────────────────────────────────────────────
        # Botão que abre o app RTH Climate Viewer no navegador / Button that opens RTH Climate Viewer app in browser
        _climate_icon = self._icon('rthclimate.png') if os.path.exists(self._icon('rthclimate.png')) else self._icon('icon.png')
        self.add_action(
            _climate_icon,
            text=self.tr(u'RTH Climate Viewer'),
            callback=self.open_rth_climate_viewer,
            parent=self.iface.mainWindow())

        # ── RTH API BROWSER ──────────────────────────────────────────────────
        # Ícone principal do plugin / Main plugin icon
        self.add_action(
            self._icon('icon.png'),
            text=self.tr(u'RTH API BROWSER'),
            callback=self.open_rth_ui,
            parent=self.iface.mainWindow())

        # ── Lat/Long Picker ───────────────────────────────────────────────────
        # Botão para capturar coordenadas ao clicar no mapa / Button to capture coordinates by clicking on map
        self.add_action(
            self._icon('latlong.png'),
            text=self.tr(u'Capturar Lat/Long / Lat Long Picker'),
            callback=self.tool_latlong.activate,
            parent=self.iface.mainWindow())

        # ── Catch JSON ────────────────────────────────────────────────────────
        # Botão para exportar a geometria selecionada como GeoJSON / Button to export selected geometry as GeoJSON
        self.add_action(
            self._icon('get.png'),
            text=self.tr(u'Capturar JSON / Catch JSON'),
            callback=self.tool_catch_json.export,
            parent=self.iface.mainWindow())

        # ── Send to Google Earth Pro ──────────────────────────────────────────
        # Botão para enviar ponto ao Google Earth Pro / Button to send point to Google Earth Pro
        self.add_action(
            self._icon('earth.png'),
            text=self.tr(u'Enviar ao Google Pro / Send to Google Pro'),
            callback=self.tool_send_google.activate,
            parent=self.iface.mainWindow())

        # ── RTH DEM Downloader ───────────────────────────────────────────────
        # Botão para baixar modelos de elevação do Topodata INPE / Button to download Topodata INPE elevation models
        # Usa dem.png se existir, senão usa o ícone padrão / Use dem.png if exists, else use default icon
        _dem_icon = self._icon('dem.png') if os.path.exists(self._icon('dem.png')) else self._icon('icon.png')
        self.add_action(
            _dem_icon,
            text=self.tr(u'RTH Baixar DEM / DEM Downloader'),
            callback=self.tool_dem.open,
            parent=self.iface.mainWindow())

        # ── Calc Area (ha) ────────────────────────────────────────────────────
        # Botão para calcular a área da feição selecionada / Button to calculate selected feature area
        self.add_action(
            self._icon('area.png'),
            text=self.tr(u'Calcular Área / Calc Area (ha)'),
            callback=self.tool_calc_area.calculate,
            parent=self.iface.mainWindow())

        # ── Pontos de GPS para Polígono / GPS Points to Polygon ──────────────────────────────────────────
        # Botão para gerar polígono côncavo a partir de pontos ou CSV / Button to generate concave polygon from points or CSV
        _ptp_icon = self._icon('pts2poly.png') if os.path.exists(self._icon('pts2poly.png')) else self._icon('icon.png')
        self.add_action(
            _ptp_icon,
            text=self.tr(u'Pontos de GPS para Polígono / GPS Points to Polygon'),
            callback=self.tool_pts_to_poly.run,
            parent=self.iface.mainWindow())

        # ── Grid de Pontos / Point Grid ───────────────────────────────────────
        # Botão para gerar grade de pontos dentro do polígono selecionado / Button to generate point grid inside selected polygon
        self.add_action(
            self._icon('grid.png'),
            text=self.tr(u'Grid de Pontos / Point Grid'),
            callback=self.tool_point_grid.run,
            parent=self.iface.mainWindow())

        # ── Export CSV ────────────────────────────────────────────────────────
        # Botão para exportar camada de pontos para CSV com geometria AS_YX / Button to export point layer to CSV with AS_YX geometry
        self.add_action(
            self._icon('gridexport.png'),
            text=self.tr(u'Exportar CSV / Export CSV'),
            callback=self.tool_export_csv.run,
            parent=self.iface.mainWindow())

        # ── Import CSV ────────────────────────────────────────────────────────
        # Botão para importar CSV com colunas X e Y como camada de pontos / Button to import CSV with X and Y columns as a point layer
        self.add_action(
            self._icon('gridimport.png'),
            text=self.tr(u'Importar CSV / Import CSV'),
            callback=self.tool_import_csv.run,
            parent=self.iface.mainWindow())

        # ── Linhas de Plantio/Colheita / Planting/Harvest Lines ───────────────────────────────
        # Botão para gerar linhas de plantio paralelas dentro do polígono / Button to generate parallel planting lines inside polygon
        _pl_icon = self._icon('planting.png') if os.path.exists(self._icon('planting.png')) else self._icon('icon.png')
        self.add_action(
            _pl_icon,
            text=self.tr(u'Linhas de Plantio/Colheita / Planting/Harvest Lines'),
            callback=self.tool_planting_lines.run,
            parent=self.iface.mainWindow())

        # Registra todas as actions da toolbar nos atalhos de teclado do QGIS
        # Register all toolbar actions in QGIS keyboard shortcuts
        for action in self.actions:
            self.iface.registerMainWindowAction(action, '')

        # ── Funcionalidades Adicionais / Additional Features ──────────────────
        # Botão com menu dropdown para ferramentas adicionais / Dropdown menu button for additional tools
        self._additional_btn = QToolButton(self.iface.mainWindow())
        _add_icon = self._icon('addfunc.png') if os.path.exists(self._icon('addfunc.png')) else self._icon('icon-geral.png')
        self._additional_btn.setIcon(QIcon(_add_icon))
        self._additional_btn.setToolTip(self.tr(u'Funcionalidades Adicionais / Additional Features'))
        # Abre o menu ao clicar no botão / Opens menu on button click
        self._additional_btn.setPopupMode(QToolButton.InstantPopup)

        # Monta o menu de funcionalidades adicionais / Build additional features menu
        self._additional_menu = QMenu(self._additional_btn)

        # Ação: Alternar Camadas / Layer Cycler
        # Pai é mainWindow para que o QGIS reconheça a action nos atalhos / Parent is mainWindow so QGIS recognizes the action in shortcuts
        _cycle_icon = self._icon('layercycler.png') if os.path.exists(self._icon('layercycler.png')) else self._icon('icon-geral.png')
        self._action_cycle = QAction(
            QIcon(_cycle_icon),
            self.tr(u'Alternar Camadas / Layer Cycler'),
            self.iface.mainWindow())
        self._action_cycle.setToolTip(
            self.tr(u'Alterna a visibilidade das camadas selecionadas, de baixo para cima, a cada clique / '
                    u'Cycles selected layer visibility bottom-to-top on each click'))
        self._action_cycle.triggered.connect(self.tool_layer_cycler.cycle)
        self._additional_menu.addAction(self._action_cycle)
        # Registra a action nos atalhos de teclado do QGIS (sem atalho padrão)
        # Register the action in QGIS keyboard shortcuts (no default shortcut)
        self.iface.registerMainWindowAction(self._action_cycle, '')

        # Ação: Resetar ciclo / Reset cycle
        _reset_icon = self._icon('resetlayercycler.png') if os.path.exists(self._icon('resetlayercycler.png')) else self._icon('icon-geral.png')
        self._action_cycle_reset = QAction(
            QIcon(_reset_icon),
            self.tr(u'Resetar ciclo de camadas / Reset Layer Cycle'),
            self.iface.mainWindow())
        self._action_cycle_reset.triggered.connect(self.tool_layer_cycler.reset)
        self._additional_menu.addAction(self._action_cycle_reset)
        # Registra também o reset nos atalhos de teclado / Register reset in keyboard shortcuts too
        self.iface.registerMainWindowAction(self._action_cycle_reset, '')

        self._additional_btn.setMenu(self._additional_menu)

        # Adiciona o botão à barra de ferramentas do plugin / Add button to plugin toolbar
        self._additional_widget_action = self.iface.addToolBarWidget(self._additional_btn)

    def unload(self):
        """Remove o plugin da interface do QGIS / Remove the plugin from the QGIS interface."""
        # Remove cada ação do menu, toolbar e atalhos de teclado / Remove each action from menu, toolbar and keyboard shortcuts
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
            self.iface.unregisterMainWindowAction(action)
        # Desregistra as actions dos atalhos de teclado do QGIS / Unregister actions from QGIS keyboard shortcuts
        if hasattr(self, '_action_cycle'):
            self.iface.unregisterMainWindowAction(self._action_cycle)
        if hasattr(self, '_action_cycle_reset'):
            self.iface.unregisterMainWindowAction(self._action_cycle_reset)
        # Remove o botão de Funcionalidades Adicionais da toolbar / Remove Additional Features button from toolbar
        if hasattr(self, '_additional_widget_action') and self._additional_widget_action:
            from qgis.PyQt.QtWidgets import QToolBar
            toolbar = self.iface.mainWindow().findChild(QToolBar, 'mPluginToolBar')
            if toolbar:
                toolbar.removeAction(self._additional_widget_action)

    def open_rth_series(self):
        """Abre o aplicativo RTH Series no navegador padrão / Open RTH Series app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseries'))

    def open_rth_vegtime(self):
        """Abre o aplicativo RTH Series Veg Time no navegador padrão / Open RTH Series Veg Time app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseriesvegtime'))

    def open_rth_climate_viewer(self):
        """Abre o aplicativo RTH Climate Viewer no navegador padrão / Open RTH Climate Viewer app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseriesclimateviewer'))

    def open_rth_ui(self):
        """Abre o diálogo principal do RTH API BROWSER / Open the main RTH API BROWSER dialog."""
        # Verifica se o módulo de diálogo foi carregado / Check if dialog module was loaded
        if self.dialog_class is None:
            self.iface.messageBar().pushMessage(
                'RTH', 'Módulo de diálogo não disponível / Dialog module not available', level=1)
            return
        try:
            # Cria o diálogo se ainda não existir, passando a interface QGIS / Create dialog if it does not exist yet, passing QGIS interface
            if not hasattr(self, 'dlg') or self.dlg is None:
                self.dlg = self.dialog_class(self.iface)
            # Exibe o diálogo / Show the dialog
            self.dlg.show()
            # Traz o diálogo para frente / Bring dialog to front
            self.dlg.raise_()
            # Ativa a janela do diálogo / Activate the dialog window
            self.dlg.activateWindow()
        except Exception as e:
            # Exibe o erro na barra de mensagens / Show error in the message bar
            self.iface.messageBar().pushMessage('RTH', str(e), level=1)
