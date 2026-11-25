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

import os
import sys
import importlib.util

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, QUrl, Qt
from qgis.core import Qgis
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
from tools.lat_long_picker.tool_lat_long_picker import LatLongPickerTool       # ferramenta Lat/Long / LatLong tool  # noqa: E402
from tools.reverse_geocode.tool_reverse_geocode import ReverseGeocodeTool      # ferramenta geocodificação reversa / reverse geocode tool  # noqa: E402
from tools.calc_perimeter.tool_calc_perimeter import CalcPerimeterTool         # ferramenta perímetro / perimeter tool  # noqa: E402
from tools.catch_json.tool_catch_json import CatchJsonTool                     # ferramenta Catch JSON / Catch JSON tool  # noqa: E402
from tools.send_to_google.tool_send_to_google import SendToGoogleTool          # ferramenta Google Earth / Google Earth tool  # noqa: E402
from tools.calc_area.tool_calc_area import CalcAreaTool                        # ferramenta Cálculo de Área / Area Calc tool  # noqa: E402
from tools.dem.tool_dem_downloader import DEMDownloaderTool                    # ferramenta DEM Downloader / DEM Downloader tool  # noqa: E402
from tools.point_grid.tool_point_grid import PointGridTool                     # ferramenta Grid de Pontos / Point Grid tool  # noqa: E402
from tools.export_csv.tool_export_csv import ExportGridCSVTool                 # ferramenta Export CSV / Export CSV tool  # noqa: E402
from tools.import_csv.tool_import_csv import ImportCSVTool                     # ferramenta Import CSV / Import CSV tool  # noqa: E402
from tools.planting_lines.tool_planting_lines import PlantingLinesTool         # ferramenta Linhas de Plantio/Colheita / Planting/Harvest Lines tool  # noqa: E402
from tools.points_to_polygon.tool_points_to_polygon import PointsToPolygonTool # ferramenta Pontos de GPS para Polígono / GPS Points to Polygon tool  # noqa: E402
from tools.layer_switcher.tool_layer_switcher import LayerSwitcherTool         # ferramenta Alternar Camadas / Layer Switcher tool  # noqa: E402
from tools.rename_layer.tool_rename_layer import RenameLayerTool               # ferramenta Renomear Layer Rápido / Quick Layer Rename tool  # noqa: E402
from tools.prodes.tool_prodes import ProdesDownloadTool                        # ferramenta PRODES Download / PRODES Download tool  # noqa: E402
from tools.auto_save.tool_auto_save import AutoSaveTool                        # ferramenta Auto-Save / Auto-Save tool  # noqa: E402
from tools.info.tool_info import InfoTool                                      # ferramenta Informações / Info tool  # noqa: E402
from tools.measure_distance.tool_measure_distance import MeasureDistanceTool  # ferramenta Medir Distância / Measure Distance tool  # noqa: E402
from tools.arcgis_export.tool_arcgis_export import ArcGISExportTool           # ferramenta Exportar para ArcGIS / Export to ArcGIS tool  # noqa: E402
from tools.quick_style.tool_quick_style import QuickStyleTool                  # ferramenta Estilos/Layouts Rápidos / Quick Styles & Layouts tool  # noqa: E402
from tools.rth_ml.tool_rth_ml import RthMLTool                                # ferramenta RTH Machine Learning  # noqa: E402
from tools.monitor_export.tool_monitor_export import MonitorExportTool, MONITORS, make_brand_icon, make_tool_icon  # ferramenta Exportar Monitor Agrícola / Agricultural Monitor Export tool  # noqa: E402
from tools.line_analysis.tool_line_analysis import LineAnalysisTool              # ferramenta Análise de Linhas / Line Analysis tool  # noqa: E402
from tools.carreador.tool_carreador import CarreadorTool                         # ferramenta Criação de Carreadores / Headland Creation tool  # noqa: E402
from tools.send_polygon_google.tool_send_polygon_google import SendPolygonToGoogleTool  # ferramenta Enviar Polígono Google Earth Pro / Send Polygon to Google Earth Pro  # noqa: E402
from tools.polygon_reviewer.tool_polygon_reviewer import PolygonReviewerTool            # ferramenta Revisor de Polígonos / Polygon Reviewer tool  # noqa: E402
from tools.drone_planner.tool_drone_planner import DronePlannerTool                     # ferramenta Planejador de Voo para Drones / Drone Flight Planner tool  # noqa: E402
from tools.flight_export.tool_flight_export import FlightExportTool                     # ferramenta Exportar Plano de Voo / Flight Plan Export tool  # noqa: E402
from tools.drone_analysis.tool_drone_analysis import DroneAnalysisTool                   # ferramenta Análise de Voo para Drones / Drone Flight Analysis tool  # noqa: E402
from tools.drone_mosaic.tool_drone_mosaic import DroneAutoMosaicTool                     # ferramenta Mosaico Automático de Drone / Drone Auto Mosaic tool  # noqa: E402
from tools.drone_dem.tool_drone_dem import DroneDEMTool                                  # ferramenta Geração de MDE/MDT de Drone / Drone DEM/DTM Generation tool  # noqa: E402
from tools.drone_analytics.tool_drone_analytics import (                                  # ferramentas Análises para Drone / Drone Analytics tools  # noqa: E402
    PlantCountTool, PlantingGapsTool, WeedDetectionTool, PlantHeightTool)                 # noqa: E402
from tools.field_analysis.tool_field_analysis import FieldAnalysisTool                    # ferramenta Análise Rápida do Talhão / Quick Field Analysis tool  # noqa: E402
from tools.vectorize_circle.tool_vectorize_circle import VectorizeCircleTool              # ferramenta Vetorizar Círculo / Vectorize Circle tool  # noqa: E402
from tools.field_drawer.tool_field_drawer import FieldDrawerTool                          # ferramenta Desenhar Talhão automaticamente / Draw Field Automatically tool  # noqa: E402
from tools.camera_displacement.tool_camera_displacement import CameraDisplacementTool     # ferramenta Deslocamento de Camera / Camera Displacement tool  # noqa: E402
from tools.measure_canopy.tool_measure_canopy import MeasureCanopyTool                    # ferramenta Medir Copa das Árvores / Measure Tree Canopy tool  # noqa: E402
from tools.brazil_geobase.tool_brazil_geobase import BrazilGeoBaseTool                    # ferramenta Brazil Public GeoBase / Base de Dados Pública do Brasil  # noqa: E402
from tools.quick_indices.tool_quick_indices import QuickIndicesTool                         # ferramenta Índices de Vegetação em Imagem / Vegetation Indices in Image tool  # noqa: E402
from tools.basemaps_mapeamento.tool_basemaps_mapeamento import BasemapsMapeamento           # ferramenta Basemaps de Satélite / Satellite Basemaps tool  # noqa: E402
from tools.random_points.tool_random_points import RandomPointsTool                        # ferramenta Pontos Aleatórios em Camada / Random Points in Layer tool  # noqa: E402
from tools.point_reviewer.tool_point_reviewer import PointReviewerTool                     # ferramenta Revisor de Pontos / Point Reviewer tool  # noqa: E402
from tools.stack_ml.tool_stack_ml import StackMLTool                                       # ferramenta Stack de Imagem ML / Stack Image ML tool  # noqa: E402
from tools.meteo_data.tool_meteo_data import MeteoDataTool                                 # ferramenta Base de Dados Meteorológicos / Meteorological Data Base  # noqa: E402
from tools.coverage_percentage.tool_coverage_percentage import CoveragePercentageTool      # ferramenta Porcentagem de Cobertura / Coverage Percentage tool  # noqa: E402
from tools.deforestation_monitor.tool_deforestation_monitor import DeforestationMonitorTool  # ferramenta Monitor de Desmatamento / Deforestation Monitor tool  # noqa: E402
from tools.point_review_report.tool_point_review_report import PointReviewReportTool        # ferramenta Relatório de Revisão de Pontos / Point Review Report tool  # noqa: E402
from tools.import_route_gpx.tool_import_route_gpx import ImportRouteGPXTool                # ferramenta Importar Rota GPX / Import GPX Route  # noqa: E402
from tools.import_validation_points.tool_import_validation_points import ImportValidationPointsTool  # ferramenta Importar Pontos de Validação / Import Validation Points  # noqa: E402
from tools.import_benfeitorias.tool_import_benfeitorias import ImportBenfeitoriasTool                # ferramenta Importar Pontos de Benfeitorias / Import Infrastructure Points  # noqa: E402
from tools.import_productive_params.tool_import_productive_params import ImportProductiveParamsTool  # ferramenta Importar Parâmetros Produtivos / Import Productive Parameters  # noqa: E402
from tools.respawn.tool_respawn import RespawnTool                                                   # ferramenta Setar/Teleportar Spawn / Set/Teleport Spawn tool  # noqa: E402
from tools.street_view.tool_street_view import StreetViewTool                                        # ferramenta Buscar no Street View / Street View Navigation tool  # noqa: E402
from tools.bordadura_lines.tool_bordadura_lines import BordaduraLinesTool                             # ferramenta Linhas de Bordadura / Headland Lines tool  # noqa: E402

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
    except Exception:  # nosec B110
        pass  # Ignora se resources não estiver disponível / Ignore if resources not available


