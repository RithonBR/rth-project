# -*- coding: utf-8 -*-
"""
RTH Exportar para ArcGIS — exporta camadas QGIS para File Geodatabase (.gdb).

Abordagem:
  - Vetoriais : escritas via OGR / OpenFileGDB driver (GDAL >= 3.6)
  - Rasters   : exportados como GeoTIFF na subpasta rasters/
                (WMS/XYZ/Tile são ignorados com aviso — não têm dados locais)
  - Nomes     : sanitizados (sem acentos, espaços, caracteres especiais)
  - Grupos    : mapeados para Feature Datasets via layer creation option
  - Simbologia: exportada como SLD por camada (opcional)
  - Relatório : TXT com lista de camadas, CRS, erros e instruções ArcGIS
"""
import os
import re
import datetime
import unicodedata

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsWkbTypes, QgsRasterFileWriter, QgsRasterPipe, QgsGeometry
)

try:
    from osgeo import ogr, osr, gdal
    gdal.UseExceptions()
    HAS_OGR = True
except ImportError:
    HAS_OGR = False

# Provedores raster que têm dados locais e podem ser exportados como GeoTIFF
_EXPORTABLE_RASTER_PROVIDERS = {'gdal', 'virtualraster', 'wcs', 'grass'}


# ---------------------------------------------------------------------------
# Sanitização / Sanitization
# ---------------------------------------------------------------------------

def _sanitize(name, max_len=64):
    decomposed = unicodedata.normalize('NFD', str(name))
    no_accents  = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    clean       = re.sub(r'[^a-zA-Z0-9_]', '_', no_accents)
    clean       = re.sub(r'_+', '_', clean).strip('_')
    if clean and clean[0].isdigit():
        clean = '_' + clean
    return clean[:max_len].rstrip('_') or 'unnamed'


def _coerce_to_layer_type(geom, expected_geom_type):
    """
    Garante que a geometria bate com o tipo esperado da camada.
    Extrai partes compatíveis de GeometryCollections (comum após makeValid).
    Retorna (geom_corrigida, foi_coercida) ou (None, False) se impossível.
    """
    if geom is None or geom.isNull():
        return None, False
    actual = QgsWkbTypes.geometryType(geom.wkbType())
    if actual == expected_geom_type:
        return geom, False
    converted = geom.convertToType(expected_geom_type, destMulti=True)
    if converted and not converted.isNull():
        return converted, True
    return None, False


def _unique_name(name, used_set, max_len=64):
    candidate = name
    idx = 1
    while candidate.lower() in used_set:
        suffix    = '_{0}'.format(idx)
        candidate = name[:max_len - len(suffix)] + suffix
        idx += 1
    used_set.add(candidate.lower())
    return candidate


# ---------------------------------------------------------------------------
# Mapeamento de tipos / Type mapping
# ---------------------------------------------------------------------------

def _ogr_field_type(qvariant_type):
    mapping = {
        QVariant.String:    ogr.OFTString,
        QVariant.Int:       ogr.OFTInteger,
        QVariant.UInt:      ogr.OFTInteger,
        QVariant.LongLong:  ogr.OFTInteger64,
        QVariant.ULongLong: ogr.OFTInteger64,
        QVariant.Double:    ogr.OFTReal,
        QVariant.Bool:      ogr.OFTInteger,
        QVariant.Date:      ogr.OFTDate,
        QVariant.Time:      ogr.OFTTime,
        QVariant.DateTime:  ogr.OFTDateTime,
    }
    return mapping.get(qvariant_type, ogr.OFTString)


