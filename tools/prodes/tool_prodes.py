# -*- coding: utf-8 -*-
"""
PRODES Download — Visualização WMS e download WFS de dados de desmatamento.
Fonte: TerraBrasilis / INPE (https://terrabrasilis.dpi.inpe.br)

Abordagem:
  - Carregar WMS : carrega camada raster via GeoServer WMS com parâmetro TIME
                   (mesma abordagem do plugin oficial TerraBrasilis Data Source)
  - Baixar Vetor : acessa WFS e salva como GeoPackage
"""
import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    Qgis,
    QgsRasterLayer, QgsVectorLayer, QgsProject,
    QgsVectorFileWriter, QgsCoordinateTransformContext
)

from .tool_prodes_dialog import ProdesDialog
from .tool_prodes_sources import BIOMES, PRODES_WMS_BASE, PRODES_WFS_BASE
from core.rth_layer_utils import collapse_layer


class ProdesDownloadTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg = None

    def tr(self, message):
        return QCoreApplication.translate('ProdesDownloadTool', message)

    def run(self):
        if self._dlg is None:
            self._dlg = ProdesDialog(self.iface)
            self._dlg.btn_run.clicked.connect(self._on_run)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    # ------------------------------------------------------------------
    # Despacho principal / Main dispatch
    # ------------------------------------------------------------------

    def _on_run(self):
        params      = self._dlg.get_params()
        layers_info = self._resolve_layers(params)

        if not layers_info:
            self._dlg.set_progress(
                self.tr(u'Nenhum dado disponível para os parâmetros selecionados / '
                        u'No data available for the selected parameters'),
                error=True
            )
            return

        if params['mode'] == 'wms':
            self._load_wms(layers_info)
        else:
            self._download_wfs(layers_info, params)

    # ------------------------------------------------------------------
    # Resolução de camadas / Layer resolution
    # ------------------------------------------------------------------

    def _resolve_layers(self, params):
        brasil    = params['brasil']
        biome_idx = params['biome_idx']
        tipo      = params['tipo']
        ano       = params['ano']

        biomes = BIOMES if brasil else [BIOMES[biome_idx]]
        result = []

        for b in biomes:
            if tipo == 'yearly':
                layer_name = b['yearly_layer']
                display    = 'PRODES {0} {1}'.format(b['name'], ano if ano else '')
            else:
                layer_name = b['accumulated_layer']
                if layer_name is None:
                    continue  # bioma sem camada acumulada (ex.: Mata Atlântica)
                display = 'PRODES {0} Acumulado'.format(b['name'])

            result.append({
                'display':   display.strip(),
                'workspace': b['workspace'],
                'layer':     layer_name,
                'tipo':      tipo,
                'ano':       ano,
                'crs':       b.get('crs', 4674),
            })

        return result

    # ------------------------------------------------------------------
    # WMS — Carregar via raster (abordagem TerraBrasilis)
    # ------------------------------------------------------------------

    def _build_wms_uri(self, workspace, layer, ano, crs=4674):
        """
        Constrói a URI WMS para QGIS seguindo o padrão do plugin TerraBrasilis.
        Para incremento anual, o parâmetro TIME é embutido diretamente na URL base
        (TIME%3D = TIME=, %26 = &), garantindo que o GeoServer filtre pelo ano.
        O CRS é obtido do bioma — a maioria usa EPSG:4674, o mosaico não-floresta usa EPSG:4326.
        """
        epsg = 'EPSG:{0}'.format(crs)
        if ano:
            # TIME embutido na URL — método comprovado pelo TerraBrasilis
            wms_url = (
                '{base}/{ws}/wms'
                '?TIME%3D{year}%26LAYERS%3D{layer}'
            ).format(base=PRODES_WMS_BASE, ws=workspace, year=ano, layer=layer)
            return (
                'IgnoreGetFeatureInfoUrl=1&IgnoreGetMapUrl=1&contextualWMSLegend=0'
                '&crs={epsg}&format=image/png'
                '&layers={layer}&styles=&url={url}'
            ).format(epsg=epsg, layer=layer, url=wms_url)
        else:
            # Acumulado — camada estática sem filtro temporal
            return (
                'url={base}/{ws}/wms'
                '&crs={epsg}&format=image/png'
                '&layers={layer}&styles=&version=1.3.0'
            ).format(base=PRODES_WMS_BASE, ws=workspace, epsg=epsg, layer=layer)

    def _load_wms(self, layers_info):
        total = len(layers_info)
        self._dlg.set_busy(True, 'Carregando...')
        self._dlg.set_progress('', value=0, maximum=total)
        loaded = 0

        for i, info in enumerate(layers_info):
            self._dlg.set_progress(
                self.tr(u'Carregando {0}...').format(info['display']),
                value=i, maximum=total
            )
            uri   = self._build_wms_uri(info['workspace'], info['layer'], info['ano'], info.get('crs', 4674))
            layer = QgsRasterLayer(uri, info['display'], 'wms')

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                collapse_layer(layer)
                loaded += 1
            else:
                self._dlg.set_progress(
                    self.tr(u'Erro ao carregar {0} — verifique conexão').format(info['display']),
                    value=i + 1, error=True
                )

        self._dlg.set_busy(False)
        self._dlg.set_progress(
            self.tr(u'{0}/{1} camada(s) carregada(s) com sucesso / {0}/{1} layer(s) loaded').format(
                loaded, total),
            value=total, maximum=total,
            error=(loaded < total)
        )

    # ------------------------------------------------------------------
    # WFS — Baixar vetor como GeoPackage
    # ------------------------------------------------------------------

    def _build_wfs_uri(self, workspace, layer, ano, crs=4674):
        """
        Constrói a URI WFS para QGIS. O filtro de ano usa OGC Filter XML
        sobre o campo 'year', que é o nome padrão no GeoServer do TerraBrasilis.
        Se o servidor rejeitar o filtro, a camada ainda carrega sem ele.
        """
        url = '{base}/{ws}/ows'.format(base=PRODES_WFS_BASE, ws=workspace)
        uri = (
            "pagingEnabled='false' "
            "preferCoordinatesForWfsT11='false' "
            "srsname='EPSG:{crs}' "
            "typename='{ws}:{layer}' "
            "url='{url}' "
            "version='auto'"
        ).format(crs=crs, ws=workspace, layer=layer, url=url)

        if ano:
            ogc_filter = (
                '<Filter>'
                '<PropertyIsEqualTo>'
                '<PropertyName>year</PropertyName>'
                '<Literal>{ano}</Literal>'
                '</PropertyIsEqualTo>'
                '</Filter>'
            ).format(ano=ano)
            uri += " filter='{0}'".format(ogc_filter)

        return uri

    def _write_layer(self, wfs_layer, out_path):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName   = 'GPKG'
        opts.fileEncoding = 'UTF-8'
        res   = QgsVectorFileWriter.writeAsVectorFormatV2(
            wfs_layer, out_path, QgsCoordinateTransformContext(), opts
        )
        error = res[0]
        msg   = res[1] if len(res) > 1 else ''
        if error != QgsVectorFileWriter.NoError:
            return False, msg
        return True, ''

    def _download_wfs(self, layers_info, params):
        out_dir = params['out_dir']
        if not out_dir:
            self.iface.messageBar().pushMessage(
                'PRODES',
                self.tr(u'Selecione uma pasta de saída antes de continuar / Select an output folder first'),
                level=Qgis.MessageLevel.Warning, duration=4
            )
            return

        os.makedirs(out_dir, exist_ok=True)

        total = len(layers_info)
        self._dlg.set_busy(True, 'Baixando...')
        self._dlg.set_progress('', value=0, maximum=total)
        saved = 0

        for i, info in enumerate(layers_info):
            self._dlg.set_progress(
                self.tr(u'Baixando {0}...').format(info['display']),
                value=i, maximum=total
            )

            uri   = self._build_wfs_uri(info['workspace'], info['layer'], info['ano'], info.get('crs', 4674))
            layer = QgsVectorLayer(uri, info['display'], 'WFS')

            if not layer.isValid():
                self._dlg.set_progress(
                    self.tr(u'Erro ao acessar WFS: {0}').format(info['display']),
                    value=i + 1, error=True
                )
                continue

            safe_name = info['display'].replace('/', '-').replace(':', '-')
            out_path  = os.path.join(out_dir, safe_name + '.gpkg')
            ok, err   = self._write_layer(layer, out_path)

            if ok:
                saved += 1
                saved_layer = QgsVectorLayer(out_path, info['display'], 'ogr')
                QgsProject.instance().addMapLayer(saved_layer)
                collapse_layer(saved_layer)
            else:
                self._dlg.set_progress(
                    self.tr(u'Erro ao salvar {0}: {1}').format(info['display'], err),
                    value=i + 1, error=True
                )

        self._dlg.set_busy(False)
        self._dlg.set_progress(
            self.tr(u'{0}/{1} arquivo(s) salvo(s) em: {2}').format(saved, total, out_dir),
            value=total, maximum=total,
            error=(saved < total)
        )