class rthproject:
    """Plugin principal RTH PROJECT para mapeamento agrícola / Main RTH PROJECT plugin for agricultural mapping."""

    def __init__(self, iface):
        # Armazena a interface QGIS / Store QGIS interface
        self.iface = iface
        # Diretório raiz do plugin / Plugin root directory
        self.plugin_dir = _plugin_dir

        # Instancia cada ferramenta passando a interface QGIS / Instantiate each tool passing QGIS interface
        self.tool_latlong         = LatLongPickerTool(iface)        # Lat/Long Picker
        self.tool_reverse_geocode = ReverseGeocodeTool(iface)      # Geocodificação Reversa
        self.tool_calc_perimeter  = CalcPerimeterTool(iface)       # Calc Perímetro
        self.tool_catch_json = CatchJsonTool(iface)         # Catch JSON
        self.tool_send_google = SendToGoogleTool(iface)     # Send to Google Earth Pro
        self.tool_calc_area = CalcAreaTool(iface)           # Calc Area (ha)
        self.tool_dem = DEMDownloaderTool(iface)            # RTH DEM Downloader
        self.tool_point_grid = PointGridTool(iface)         # Grid de Pontos / Point Grid
        self.tool_export_csv = ExportGridCSVTool(iface)     # Export CSV
        self.tool_import_csv = ImportCSVTool(iface)         # Import CSV
        self.tool_planting_lines = PlantingLinesTool(iface)    # Linhas de Plantio/Colheita / Planting/Harvest Lines
        self.tool_pts_to_poly = PointsToPolygonTool(iface)     # Pontos de GPS para Polígono / GPS Points to Polygon
        self.tool_layer_switcher = LayerSwitcherTool(iface)    # Alternar Camadas / Layer Switcher
        self.tool_rename_layer = RenameLayerTool(iface)        # Renomear Layer Rápido / Quick Layer Rename
        self.tool_prodes = ProdesDownloadTool(iface)           # PRODES Download
        self.tool_auto_save = AutoSaveTool(iface)              # Auto-Save
        self.tool_info = InfoTool(iface, _plugin_dir)         # Informações / Info
        self.tool_measure = MeasureDistanceTool(iface)        # Medir Distância / Measure Distance
        self.tool_arcgis_export = ArcGISExportTool(iface)    # Exportar para ArcGIS / Export to ArcGIS
        self.tool_quick_style = QuickStyleTool(iface, _plugin_dir)  # Estilos/Layouts Rápidos / Quick Styles & Layouts
        self.tool_rth_ml = RthMLTool(iface)                        # RTH Machine Learning
        self.tool_stack_ml = StackMLTool(iface)                    # Stack de Imagem ML / Stack Image ML
        self.tool_meteo_data = MeteoDataTool(iface)                 # Base de Dados Meteorológicos / Meteorological Data Base
        self.tool_monitor_export = MonitorExportTool(iface)          # Exportar Monitor Agrícola / Agricultural Monitor Export
        self.tool_line_analysis = LineAnalysisTool(iface)            # Análise de Linhas / Line Analysis
        self.tool_carreador = CarreadorTool(iface)                    # Criação de Carreadores / Headland Creation
        self.tool_send_polygon = SendPolygonToGoogleTool(iface)       # Enviar Polígono Google Earth Pro / Send Polygon to Google Earth Pro
        self.tool_polygon_reviewer = PolygonReviewerTool(iface)        # Revisor de Polígonos / Polygon Reviewer
        self.tool_random_points      = RandomPointsTool(iface)            # Pontos Aleatórios em Camada / Random Points in Layer
        self.tool_point_reviewer     = PointReviewerTool(iface)           # Revisor de Pontos / Point Reviewer
        self.tool_coverage_pct         = CoveragePercentageTool(iface)      # Porcentagem de Cobertura / Coverage Percentage
        self.tool_deforest_monitor     = DeforestationMonitorTool(iface)    # Monitor de Desmatamento / Deforestation Monitor
        self.tool_pt_review_report     = PointReviewReportTool(iface)        # Relatório de Revisão de Pontos / Point Review Report
        self.tool_drone_planner = DronePlannerTool(iface)              # Planejador de Voo para Drones / Drone Flight Planner
        self.tool_flight_export = FlightExportTool(iface)              # Exportar Plano de Voo / Flight Plan Export
        self.tool_drone_analysis = DroneAnalysisTool(iface)            # Análise de Voo para Drones / Drone Flight Analysis
        self.tool_drone_mosaic   = DroneAutoMosaicTool(iface)          # Mosaico Automático de Drone / Drone Auto Mosaic
        self.tool_drone_dem      = DroneDEMTool(iface)                  # Geração de MDE/MDT de Drone / Drone DEM/DTM Generation
        self.tool_plant_count    = PlantCountTool(iface)                # Contagem de Plantas / Plant Count
        self.tool_planting_gaps  = PlantingGapsTool(iface)              # Detecção de Falhas de Plantio / Planting Gap Detection
        self.tool_weed_detection = WeedDetectionTool(iface)             # Detecção de Daninhas / Weed Detection
        self.tool_plant_height   = PlantHeightTool(iface)               # Altura de Planta / Plant Height CHM
        self.tool_field_analysis    = FieldAnalysisTool(iface)              # Análise Rápida do Talhão / Quick Field Analysis
        self.tool_field_drawer        = FieldDrawerTool(iface)             # Desenhar Talhão automaticamente / Draw Field Automatically
        self.tool_camera_displacement = CameraDisplacementTool(iface)    # Deslocamento de Camera / Camera Displacement
        self.tool_vectorize_circle  = VectorizeCircleTool(iface)         # Vetorizar Círculo / Vectorize Circle
        self.tool_measure_canopy    = MeasureCanopyTool(iface)            # Medir Copa das Árvores / Measure Tree Canopy
        self.tool_brazil_geobase    = BrazilGeoBaseTool(iface)            # Brazil Public GeoBase / Base de Dados Pública do Brasil
        self.tool_quick_indices     = QuickIndicesTool(iface)              # Índices Rápidos por Imagem / Quick Image Indices
        self.tool_basemaps               = BasemapsMapeamento(iface)                    # Basemaps de Satélite / Satellite Basemaps
        self.tool_import_route_gpx       = ImportRouteGPXTool(iface)                   # Importar Rota GPX / Import GPX Route
        self.tool_import_validation_pts  = ImportValidationPointsTool(iface)           # Importar Pontos de Validação / Import Validation Points
        self.tool_import_benfeitorias    = ImportBenfeitoriasTool(iface)               # Importar Pontos de Benfeitorias / Import Infrastructure Points
        self.tool_import_productive_params = ImportProductiveParamsTool(iface)         # Importar Parâmetros Produtivos / Import Productive Parameters
        self.tool_respawn           = RespawnTool(iface)                              # Setar/Teleportar Spawn / Set/Teleport Spawn
        self.tool_street_view       = StreetViewTool(iface)                           # Buscar no Street View / Street View Navigation
        self.tool_bordadura_lines   = BordaduraLinesTool(iface)                        # Linhas de Bordadura / Headland Lines

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
        """Retorna o caminho absoluto do ícone na pasta icons/ do plugin / Return the absolute icon path inside the plugin icons/ folder."""
        return os.path.join(self.plugin_dir, 'icons', name)

    def _make_dropdown_btn(self, icon_path, label):
        """Cria QToolButton dropdown com ícone e tooltip, sem texto visível / Create dropdown QToolButton with icon and tooltip, no visible text."""
        btn = QToolButton(self.iface.mainWindow())
        btn.setIcon(QIcon(icon_path))
        btn.setToolTip(self.tr(label))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return btn

    def initGui(self):
        """Inicializa a interface gráfica do plugin / Initialize the plugin graphical interface."""

        # ── 1. RTH API BROWSER ───────────────────────────────────────────────
        _browser_action = self.add_action(
            self._icon('icon.png'),
            text=self.tr(u'RTH Catálogo de Cenas / RTH Scene Catalog'),
            callback=self.open_rth_ui,
            parent=self.iface.mainWindow())
        for action in self.actions:
            self.iface.registerMainWindowAction(action, '')

        # Sobrescreve o tooltip no QToolButton real para evitar renderização em negrito
        # do Qt (que ocorre quando o tooltip vem de QAction automaticamente)
        from qgis.PyQt.QtWidgets import QToolBar
        _tb = self.iface.mainWindow().findChild(QToolBar, 'mPluginToolBar')
        if _tb:
            for _w in _tb.findChildren(QToolButton):
                if _w.defaultAction() is _browser_action:
                    _w.setToolTip(self.tr(u'RTH Catálogo de Cenas / RTH Scene Catalog'))
                    break

        # ── 2. GEE Apps (dropdown) ────────────────────────────────────────────
        self._gee_btn = self._make_dropdown_btn(
            self._icon('geeApps.png') if os.path.exists(self._icon('geeApps.png')) else self._icon('icon.png'),
            u'Aplicativos GEE / GEE Apps')
        self._gee_menu = QMenu(self._gee_btn)

        _act = QAction(QIcon(self._icon('rthseries.png')), self.tr(u'RTH Análise de Polígono / RTH Polygon Analysis'), self.iface.mainWindow())
        _act.triggered.connect(self.open_rth_series)
        self._gee_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('rthvegtime.png')), self.tr(u'RTH Gráficos de Vegetação / RTH Vegtime'), self.iface.mainWindow())
        _act.triggered.connect(self.open_rth_vegtime)
        self._gee_menu.addAction(_act)

        _climate_icon = self._icon('rthclimate.png') if os.path.exists(self._icon('rthclimate.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_climate_icon), self.tr(u'RTH Visualizador de Clima / RTH Climate Viewer'), self.iface.mainWindow())
        _act.triggered.connect(self.open_rth_climate_viewer)
        self._gee_menu.addAction(_act)

        _deforest_icon = self._icon('rthDesmatamento.png') if os.path.exists(self._icon('rthDesmatamento.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_deforest_icon), self.tr(u'RTH Verificar Desmatamento / RTH Deforest Check'), self.iface.mainWindow())
        _act.triggered.connect(self.open_rth_deforest_check)
        self._gee_menu.addAction(_act)

        self._gee_btn.setMenu(self._gee_menu)
        self._gee_widget_action = self.iface.addToolBarWidget(self._gee_btn)

        # ── 3. Sensoriamento Remoto (dropdown) ───────────────────────────────
        _sr_icon = self._icon('sensoriamento.png') if os.path.exists(self._icon('sensoriamento.png')) else self._icon('icon-geral.png')
        self._sr_btn = self._make_dropdown_btn(_sr_icon, u'Sensoriamento Remoto / Remote Sensing')
        self._sr_menu = QMenu(self._sr_btn)

        _fd_icon = self._icon('talhaoAuto.png') if os.path.exists(self._icon('talhaoAuto.png')) else self._icon('icon-geral.png')
        _fd_act = QAction(QIcon(_fd_icon), self.tr(u'Desenhar Talhão automaticamente / Draw Field Automatically'), self.iface.mainWindow())
        _fd_act.setToolTip(self.tr(
            u'Clique no mapa para delimitar automaticamente o talhão pela cor do canvas (CIELAB flood fill). '
            u'Clique direito para ajustar a tolerância. / '
            u'Click the map to automatically outline the field by canvas color (CIELAB flood fill). '
            u'Right click to adjust tolerance.'))
        _fd_act.triggered.connect(self.tool_field_drawer.run)
        self._sr_menu.addAction(_fd_act)

        _circ_icon = self._icon('VetCirculo.png') if os.path.exists(self._icon('VetCirculo.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_circ_icon), self.tr(u'Vetorizar Círculo / Vectorize Circle'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Clique no centro, mova para expandir, clique de novo para finalizar. '
            u'Cria círculo suave com 144 vértices. / '
            u'Click centre, move to expand, click again to finish. '
            u'Creates smooth circle with 144 vertices.'))
        _act.triggered.connect(self.tool_vectorize_circle.run)
        self._sr_menu.addAction(_act)

        _reviewer_icon = self._icon('revisorPoligono.png') if os.path.exists(self._icon('revisorPoligono.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_reviewer_icon), self.tr(u'Revisor de Poligonos / Polygon Reviewer'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Navega pelos poligonos selecionados com zoom automatico e rastreamento de revisao / Navigate selected polygons with auto-zoom and revision tracking'))
        _act.triggered.connect(self.tool_polygon_reviewer.run)
        self._sr_menu.addAction(_act)

        self._sr_menu.addSeparator()

        _act = QAction(QIcon(self._icon('PontosAle.png')), self.tr(u'Pontos Aleatórios em Camada / Random Points in Layer'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Gera pontos aleatórios espacialmente espaçados dentro de uma camada polígono / Generates spatially spaced random points inside a polygon layer'))
        _act.triggered.connect(self.tool_random_points.run)
        self._sr_menu.addAction(_act)

        _pt_rev_icon = self._icon('revisorPoligono.png') if os.path.exists(self._icon('revisorPoligono.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_pt_rev_icon), self.tr(u'Revisor de Pontos / Point Reviewer'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Navega pelos pontos da camada ativa com zoom automático e marcação de acerto / Navigate points with auto-zoom and acerto marking'))
        _act.triggered.connect(self.tool_point_reviewer.run)
        self._sr_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('PorcenCob.png')), self.tr(u'Porcentagem de Cobertura / Coverage Percentage'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Calcula que % da área de referência é coberta pelo buffer dos pontos / Calculates what % of the reference area is covered by point buffers'))
        _act.triggered.connect(self.tool_coverage_pct.run)
        self._sr_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('RelatorioPontos.png')), self.tr(u'Relatório de Revisão de Pontos / Point Review Report'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Mostra contagem de Acertou/Errou/Indiferente e calcula o coeficiente Kappa / Shows Acertou/Errou/Indifferent counts and calculates Kappa coefficient'))
        _act.triggered.connect(self.tool_pt_review_report.run)
        self._sr_menu.addAction(_act)

        self._sr_menu.addSeparator()

        _deforest_mon_icon = self._icon('rthDesmatamento.png') if os.path.exists(self._icon('rthDesmatamento.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_deforest_mon_icon), self.tr(u'Monitor de Desmatamento / Deforestation Monitor'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Busca automaticamente 5 imagens de satélite em momentos-chave em torno do desmatamento / Automatically searches 5 satellite images at key moments around deforestation'))
        _act.triggered.connect(self.tool_deforest_monitor.run)
        self._sr_menu.addAction(_act)

        _qi_icon = self._icon('VegImage.png') if os.path.exists(self._icon('VegImage.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_qi_icon), self.tr(u'Índices de Vegetação em Imagem / Vegetation Indices in Image'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Busca cenas Sentinel-2 pela área visível, selecione uma ou mais e calcule índices de vegetação. / '
            u'Search Sentinel-2 scenes by the visible area, select one or more and compute vegetation indices.'))
        _act.triggered.connect(self.tool_quick_indices.run)
        self._sr_menu.addAction(_act)

        self._sr_btn.setMenu(self._sr_menu)
        self._sr_widget_action = self.iface.addToolBarWidget(self._sr_btn)

        # ── 4. RTH Machine Learning (dropdown) ───────────────────────────────
        _ml_icon = self._icon('rthmachine.png')
        self._rth_ml_btn = self._make_dropdown_btn(_ml_icon, u'RTH Machine Learning')
        self._rth_ml_menu = QMenu(self._rth_ml_btn)

        _act = QAction(QIcon(self._icon('stackImage.png')), self.tr(u'Stack de Imagem ML / Stack Image ML'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Empilha bandas Sentinel-2 e índices de vegetação de uma cena STAC em um GeoTIFF multi-banda / '
            u'Stacks Sentinel-2 bands and vegetation indices from a STAC scene into a multi-band GeoTIFF'))
        _act.triggered.connect(self.tool_stack_ml.run)
        self._rth_ml_menu.addAction(_act)

        self._rth_ml_menu.addSeparator()

        _act = QAction(QIcon(self._icon('classImage.png')), self.tr(u'Classificação de Uso do Solo / Land Use Classification'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_rth_ml.run)
        self._rth_ml_menu.addAction(_act)

        self._rth_ml_btn.setMenu(self._rth_ml_menu)
        self._rth_ml_widget_action = self.iface.addToolBarWidget(self._rth_ml_btn)

        # ── 4. Agricultura de Precisão (dropdown) ─────────────────────────────
        self._agro_btn = self._make_dropdown_btn(
            self._icon('agriculturaPresenciao.png') if os.path.exists(self._icon('agriculturaPresenciao.png')) else self._icon('icon.png'),
            u'Agricultura de Precisão / Precision Agriculture')
        self._agro_menu = QMenu(self._agro_btn)

        # ── Ferramentas RTH World Explorer (duplicata) / World Explorer tools (duplicate) ──
        _ptp_icon2 = self._icon('pts2poly.png') if os.path.exists(self._icon('pts2poly.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_ptp_icon2), self.tr(u'Pontos de GPS para Polígono / GPS Points to Polygon'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_pts_to_poly.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('grid.png')), self.tr(u'Grid de Pontos / Point Grid'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_point_grid.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('gridexport.png')), self.tr(u'Exportar Grid CSV / Export Grid CSV'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_export_csv.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('gridimport.png')), self.tr(u'Importar Grid CSV / Import Grid CSV'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_csv.run)
        self._agro_menu.addAction(_act)

        self._agro_menu.addSeparator()

        _act = QAction(QIcon(self._icon('vegtalhao.png')), self.tr(u'Indices de Vegetacao em Talhao / Vegetation Indices in Field'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Selecione o talhao, busque cenas Sentinel-2 e compute NDVI/EVI/SAVI/MSAVI/NDWI diretamente do COG remoto / '
            u'Select field polygon, search Sentinel-2 scenes, and compute NDVI/EVI/SAVI/MSAVI/NDWI directly from remote COG'))
        _act.triggered.connect(self.tool_field_analysis.run)
        self._agro_menu.addAction(_act)


        _pl_icon = self._icon('planting.png') if os.path.exists(self._icon('planting.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_pl_icon), self.tr(u'Linhas de Plantio/Colheita / Planting/Harvest Lines'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_planting_lines.run)
        self._agro_menu.addAction(_act)

        _bord_icon = self._icon('bordadura.png') if os.path.exists(self._icon('bordadura.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_bord_icon), self.tr(u'Linhas de Bordadura / Headland Lines'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Gera passadas perimetrais de bordadura dentro do polígono: '
            u'offset = metade do implemento a partir da borda. / '
            u'Generates headland perimeter passes inside the polygon: '
            u'offset = half implement width from the boundary.'))
        _act.triggered.connect(self.tool_bordadura_lines.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('planting analysis.png')), self.tr(u'Analise de Linhas / Line Analysis'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Analisa qualidade e metricas de linhas de plantio/colheita / Analyse quality and metrics of planting/harvest lines'))
        _act.triggered.connect(self.tool_line_analysis.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('carreadores.png')), self.tr(u'Criacao de Carreadores / Headland Creation'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Desenhe uma linha sobre o poligono para criar a faixa de carreador / Draw a line over the polygon to create the headland strip'))
        _act.triggered.connect(self.tool_carreador.run)
        self._agro_menu.addAction(_act)

        _monitor_submenu = QMenu(self._agro_menu)
        _monitor_submenu.setTitle(self.tr(u'Exportar para Monitor Agrícola / Export to Agricultural Monitor'))
        _monitor_submenu.setIcon(make_tool_icon(22))
        for _monitor_name in MONITORS:
            _act = QAction(make_brand_icon(_monitor_name, 22), self.tr(_monitor_name), self.iface.mainWindow())
            _act.triggered.connect(
                lambda _checked=False, _mn=_monitor_name: self.tool_monitor_export.open(_mn))
            _monitor_submenu.addAction(_act)
        self._agro_menu.addMenu(_monitor_submenu)

        # ── Separador: ferramentas de drone / Drone tools separator ───────────
        self._agro_menu.addSeparator()

        # ── Ferramentas de Drone / Drone tools ────────────────────────────────
        _act = QAction(QIcon(self._icon('planejamentoDrone.png')), self.tr(u'Planejador de Voo para Drones / Drone Flight Planner'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Gera linhas de voo para mapeamento com drones a partir de parametros da camera e sobreposicao / Generate drone mapping flight lines from camera parameters and overlap settings'))
        _act.triggered.connect(self.tool_drone_planner.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('analisedevoodrone.png')), self.tr(u'Analise de Voo para Drones / Drone Flight Analysis'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Estima baterias, metros lineares, tempo de conclusao e outros parametros operacionais do voo / Estimates batteries, linear meters, completion time and other flight operational parameters'))
        _act.triggered.connect(self.tool_drone_analysis.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('exportarplanejamentoDrone.png')), self.tr(u'Exportar Plano de Voo / Export Flight Plan'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Exporta linhas de voo e waypoints para KMZ, KML, Litchi CSV, Mission Planner, Shapefile ou GeoPackage / '
            u'Exports flight lines and waypoints to KMZ, KML, Litchi CSV, Mission Planner, Shapefile or GeoPackage'))
        _act.triggered.connect(self.tool_flight_export.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('mosaicoDrone.png')), self.tr(u'Mosaico Automatico de Drone / Drone Auto Mosaic'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Combina tiles raster georreferenciados em um unico ortomosaico via GDAL Merge / '
            u'Combines georeferenced raster tiles into a single orthomosaic via GDAL Merge'))
        _act.triggered.connect(self.tool_drone_mosaic.run)
        self._agro_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('demDrone.png')), self.tr(u'Geracao de MDE/MDT de Drone / Drone DEM/DTM Generation'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Gera MDE/DSM ou MDT/DTM a partir de tiles raster ou nuvem de pontos LAS/LAZ / '
            u'Generates DEM/DSM or DTM from raster tiles or LAS/LAZ point cloud'))
        _act.triggered.connect(self.tool_drone_dem.run)
        self._agro_menu.addAction(_act)

        _analytics_submenu = QMenu(self._agro_menu)
        _analytics_submenu.setTitle(self.tr(u'Analises para Drone (Em breve) / Drone Analytics (Coming Soon)'))
        _analytics_submenu.setIcon(QIcon(self._icon('emObras.png')))

        _act = QAction(QIcon(self._icon('emObras.png')),
                       self.tr(u'Contagem de Plantas (Em breve) / Plant Count (Coming Soon)'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Em breve / Coming soon'))
        _act.setEnabled(False)
        _analytics_submenu.addAction(_act)

        _act = QAction(QIcon(self._icon('emObras.png')),
                       self.tr(u'Deteccao de Falhas de Plantio (Em breve) / Planting Gap Detection (Coming Soon)'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Em breve / Coming soon'))
        _act.setEnabled(False)
        _analytics_submenu.addAction(_act)

        _act = QAction(QIcon(self._icon('emObras.png')),
                       self.tr(u'Deteccao de Daninhas (Em breve) / Weed Detection (Coming Soon)'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Em breve / Coming soon'))
        _act.setEnabled(False)
        _analytics_submenu.addAction(_act)

        _act = QAction(QIcon(self._icon('emObras.png')),
                       self.tr(u'Altura de Planta via DSM - DTM (Em breve) / Plant Height CHM (Coming Soon)'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Em breve / Coming soon'))
        _act.setEnabled(False)
        _analytics_submenu.addAction(_act)

        self._agro_menu.addMenu(_analytics_submenu)

        self._agro_btn.setMenu(self._agro_menu)
        self._agro_widget_action = self.iface.addToolBarWidget(self._agro_btn)

        # ── 4. Bases Geográficas (dropdown) ───────────────────────────────────
        self._geodata_btn = self._make_dropdown_btn(
            self._icon('basesGeo.png') if os.path.exists(self._icon('basesGeo.png')) else self._icon('icon.png'),
            u'Bases Geográficas / Geographic Data')
        self._geodata_menu = QMenu(self._geodata_btn)

        _dem_icon = self._icon('dem.png') if os.path.exists(self._icon('dem.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_dem_icon), self.tr(u'RTH Baixar DEM / DEM Downloader'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_dem.open)
        self._geodata_menu.addAction(_act)

        _prodes_icon = self._icon('baixarProdes.png') if os.path.exists(self._icon('baixarProdes.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_prodes_icon), self.tr(u'Baixar PRODES / PRODES Download'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_prodes.run)
        self._geodata_menu.addAction(_act)

        # ── Brazil Public GeoBase ─────────────────────────────────────────────
        _geobase_icon = self._icon('basesGeoBR.png') if os.path.exists(self._icon('basesGeoBR.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_geobase_icon), self.tr(u'Base de Dados Publica do Brasil / Brazil Public GeoBase'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Catalogo centralizado de servicos WMS/WFS de orgaos federais brasileiros (INDE): '
            u'FUNAI, ANA, ICMBio, IBAMA, INCRA, ANM, ANEEL, DNIT, CPRM e outros / '
            u'Centralised catalog of WMS/WFS services from Brazilian federal agencies (INDE): '
            u'FUNAI, ANA, ICMBio, IBAMA, INCRA, ANM, ANEEL, DNIT, CPRM and others'))
        _act.triggered.connect(self.tool_brazil_geobase.run)
        self._geodata_menu.addAction(_act)

        # ── Base de Dados Meteorológicos ──────────────────────────────────────
        _meteo_icon = self._icon('BDMet.png')
        _act = QAction(QIcon(_meteo_icon),
                       self.tr(u'Base de Dados Meteorológicos / Meteorological Data Base'),
                       self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Dados GOES, SAMET, MERGE, ETA e GL1.2 do INPE via STAC API / '
            u'GOES, SAMET, MERGE, ETA and GL1.2 data from INPE via STAC API'))
        _act.triggered.connect(self.tool_meteo_data.run)
        self._geodata_menu.addAction(_act)

        self._geodata_menu.addSeparator()

        # ── Basemaps de Satélite / Satellite Basemaps ─────────────────────────
        _basemaps_icon = self._icon('basesGeo.png') if os.path.exists(self._icon('basesGeo.png')) else self._icon('icon-geral.png')
        _basemaps_submenu = QMenu(self._geodata_menu)
        _basemaps_submenu.setTitle(self.tr(u'Basemaps'))
        _basemaps_submenu.setIcon(QIcon(_basemaps_icon))

        for _bm_name in ('ESRI Satellite', 'Google Satellite', 'Bing Satellite'):
            _act = QAction(self.tr(_bm_name), self.iface.mainWindow())
            _act.triggered.connect(
                lambda _checked=False, _n=_bm_name: self.tool_basemaps.load(_n))
            _basemaps_submenu.addAction(_act)

        self._geodata_menu.addMenu(_basemaps_submenu)

        self._geodata_menu.addSeparator()

        # ── Bases Locais (dinâmico — varre a pasta Mock) ──────────────────────
        self._mock_dynamic_actions = []
        self._geodata_menu.aboutToShow.connect(self._rebuild_mock_section)

        self._geodata_btn.setMenu(self._geodata_menu)
        self._geodata_widget_action = self.iface.addToolBarWidget(self._geodata_btn)

        # ── 5. Estilos Rápidos (dropdown — dinâmico) ──────────────────────────
        self._styles_btn = self._make_dropdown_btn(
            self._icon('quickstyles.png') if os.path.exists(self._icon('quickstyles.png')) else self._icon('icon-geral.png'),
            u'Estilos Rápidos / Quick Styles')
        self._styles_menu = QMenu(self._styles_btn)
        self._styles_menu.aboutToShow.connect(
            lambda: self.tool_quick_style.rebuild_style_menu(self._styles_menu))
        self._styles_btn.setMenu(self._styles_menu)
        self._styles_widget_action = self.iface.addToolBarWidget(self._styles_btn)

        # ── 6. Layouts de Impressão Rápidos (dropdown — dinâmico) ─────────────
        self._layouts_btn = self._make_dropdown_btn(
            self._icon('quickmaps.png') if os.path.exists(self._icon('quickmaps.png')) else self._icon('icon-geral.png'),
            u'Layouts de Impressão Rápidos / Quick Print Layouts')
        self._layouts_menu = QMenu(self._layouts_btn)
        self._layouts_menu.aboutToShow.connect(
            lambda: self.tool_quick_style.rebuild_layout_menu(self._layouts_menu))
        self._layouts_btn.setMenu(self._layouts_menu)
        self._layouts_widget_action = self.iface.addToolBarWidget(self._layouts_btn)

        # ── 7. Funcionalidades Adicionais (dropdown) ──────────────────────────
        self._additional_btn = self._make_dropdown_btn(
            self._icon('addfunc.png') if os.path.exists(self._icon('addfunc.png')) else self._icon('icon-geral.png'),
            u'Funcionalidades Adicionais / Additional Tools')
        self._additional_menu = QMenu(self._additional_btn)

        _act = QAction(QIcon(self._icon('latlong.png')), self.tr(u'Identificar Localização / Identify Location'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Clique no mapa para exibir e copiar cidade, município, estado e país via Nominatim/OpenStreetMap / Click on the map to display and copy city, municipality, state and country via Nominatim/OpenStreetMap'))
        _act.triggered.connect(self.tool_reverse_geocode.activate)
        self._additional_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('latlong.png')), self.tr(u'Capturar Lat/Long / Lat Long Picker'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_latlong.activate)
        self._additional_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('get.png')), self.tr(u'Capturar JSON / Catch JSON'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_catch_json.export)
        self._additional_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('earth.png')), self.tr(u'Enviar ao Google Pro / Send to Google Pro'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_send_google.activate)
        self._additional_menu.addAction(_act)

        _earth_poly_icon = self._icon('earth.png') if os.path.exists(self._icon('earth.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_earth_poly_icon), self.tr(u'Enviar Poligono Google Earth Pro / Send Polygon to Google Earth Pro'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Envia o(s) poligono(s) selecionado(s) ao Google Earth Pro apenas com o tracado (sem preenchimento) / Sends selected polygon(s) to Google Earth Pro outline only (no fill)'))
        _act.triggered.connect(self.tool_send_polygon.run)
        self._additional_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('area.png')), self.tr(u'Calcular Área / Calc Area (ha)'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_calc_area.calculate)
        self._additional_menu.addAction(_act)

        _perim_icon = self._icon('perim.png') if os.path.exists(self._icon('perim.png')) else self._icon('area.png')
        _act = QAction(QIcon(_perim_icon), self.tr(u'Calcular Perímetro / Calc Perimeter (m)'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Calcula o perímetro total das feições selecionadas em metros ou km com projeção UTM regional / Calculates total perimeter of selected features in metres or km using regional UTM projection'))
        _act.triggered.connect(self.tool_calc_perimeter.calculate)
        self._additional_menu.addAction(_act)

        _measure_icon = self._icon('medirDist.png') if os.path.exists(self._icon('medirDist.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_measure_icon), self.tr(u'Medir Distância / Measure Distance'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Clique em 2 pontos no mapa para medir a distância em metros / Click 2 points on the map to measure distance in metres'))
        _act.triggered.connect(self.tool_measure.run)
        self._additional_menu.addAction(_act)

        _canopy_icon = self._icon('MedirCopa.png') if os.path.exists(self._icon('MedirCopa.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_canopy_icon), self.tr(u'Medir Copa das Árvores / Measure Tree Canopy'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Clique no centro da árvore, mova até a borda da copa e clique de novo. '
            u'Mostra diâmetro acima e raio abaixo em tempo real. / '
            u'Click tree centre, move to canopy edge, click again. '
            u'Shows diameter above and radius below in real-time.'))
        _act.triggered.connect(self.tool_measure_canopy.run)
        self._additional_menu.addAction(_act)

        _rename_icon = self._icon('renomearRapido.png') if os.path.exists(self._icon('renomearRapido.png')) else self._icon('icon-geral.png')
        self._action_rename = QAction(QIcon(_rename_icon), self.tr(u'★  Renomear Layer Rápido / Quick Layer Rename'), self.iface.mainWindow())
        self._action_rename.setToolTip(self.tr(u'Adiciona ou remove ★ no início do nome da(s) camada(s) selecionada(s) / Add or remove ★ at the start of selected layer name(s)'))
        self._action_rename.triggered.connect(self.tool_rename_layer.run)
        self._additional_menu.addAction(self._action_rename)
        self.iface.registerMainWindowAction(self._action_rename, '')

        _arcgis_icon = self._icon('exportarArcgis.png') if os.path.exists(self._icon('exportarArcgis.png')) else self._icon('icon-geral.png')
        _act = QAction(QIcon(_arcgis_icon), self.tr(u'Exportar para ArcGIS / Export to ArcGIS'), self.iface.mainWindow())
        _act.setToolTip(self.tr(u'Exporta camadas do projeto para File Geodatabase (.gdb) compatível com ArcGIS / Export project layers to ArcGIS-compatible File Geodatabase (.gdb)'))
        _act.triggered.connect(self.tool_arcgis_export.run)
        self._additional_menu.addAction(_act)

        self._additional_menu.addSeparator()

        # ── Respawn ───────────────────────────────────────────────────────────
        _spawn_set_icon      = self._icon('SetarSpawn.png') if os.path.exists(self._icon('SetarSpawn.png')) else self._icon('icon-geral.png')
        _spawn_teleport_icon = self._icon('TeleportSpawn.png') if os.path.exists(self._icon('TeleportSpawn.png')) else self._icon('icon-geral.png')
        _spawn_submenu = QMenu(self._additional_menu)
        _spawn_submenu.setTitle(self.tr(u'Respawn'))
        _spawn_submenu.setIcon(QIcon(_spawn_set_icon))

        _act = QAction(QIcon(_spawn_set_icon), self.tr(u'Setar Spawn / Set Spawn'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Salva a posição e escala atuais do mapa como ponto de spawn. / '
            u'Saves current map position and scale as spawn point.'))
        _act.triggered.connect(self.tool_respawn.set_spawn)
        _spawn_submenu.addAction(_act)

        _act = QAction(QIcon(_spawn_teleport_icon), self.tr(u'Teleportar para Spawn / Teleport to Spawn'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Volta a câmera do mapa para o spawn salvo com a mesma posição e escala. / '
            u'Returns map camera to saved spawn with the same position and scale.'))
        _act.triggered.connect(self.tool_respawn.teleport)
        _spawn_submenu.addAction(_act)

        self._additional_menu.addMenu(_spawn_submenu)

        # ── Buscar no Street View ─────────────────────────────────────────────
        _sv_icon      = self._icon('streetview.png')      if os.path.exists(self._icon('streetview.png'))      else self._icon('earth.png')
        _sv_add_icon  = self._icon('streetview_add.png')  if os.path.exists(self._icon('streetview_add.png'))  else _sv_icon
        _sv_goto_icon = self._icon('streetview_goto.png') if os.path.exists(self._icon('streetview_goto.png')) else _sv_icon
        _sv_submenu = QMenu(self._additional_menu)
        _sv_submenu.setTitle(self.tr(u'Buscar no Street / Street View'))
        _sv_submenu.setIcon(QIcon(_sv_icon))

        _act = QAction(QIcon(_sv_add_icon), self.tr(u'Adicionar Camada Street View / Add Street View Layer'), self.iface.mainWindow())
        _act.setToolTip(self.tr(
            u'Adiciona a camada de cobertura do Street View (linhas azuis) ao projeto. / '
            u'Adds the Street View coverage layer (blue lines) to the project.'))
        _act.triggered.connect(self.tool_street_view.add_coverage_layer)
        _sv_submenu.addAction(_act)

        _act_goto = QAction(QIcon(_sv_goto_icon), self.tr(u'Me Enviar para Local / Go to Location'), self.iface.mainWindow())
        _act_goto.setCheckable(True)
        _act_goto.setToolTip(self.tr(
            u'Clique no mapa para abrir o Street View naquele ponto. '
            u'Clique e arraste para definir a direção da câmera. / '
            u'Click the map to open Street View at that point. '
            u'Click and drag to set the camera direction.'))
        _act_goto.triggered.connect(self.tool_street_view.goto)
        self.tool_street_view.set_goto_action(_act_goto)
        _sv_submenu.addAction(_act_goto)

        self._additional_menu.addMenu(_sv_submenu)

        _cycle_icon = self._icon('layercycler.png') if os.path.exists(self._icon('layercycler.png')) else self._icon('icon-geral.png')
        _cycle_submenu = QMenu(self._additional_menu)
        _cycle_submenu.setTitle(self.tr(u'Alterar Camadas / Change Layers'))
        _cycle_submenu.setIcon(QIcon(_cycle_icon))

        self._action_cycle = QAction(QIcon(_cycle_icon), self.tr(u'▶  Próxima Camada / Next Layer'), self.iface.mainWindow())
        self._action_cycle.setToolTip(self.tr(u'Avança para a próxima camada no grupo ativo / Advance to next layer in active group'))
        self._action_cycle.triggered.connect(self.tool_layer_switcher.cycle_next)
        _cycle_submenu.addAction(self._action_cycle)
        self.iface.registerMainWindowAction(self._action_cycle, '')

        self._action_cycle_back = QAction(QIcon(_cycle_icon), self.tr(u'◀  Camada Anterior / Previous Layer'), self.iface.mainWindow())
        self._action_cycle_back.setToolTip(self.tr(u'Retrocede para a camada anterior no grupo ativo / Go back to previous layer in active group'))
        self._action_cycle_back.triggered.connect(self.tool_layer_switcher.cycle_prev)
        _cycle_submenu.addAction(self._action_cycle_back)
        self.iface.registerMainWindowAction(self._action_cycle_back, '')

        _cycle_submenu.addSeparator()

        self._action_next_group = QAction(QIcon(_cycle_icon), self.tr(u'→  Próximo Grupo / Next Group'), self.iface.mainWindow())
        self._action_next_group.setToolTip(self.tr(u'Troca para o próximo grupo de alternância (modo Múltiplos Grupos) / Switch to next layer group (Multi-Group mode)'))
        self._action_next_group.triggered.connect(self.tool_layer_switcher.next_group)
        _cycle_submenu.addAction(self._action_next_group)
        self.iface.registerMainWindowAction(self._action_next_group, '')

        self._action_prev_group = QAction(QIcon(_cycle_icon), self.tr(u'←  Grupo Anterior / Previous Group'), self.iface.mainWindow())
        self._action_prev_group.setToolTip(self.tr(u'Troca para o grupo anterior de alternância (modo Múltiplos Grupos) / Switch to previous layer group (Multi-Group mode)'))
        self._action_prev_group.triggered.connect(self.tool_layer_switcher.prev_group)
        _cycle_submenu.addAction(self._action_prev_group)
        self.iface.registerMainWindowAction(self._action_prev_group, '')

        _cycle_submenu.addSeparator()

        _reset_icon = self._icon('resetlayercycler.png') if os.path.exists(self._icon('resetlayercycler.png')) else self._icon('icon-geral.png')
        self._action_cycle_reset = QAction(QIcon(_reset_icon), self.tr(u'↺  Resetar Ciclo / Reset Cycle'), self.iface.mainWindow())
        self._action_cycle_reset.setToolTip(self.tr(u'Restaura a visibilidade de todas as camadas do ciclo / Restore visibility of all cycle layers'))
        self._action_cycle_reset.triggered.connect(self.tool_layer_switcher.reset)
        _cycle_submenu.addAction(self._action_cycle_reset)
        self.iface.registerMainWindowAction(self._action_cycle_reset, '')

        _cycle_submenu.addSeparator()

        _config_icon = self._icon('config.png') if os.path.exists(self._icon('config.png')) else self._icon('icon-geral.png')
        self._action_cycle_config = QAction(QIcon(_config_icon), self.tr(u'Configurar Grupos / Configure Groups'), self.iface.mainWindow())
        self._action_cycle_config.setToolTip(self.tr(u'Abre a janela de configuração de grupos do Layer Switcher / Open Layer Switcher group configuration'))
        self._action_cycle_config.triggered.connect(self.tool_layer_switcher.configure)
        _cycle_submenu.addAction(self._action_cycle_config)

        self._action_cycle_auto = QAction(QIcon(self._icon('icon-geral.png')), self.tr(u'Habilitar Alternância / Enable Auto-Switch'), self.iface.mainWindow())
        self._action_cycle_auto.setToolTip(self.tr(u'Ativa/desativa a alternância automática de camadas por intervalo / Enable/disable automatic layer switching by interval'))
        self._action_cycle_auto.setCheckable(True)
        self._action_cycle_auto.triggered.connect(
            lambda: self.tool_layer_switcher.set_auto(self._action_cycle_auto.isChecked()))
        _cycle_submenu.addAction(self._action_cycle_auto)
        self.tool_layer_switcher.set_auto_action(self._action_cycle_auto)

        self._action_cycle_auto_config = QAction(QIcon(_config_icon), self.tr(u'Configurar Intervalo / Configure Interval'), self.iface.mainWindow())
        self._action_cycle_auto_config.setToolTip(self.tr(u'Define o intervalo em segundos para a alternância automática / Set the interval in seconds for automatic layer switching'))
        self._action_cycle_auto_config.triggered.connect(self.tool_layer_switcher.configure_auto)
        _cycle_submenu.addAction(self._action_cycle_auto_config)

        self._additional_menu.addMenu(_cycle_submenu)

        _cam_icon      = self._icon('camera.png')      if os.path.exists(self._icon('camera.png'))      else self._icon('icon-geral.png')
        _cam_up_icon   = self._icon('cameracima.png')  if os.path.exists(self._icon('cameracima.png'))  else _cam_icon
        _cam_down_icon = self._icon('camerabaixo.png') if os.path.exists(self._icon('camerabaixo.png')) else _cam_icon
        _cam_submenu = QMenu(self._additional_menu)
        _cam_submenu.setTitle(self.tr(u'Deslocamento de Camera / Camera Displacement'))
        _cam_submenu.setIcon(QIcon(_cam_icon))

        self._action_cam_up = QAction(QIcon(_cam_up_icon), self.tr(u'↑  Deslocar para Cima / Shift Up'), self.iface.mainWindow())
        self._action_cam_up.setToolTip(self.tr(u'Desloca o canvas para cima (norte) pelo passo configurado / Shift canvas up (north) by configured step'))
        self._action_cam_up.triggered.connect(self.tool_camera_displacement.pan_up)
        _cam_submenu.addAction(self._action_cam_up)
        self.iface.registerMainWindowAction(self._action_cam_up, '')

        self._action_cam_down = QAction(QIcon(_cam_down_icon), self.tr(u'↓  Deslocar para Baixo / Shift Down'), self.iface.mainWindow())
        self._action_cam_down.setToolTip(self.tr(u'Desloca o canvas para baixo (sul) pelo passo configurado / Shift canvas down (south) by configured step'))
        self._action_cam_down.triggered.connect(self.tool_camera_displacement.pan_down)
        _cam_submenu.addAction(self._action_cam_down)
        self.iface.registerMainWindowAction(self._action_cam_down, '')

        _cam_submenu.addSeparator()

        self._action_cam_auto = QAction(QIcon(_cam_icon), self.tr(u'Habilitar deslocamento / Enable Displacement'), self.iface.mainWindow())
        self._action_cam_auto.setToolTip(self.tr(u'Ativa/desativa o deslocamento automático do canvas / Enable/disable automatic canvas displacement'))
        self._action_cam_auto.setCheckable(True)
        self._action_cam_auto.triggered.connect(
            lambda: self.tool_camera_displacement.set_auto(self._action_cam_auto.isChecked()))
        self.tool_camera_displacement.set_auto_action(self._action_cam_auto)
        _cam_submenu.addAction(self._action_cam_auto)

        self._action_cam_config = QAction(QIcon(_config_icon), self.tr(u'Configurar / Configure'), self.iface.mainWindow())
        self._action_cam_config.setToolTip(self.tr(u'Define o passo (% da tela) e o intervalo automático em segundos / Set step size (% of screen) and auto interval in seconds'))
        self._action_cam_config.triggered.connect(self.tool_camera_displacement.configure)
        _cam_submenu.addAction(self._action_cam_config)

        self._additional_menu.addMenu(_cam_submenu)

        _autosave_icon = self._icon('AutoSave.png') if os.path.exists(self._icon('AutoSave.png')) else self._icon('icon-geral.png')
        _autosave_submenu = QMenu(self._additional_menu)
        _autosave_submenu.setTitle(self.tr(u'Auto-Save'))
        _autosave_submenu.setIcon(QIcon(_autosave_icon))

        _autosave_toggle_icon = self._icon('AutoSave.png') if os.path.exists(self._icon('AutoSave.png')) else self._icon('icon-geral.png')
        _autosave_config_icon = self._icon('config.png') if os.path.exists(self._icon('config.png')) else self._icon('icon-geral.png')

        self._action_autosave_toggle = QAction(QIcon(_autosave_toggle_icon), self.tr(u'Habilitar Auto-Save / Enable Auto-Save'), self.iface.mainWindow())
        self._action_autosave_toggle.setCheckable(True)
        self._action_autosave_toggle.triggered.connect(self.tool_auto_save.toggle)
        self.tool_auto_save.set_toggle_action(self._action_autosave_toggle)
        _autosave_submenu.addAction(self._action_autosave_toggle)

        _act = QAction(QIcon(_autosave_config_icon), self.tr(u'Configurar Intervalo / Configure Interval'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_auto_save.configure)
        _autosave_submenu.addAction(_act)

        self._additional_menu.addMenu(_autosave_submenu)

        self._additional_btn.setMenu(self._additional_menu)
        self._additional_widget_action = self.iface.addToolBarWidget(self._additional_btn)

        # ── 9. RTH World Explorer (dropdown) ─────────────────────────────────
        _explorer_icon = self._icon('Rth-World.png') if os.path.exists(self._icon('Rth-World.png')) else self._icon('icon-geral.png')
        self._explorer_btn = self._make_dropdown_btn(_explorer_icon, u'RTH World Explorer')
        self._explorer_menu = QMenu(self._explorer_btn)

        # Site do Aplicativo de Celular
        _act = QAction(QIcon(self._icon('DocApp.png')), self.tr(u'Site do Aplicativo de Celular / Mobile App Website'), self.iface.mainWindow())
        _act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl('https://rithon.com.br/pages/rth-explorer/')))
        self._explorer_menu.addAction(_act)

        # Aplicativo na Playstore
        _act = QAction(QIcon(self._icon('PlaystoreAPP.png')), self.tr(u'Aplicativo na Playstore / App on Playstore'), self.iface.mainWindow())
        _act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl('https://play.google.com/store/apps/details?id=com.rth.rth_world_explorer')))
        self._explorer_menu.addAction(_act)

        self._explorer_menu.addSeparator()

        # Importar Rota GPX
        _act = QAction(QIcon(self._icon('ImportRota.png')), self.tr(u'Importar Rota / Import Route'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_route_gpx.run)
        self._explorer_menu.addAction(_act)

        # Importar Pontos de Validação
        _act = QAction(QIcon(self._icon('ImportPoints.png')), self.tr(u'Importar Pontos de Validação / Import Validation Points'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_validation_pts.run)
        self._explorer_menu.addAction(_act)

        # Importar Pontos de Benfeitorias
        _benf_icon = self._icon('ImportBenf.png') if os.path.exists(self._icon('ImportBenf.png')) else self._icon('ImportPoints.png')
        _act = QAction(QIcon(_benf_icon), self.tr(u'Importar Pontos de Benfeitorias / Import Infrastructure Points'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_benfeitorias.run)
        self._explorer_menu.addAction(_act)

        # Importar Parâmetros Produtivos
        _act = QAction(QIcon(self._icon('ImportPP.png')), self.tr(u'Importar Parâmetros Produtivos / Import Productive Parameters'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_productive_params.run)
        self._explorer_menu.addAction(_act)

        self._explorer_menu.addSeparator()

        # Pontos de GPS para Polígono
        _ptp_icon = self._icon('pts2poly.png') if os.path.exists(self._icon('pts2poly.png')) else self._icon('icon.png')
        _act = QAction(QIcon(_ptp_icon), self.tr(u'Pontos de GPS para Polígono / GPS Points to Polygon'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_pts_to_poly.run)
        self._explorer_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('grid.png')), self.tr(u'Grid de Pontos / Point Grid'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_point_grid.run)
        self._explorer_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('gridexport.png')), self.tr(u'Exportar Grid CSV / Export Grid CSV'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_export_csv.run)
        self._explorer_menu.addAction(_act)

        _act = QAction(QIcon(self._icon('gridimport.png')), self.tr(u'Importar Grid CSV / Import Grid CSV'), self.iface.mainWindow())
        _act.triggered.connect(self.tool_import_csv.run)
        self._explorer_menu.addAction(_act)

        self._explorer_btn.setMenu(self._explorer_menu)
        self._explorer_widget_action = self.iface.addToolBarWidget(self._explorer_btn)

        # ── 10. Informações / Info ───────────────────────────────────────────
        _info_icon = self._icon('info.png') if os.path.exists(self._icon('info.png')) else self._icon('icon-geral.png')
        self._info_btn = self._make_dropdown_btn(_info_icon, u'Informações / Info')
        self._info_btn.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._info_btn.clicked.connect(self.tool_info.run)
        self._info_widget_action = self.iface.addToolBarWidget(self._info_btn)

    def unload(self):
        """Remove o plugin da interface do QGIS / Remove the plugin from the QGIS interface."""
        if hasattr(self, 'tool_auto_save'):
            self.tool_auto_save.stop()
        if hasattr(self, 'tool_layer_switcher'):
            self.tool_layer_switcher.stop()
        if hasattr(self, 'tool_camera_displacement'):
            self.tool_camera_displacement.stop()
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
            self.iface.unregisterMainWindowAction(action)
        for attr in ('_action_rename', '_action_cycle', '_action_cycle_back',
                     '_action_next_group', '_action_prev_group',
                     '_action_cycle_reset', '_action_cycle_config'):
            if hasattr(self, attr):
                self.iface.unregisterMainWindowAction(getattr(self, attr))
        from qgis.PyQt.QtWidgets import QToolBar
        toolbar = self.iface.mainWindow().findChild(QToolBar, 'mPluginToolBar')
        for attr in ('_gee_widget_action', '_agro_widget_action', '_geodata_widget_action',
                     '_styles_widget_action', '_layouts_widget_action',
                     '_rth_ml_widget_action', '_sr_widget_action',
                     '_additional_widget_action', '_explorer_widget_action',
                     '_info_widget_action'):
            if hasattr(self, attr) and getattr(self, attr) and toolbar:
                toolbar.removeAction(getattr(self, attr))

    def _rebuild_mock_section(self):
        """Reconstrói os itens dinâmicos da pasta Mock no menu de Bases Geográficas.
        Rebuild dynamic Mock-folder items in the Geographic Data menu.
        """
        for act in self._mock_dynamic_actions:
            self._geodata_menu.removeAction(act)
        self._mock_dynamic_actions.clear()

        mock_dir = os.path.join(self.plugin_dir, 'Mock')
        _exts = ('.gpkg', '.shp', '.geojson', '.json', '.kml', '.kmz')
        files = []
        if os.path.isdir(mock_dir):
            files = sorted(
                f for f in os.listdir(mock_dir)
                if os.path.isfile(os.path.join(mock_dir, f))
                and f.lower().endswith(_exts)
            )

        if files:
            for fname in files:
                label = os.path.splitext(fname)[0].replace('_', ' ').replace('-', ' ')
                act = QAction(label, self._geodata_menu)
                act.triggered.connect(
                    lambda checked, fn=fname, lbl=label: self._load_mock_layer(fn, lbl))
                self._geodata_menu.addAction(act)
                self._mock_dynamic_actions.append(act)
        else:
            act = QAction(
                self.tr(u'Nenhum arquivo na pasta Mock / No files in Mock folder'),
                self._geodata_menu)
            act.setEnabled(False)
            self._geodata_menu.addAction(act)
            self._mock_dynamic_actions.append(act)

        sep = self._geodata_menu.addSeparator()
        self._mock_dynamic_actions.append(sep)

        hint = QAction(
            self.tr(u'↳  Adicione .gpkg/.shp à pasta Mock para aparecerem aqui  /  Add .gpkg/.shp to Mock folder'),
            self._geodata_menu)
        hint.setEnabled(False)
        self._geodata_menu.addAction(hint)
        self._mock_dynamic_actions.append(hint)

        open_act = QAction(
            self.tr(u'Abrir pasta Mock / Open Mock folder'), self._geodata_menu)
        open_act.triggered.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.join(self.plugin_dir, 'Mock'))))
        self._geodata_menu.addAction(open_act)
        self._mock_dynamic_actions.append(open_act)

    def _load_mock_layer(self, filename, display_name):
        """Carrega um arquivo vetorial da pasta Mock e adiciona ao projeto.
        Load a vector file from the Mock folder and add to project.
        """
        from qgis.core import QgsVectorLayer, QgsProject
        from qgis.PyQt.QtWidgets import QMessageBox
        path = os.path.join(self.plugin_dir, 'Mock', filename)
        if not os.path.exists(path):
            QMessageBox.warning(
                None, 'RTH Bases Geográficas',
                'Arquivo não encontrado / File not found:\n{}'.format(path))
            return
        from core.rth_layer_utils import collapse_layer
        layer = QgsVectorLayer(path, display_name, 'ogr')
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            collapse_layer(layer)
            self.iface.messageBar().pushMessage(
                'RTH Bases Geográficas',
                '{} carregado / loaded'.format(display_name),
                level=Qgis.MessageLevel.Info, duration=4)
        else:
            QMessageBox.warning(
                None, 'RTH Bases Geográficas',
                'Erro ao carregar / Error loading:\n{}'.format(path))

    def open_rth_series(self):
        """Abre o aplicativo RTH Series no navegador padrão / Open RTH Series app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseries'))

    def open_rth_vegtime(self):
        """Abre o aplicativo RTH Series Veg Time no navegador padrão / Open RTH Series Veg Time app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseriesvegtime'))

    def open_rth_climate_viewer(self):
        """Abre o aplicativo RTH Climate Viewer no navegador padrão / Open RTH Climate Viewer app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseriesclimateviewer'))

    def open_rth_deforest_check(self):
        """Abre o aplicativo RTH Deforest Check no navegador padrão / Open RTH Deforest Check app in the default browser."""
        QDesktopServices.openUrl(QUrl('https://luciano-ufsc.projects.earthengine.app/view/rthseriesmonth'))

    def open_rth_ui(self):
        """Abre o diálogo principal do RTH API BROWSER / Open the main RTH API BROWSER dialog."""
        # Verifica se o módulo de diálogo foi carregado / Check if dialog module was loaded
        if self.dialog_class is None:
            self.iface.messageBar().pushMessage(
                'RTH', 'Módulo de diálogo não disponível / Dialog module not available', level=Qgis.MessageLevel.Warning)
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
            self.iface.messageBar().pushMessage('RTH', str(e), level=Qgis.MessageLevel.Warning)