def _detect_ogr_geom_type(layer):
    """Converte o tipo WKB do layer QGIS para o equivalente OGR.

    Se o tipo for desconhecido, amostra a primeira feição para inferir.
    Retorna None se não for possível determinar — camada deve ser ignorada.
    """
    wkb  = layer.wkbType()
    flat = QgsWkbTypes.flatType(wkb)
    has_z = QgsWkbTypes.hasZ(wkb)

    base_map = {
        QgsWkbTypes.Point:              ogr.wkbPoint,
        QgsWkbTypes.LineString:         ogr.wkbLineString,
        QgsWkbTypes.Polygon:            ogr.wkbPolygon,
        QgsWkbTypes.MultiPoint:         ogr.wkbMultiPoint,
        QgsWkbTypes.MultiLineString:    ogr.wkbMultiLineString,
        QgsWkbTypes.MultiPolygon:       ogr.wkbMultiPolygon,
        QgsWkbTypes.GeometryCollection: ogr.wkbGeometryCollection,
        QgsWkbTypes.NoGeometry:         ogr.wkbNone,
    }

    ogr_type = base_map.get(flat)

    # Tipo desconhecido — amostra primeira feição
    if ogr_type is None:
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if geom and not geom.isNull():
                wkb_bytes = bytes(geom.asWkb())
                if wkb_bytes:
                    sample = ogr.CreateGeometryFromWkb(wkb_bytes)
                    if sample:
                        ogr_type = sample.GetGeometryType()
                        has_z    = False   # já embutido no tipo amostrado
                        break

    if ogr_type is None:
        return None  # não foi possível detectar

    # Adiciona dimensão Z se necessário
    if has_z and ogr_type not in (ogr.wkbNone,):
        z_map = {
            ogr.wkbPoint:           ogr.wkbPoint25D,
            ogr.wkbLineString:      ogr.wkbLineString25D,
            ogr.wkbPolygon:         ogr.wkbPolygon25D,
            ogr.wkbMultiPoint:      ogr.wkbMultiPoint25D,
            ogr.wkbMultiLineString: ogr.wkbMultiLineString25D,
            ogr.wkbMultiPolygon:    ogr.wkbMultiPolygon25D,
        }
        ogr_type = z_map.get(ogr_type, ogr_type)

    return ogr_type


def _to_python(val):
    if val is None:
        return None
    if isinstance(val, QVariant):
        if not val.isValid() or val.isNull():
            return None
        val = val.value()
    from qgis.PyQt.QtCore import QDate, QTime, QDateTime
    if isinstance(val, QDateTime):
        return val.toString('yyyy-MM-dd HH:mm:ss') if val.isValid() else None
    if isinstance(val, QDate):
        return val.toString('yyyy-MM-dd') if val.isValid() else None
    if isinstance(val, QTime):
        return val.toString('HH:mm:ss') if val.isValid() else None
    if isinstance(val, datetime.datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(val, datetime.date):
        return val.strftime('%Y-%m-%d')
    return val


# ---------------------------------------------------------------------------
# Auxiliar de grupo / Group helper
# ---------------------------------------------------------------------------

def _layer_group(layer):
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(layer.id())
    if node is None:
        return None
    parent = node.parent()
    if parent is root or parent is None:
        return None
    return parent.name()


# ---------------------------------------------------------------------------
# Ferramenta principal / Main tool
# ---------------------------------------------------------------------------

class ArcGISExportTool:

    def __init__(self, iface):
        self.iface = iface
        self._dlg  = None

    def tr(self, message):
        return QCoreApplication.translate('ArcGISExportTool', message)

    def run(self):
        if self._dlg is None:
            from .tool_arcgis_export_dialog import ArcGISExportDialog
            self._dlg = ArcGISExportDialog(self.iface, self.iface.mainWindow())
            self._dlg.export_requested.connect(self._on_export)
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()

    # ------------------------------------------------------------------
    # Despacho principal / Main dispatch
    # ------------------------------------------------------------------

    def _on_export(self, params):
        dlg = self._dlg

        if not HAS_OGR:
            dlg.log_error(self.tr(u'GDAL/OGR não encontrado. Verifique a instalação do QGIS.'))
            dlg.set_busy(False)
            return

        driver = ogr.GetDriverByName('OpenFileGDB')
        if driver is None:
            dlg.log_error(self.tr(u'Driver OpenFileGDB não disponível (requer GDAL >= 3.6).'))
            dlg.set_busy(False)
            return

        out_dir = params['out_dir']
        if not out_dir:
            dlg.log_error(self.tr(u'Selecione um diretório de saída antes de continuar.'))
            dlg.set_busy(False)
            return

        os.makedirs(out_dir, exist_ok=True)

        project = QgsProject.instance()
        if params['only_selected']:
            all_layers = self.iface.layerTreeView().selectedLayers()
        else:
            all_layers = list(project.mapLayers().values())

        vector_layers = [l for l in all_layers if isinstance(l, QgsVectorLayer)]
        raster_layers = ([l for l in all_layers if isinstance(l, QgsRasterLayer)]
                         if params['include_raster'] else [])

        total = len(vector_layers) + len(raster_layers)
        if total == 0:
            dlg.log_warn(self.tr(u'Nenhuma camada encontrada para exportar.'))
            dlg.set_busy(False)
            return

        dlg.set_progress(0, total)

        # Nome da GDB — campo customizado ou nome do projeto
        custom = _sanitize(params.get('gdb_name', '').strip(), 32)
        if not custom:
            proj_base = os.path.splitext(os.path.basename(project.fileName()))[0]
            custom    = _sanitize(proj_base or 'RTH_Export', 32)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        gdb_name  = '{0}_{1}.gdb'.format(custom, timestamp)
        gdb_path  = os.path.join(out_dir, gdb_name)

        if os.path.exists(gdb_path):
            import shutil
            shutil.rmtree(gdb_path)

        dlg.log(self.tr(u'Criando geodatabase: {0}').format(gdb_name))
        ds = driver.CreateDataSource(gdb_path)
        if ds is None:
            dlg.log_error(self.tr(u'Falha ao criar a geodatabase. Verifique permissões na pasta.'))
            dlg.set_busy(False)
            return

        results    = []
        used_names = set()
        step       = 0

        for layer in vector_layers:
            step += 1
            dlg.set_progress(step, total, self.tr(u'Exportando: {0}').format(layer.name()))
            results.append(self._export_vector(ds, layer, used_names,
                                               params.get('export_sld', False), out_dir))
            QApplication.processEvents()

        raster_out = os.path.join(out_dir, 'rasters')
        for layer in raster_layers:
            step += 1
            dlg.set_progress(step, total, self.tr(u'Exportando raster: {0}').format(layer.name()))
            results.append(self._export_raster(layer, raster_out))
            QApplication.processEvents()

        ds = None  # flush/close

        if params.get('generate_report', True):
            self._generate_report(out_dir, gdb_name, results, project)

        exported = sum(1 for r in results if r['ok'])
        failed   = len(results) - exported

        dlg.set_progress(total, total, '')
        dlg.log('─' * 50)
        dlg.log(self.tr(u'Concluído: {0} exportada(s)  |  {1} erro(s)').format(exported, failed))
        dlg.log(self.tr(u'GDB: {0}').format(gdb_path))
        dlg.set_busy(False)

    # ------------------------------------------------------------------
    # Exportação vetorial / Vector export
    # ------------------------------------------------------------------

    def _export_vector(self, ds, layer, used_names, export_sld, out_dir):
        dlg = self._dlg
        result = {
            'name': layer.name(), 'type': 'vetor',
            'ok': False, 'error': '', 'crs': layer.crs().authid(), 'safe_name': '',
            'geom_fixed': 0, 'geom_coerced': 0, 'geom_skipped': 0
        }

        try:
            safe_name  = _unique_name(_sanitize(layer.name(), 60), used_names)
            group_name = _layer_group(layer)
            safe_group = _sanitize(group_name, 64) if group_name else None
            result['safe_name'] = safe_name

            # Tipo de geometria — mapeamento explícito (OpenFileGDB não aceita wkbUnknown)
            ogr_type = _detect_ogr_geom_type(layer)
            if ogr_type is None:
                result['error'] = (
                    'Tipo de geometria não reconhecido (wkbType={0}). '
                    'Converta a camada para um formato padrão antes de exportar.'
                ).format(layer.wkbType())
                dlg.log_error('[{0}] {1}'.format(layer.name(), result['error']))
                return result

            srs = osr.SpatialReference()
            srs.ImportFromWkt(layer.crs().toWkt())

            # ── CreateLayer: tenta com Feature Dataset, recai para raiz se o CRS
            #    do grupo for incompatível (gdal.UseExceptions lança exceção, não None)
            ogr_layer = None
            if safe_group:
                layer_opts = ['GEOMETRY_NAME=SHAPE',
                              'FEATURE_DATASET={0}'.format(safe_group)]
                try:
                    ogr_layer = ds.CreateLayer(safe_name, srs=srs,
                                               geom_type=ogr_type, options=layer_opts)
                except Exception:
                    dlg.log_warn(
                        '  [{0}] Grupo "{1}": CRS incompatível com Feature Dataset — '
                        'exportando para raiz da GDB / CRS mismatch, exporting to GDB root.'
                        .format(layer.name(), safe_group))

            if ogr_layer is None:
                try:
                    ogr_layer = ds.CreateLayer(safe_name, srs=srs,
                                               geom_type=ogr_type,
                                               options=['GEOMETRY_NAME=SHAPE'])
                except Exception:
                    ogr_layer = None

            if ogr_layer is None:
                result['error'] = 'OGR não conseguiu criar a layer (nome ou tipo conflitante).'
                dlg.log_error('[{0}] {1}'.format(layer.name(), result['error']))
                return result

            # Campos
            field_map = {}
            used_flds = set()
            for qfield in layer.fields():
                raw       = qfield.name()
                safe_f    = _unique_name(_sanitize(raw, 64), used_flds)
                field_map[raw] = safe_f

                oftype   = _ogr_field_type(qfield.type())
                fld_defn = ogr.FieldDefn(safe_f, oftype)
                if oftype == ogr.OFTString:
                    fld_defn.SetWidth(qfield.length() if qfield.length() > 0 else 255)
                elif oftype == ogr.OFTReal:
                    fld_defn.SetWidth(qfield.length() if qfield.length() > 0 else 20)
                    fld_defn.SetPrecision(qfield.precision() if qfield.precision() > 0 else 6)
                ogr_layer.CreateField(fld_defn)

            # Feições
            invalid_fixed  = 0
            coerced_count  = 0
            skipped_count  = 0
            corrupt_count  = 0
            feat_count     = 0
            expected_geom_type = QgsWkbTypes.geometryType(layer.wkbType())
            ogr_layer.StartTransaction()

            try:
                feat_iter = layer.getFeatures()
            except Exception as exc:
                result['error'] = 'Dados corrompidos — não foi possível ler as feições: {0}'.format(str(exc))
                dlg.log_error('[{0}] {1}'.format(layer.name(), result['error']))
                return result

            for qfeat in feat_iter:
                try:
                    ogr_feat = ogr.Feature(ogr_layer.GetLayerDefn())

                    geom = qfeat.geometry()
                    if geom and not geom.isNull():
                        # 1. Corrige geometria GEOS inválida
                        if not geom.isGeosValid():
                            fixed = geom.makeValid()
                            if fixed and not fixed.isNull():
                                geom = fixed
                                invalid_fixed += 1

                        # 2. Garante que o tipo bate com a camada (makeValid pode mudar o tipo,
                        #    ex: polígono com auto-interseção → GeometryCollection)
                        if expected_geom_type not in (
                                QgsWkbTypes.UnknownGeometry, QgsWkbTypes.NullGeometry):
                            geom, was_coerced = _coerce_to_layer_type(geom, expected_geom_type)
                            if was_coerced:
                                coerced_count += 1
                            if geom is None:
                                # Não foi possível extrair geometria compatível; insere sem geometria
                                skipped_count += 1
                                for qfield in layer.fields():
                                    safe_f = field_map[qfield.name()]
                                    val    = _to_python(qfeat[qfield.name()])
                                    if val is None:
                                        ogr_feat.SetFieldNull(safe_f)
                                    else:
                                        try:
                                            ogr_feat.SetField(safe_f, val)
                                        except Exception:
                                            ogr_feat.SetFieldNull(safe_f)
                                ogr_layer.CreateFeature(ogr_feat)
                                feat_count += 1
                                continue

                        wkb_bytes = bytes(geom.asWkb())
                        if wkb_bytes:
                            ogr_geom = ogr.CreateGeometryFromWkb(wkb_bytes)
                            if ogr_geom:
                                ogr_feat.SetGeometry(ogr_geom)

                    for qfield in layer.fields():
                        safe_f = field_map[qfield.name()]
                        val    = _to_python(qfeat[qfield.name()])
                        if val is None:
                            ogr_feat.SetFieldNull(safe_f)
                        else:
                            try:
                                ogr_feat.SetField(safe_f, val)
                            except Exception:
                                ogr_feat.SetFieldNull(safe_f)

                    ogr_layer.CreateFeature(ogr_feat)
                    feat_count += 1

                except Exception:
                    # Feição com dados corrompidos — ignora e continua / Corrupt feature — skip and continue
                    corrupt_count += 1
                    continue

            ogr_layer.CommitTransaction()

            if invalid_fixed:
                dlg.log_warn('  [{0}] {1} geometria(s) inválida(s) corrigidas automaticamente.'.format(
                    layer.name(), invalid_fixed))
            if coerced_count:
                dlg.log_warn('  [{0}] {1} geometria(s) com tipo convertido após correção.'.format(
                    layer.name(), coerced_count))
            if skipped_count:
                dlg.log_warn('  [{0}] {1} feição(ões) sem geometria válida após correção (atributos preservados).'.format(
                    layer.name(), skipped_count))
            if corrupt_count:
                dlg.log_warn('  [{0}] {1} feição(ões) ignorada(s) por dados corrompidos no arquivo fonte / '
                             '{1} feature(s) skipped due to corrupt data in source file.'.format(
                             layer.name(), corrupt_count))

            group_info = ' → Dataset: {0}'.format(safe_group) if safe_group else ''
            fixes_info = ''
            if invalid_fixed or coerced_count or skipped_count or corrupt_count:
                parts = []
                if invalid_fixed:
                    parts.append('{} geom corrigida(s)'.format(invalid_fixed))
                if corrupt_count:
                    parts.append('{} corrompida(s) ignorada(s)'.format(corrupt_count))
                if coerced_count:
                    parts.append('{} tipo convertido'.format(coerced_count))
                if skipped_count:
                    parts.append('{} sem geom'.format(skipped_count))
                fixes_info = '  ⚠ ' + ', '.join(parts)
            dlg.log('[OK] {0}  →  {1}{2}  ({3} feições, CRS: {4}){5}'.format(
                layer.name(), safe_name, group_info, feat_count,
                layer.crs().authid(), fixes_info))

            if export_sld:
                sld_path = os.path.join(out_dir, safe_name + '.sld')
                ok_sld, msg_sld = layer.saveSldStyle(sld_path)
                if ok_sld:
                    dlg.log('     SLD: {0}.sld'.format(safe_name))
                else:
                    dlg.log_warn('     SLD não exportado: {0}'.format(msg_sld))

            result['ok']           = True
            result['geom_fixed']   = invalid_fixed
            result['geom_coerced'] = coerced_count
            result['geom_skipped'] = skipped_count

        except Exception as exc:
            result['error'] = str(exc)
            dlg.log_error('[{0}] Erro inesperado: {1}'.format(layer.name(), str(exc)))

        return result

    # ------------------------------------------------------------------
    # Exportação raster / Raster export
    # ------------------------------------------------------------------

    def _export_raster(self, layer, out_dir):
        dlg = self._dlg
        result = {
            'name': layer.name(), 'type': 'raster',
            'ok': False, 'error': '', 'crs': layer.crs().authid(), 'safe_name': ''
        }
        try:
            # Detecta provedores sem dados locais (WMS, XYZ, tiles)
            provider_name = layer.dataProvider().name().lower()
            if provider_name not in _EXPORTABLE_RASTER_PROVIDERS:
                result['error'] = (
                    'Provedor "{}" não tem dados locais para exportar '
                    '(WMS/XYZ/Tile). Para exportar, use Camada → Exportar → '
                    '"Salvar como" → GeoTIFF no QGIS antes de rodar esta ferramenta.'
                ).format(provider_name)
                dlg.log_warn('[{0}] Ignorado: {1}'.format(layer.name(), result['error']))
                return result

            os.makedirs(out_dir, exist_ok=True)
            safe_name           = _sanitize(layer.name(), 60)
            out_path            = os.path.join(out_dir, safe_name + '.tif')
            result['safe_name'] = safe_name

            dp   = layer.dataProvider()
            pipe = QgsRasterPipe()
            if not pipe.set(dp.clone()):
                result['error'] = 'Falha ao criar raster pipe'
                dlg.log_error('[{0}] {1}'.format(layer.name(), result['error']))
                return result

            writer = QgsRasterFileWriter(out_path)
            writer.setOutputFormat('GTiff')
            err = writer.writeRaster(pipe, dp.xSize(), dp.ySize(), dp.extent(), dp.crs())

            if err == QgsRasterFileWriter.NoError:
                dlg.log('[OK] Raster {0}  →  rasters/{1}.tif'.format(layer.name(), safe_name))
                result['ok'] = True
            else:
                result['error'] = 'QgsRasterFileWriter error code {0}'.format(err)
                dlg.log_error('[{0}] {1}'.format(layer.name(), result['error']))

        except Exception as exc:
            result['error'] = str(exc)
            dlg.log_error('[{0}] Erro: {1}'.format(layer.name(), str(exc)))

        return result

    # ------------------------------------------------------------------
    # Relatório / Report
    # ------------------------------------------------------------------

    def _generate_report(self, out_dir, gdb_name, results, project):
        dlg = self._dlg
        try:
            report_path = os.path.join(out_dir, 'relatorio_exportacao.txt')
            ok_list  = [r for r in results if r['ok']]
            err_list = [r for r in results if not r['ok']]
            now      = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with open(report_path, 'w', encoding='utf-8') as f:
                _w = f.write
                _w('=' * 64 + '\n')
                _w(' RTH PROJECT — RELATÓRIO DE EXPORTAÇÃO ARCGIS\n')
                _w(' RTH PROJECT — ArcGIS Export Report\n')
                _w('=' * 64 + '\n')
                _w('Data / Date          : {0}\n'.format(now))
                _w('Projeto / Project    : {0}\n'.format(project.fileName() or '(sem arquivo)'))
                _w('CRS do Projeto       : {0}\n'.format(project.crs().authid()))
                _w('Geodatabase          : {0}\n'.format(gdb_name))
                _w('Total exportadas     : {0}/{1}\n'.format(len(ok_list), len(results)))
                _w('\n')

                _w('─' * 64 + '\n')
                _w('CAMADAS EXPORTADAS COM SUCESSO / SUCCESSFULLY EXPORTED LAYERS\n')
                _w('─' * 64 + '\n')
                for r in ok_list:
                    _w('  [OK]  {0}\n'.format(r['name']))
                    _w('         Nome no GDB   : {0}\n'.format(r['safe_name']))
                    _w('         Tipo          : {0}\n'.format(r['type']))
                    _w('         CRS           : {0}\n'.format(r['crs']))
                    if r.get('geom_fixed'):
                        _w('         Geom corrigidas : {0} (makeValid)\n'.format(r['geom_fixed']))
                    if r.get('geom_coerced'):
                        _w('         Tipo convertido : {0} (extraído de GeometryCollection)\n'.format(r['geom_coerced']))
                    if r.get('geom_skipped'):
                        _w('         Sem geometria   : {0} (atributos preservados)\n'.format(r['geom_skipped']))
                    _w('\n')

                if err_list:
                    _w('─' * 64 + '\n')
                    _w('ERROS / ERRORS  ({0} camada(s))\n'.format(len(err_list)))
                    _w('─' * 64 + '\n')
                    for r in err_list:
                        _w('  [ERRO]  {0}\n'.format(r['name']))
                        _w('           {0}\n'.format(r['error']))
                        _w('\n')

                _w('─' * 64 + '\n')
                _w('COMO USAR NO ARCGIS / HOW TO USE IN ARCGIS\n')
                _w('─' * 64 + '\n')
                _w('\n')
                _w('1. Abrir ArcGIS Pro e criar um novo projeto ou abrir um existente.\n')
                _w('2. No painel "Catalog": clique em "Add Folder Connection"\n')
                _w('   e navegue até a pasta de saída desta exportação.\n')
                _w('3. Expanda a conexão e localize o arquivo "{0}".\n'.format(gdb_name))
                _w('4. Arraste as Feature Classes desejadas para a visualização do mapa.\n')
                _w('\n')
                _w('ATENÇÃO / NOTES:\n')
                _w('  - Nomes sanitizados: acentos e espaços removidos.\n')
                _w('  - Grupos QGIS → Feature Datasets na GDB.\n')
                _w('  - SLD (se gerado) na mesma pasta para referência de simbologia.\n')
                _w('  - Rasters em "rasters/" como GeoTIFF.\n')
                _w('  - Camadas WMS/XYZ/Tile não podem ser exportadas diretamente;\n')
                _w('    use "Salvar como GeoTIFF" no QGIS antes.\n')
                _w('\n')
                _w('─' * 64 + '\n')
                _w('Gerado por RTH PROJECT QGIS Plugin\n')
                _w('https://rithon.com.br\n')

            dlg.log(self.tr(u'Relatório salvo: relatorio_exportacao.txt'))

        except Exception as exc:
            dlg.log_warn(self.tr(u'Falha ao gerar relatório: {0}').format(str(exc)))
