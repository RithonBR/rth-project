# -*- coding: utf-8 -*-
"""
test_geobase_download.py
────────────────────────────────────────────────────────────────────────────
Testa o caminho completo de download do plugin brazil_geobase:
  - Item 3: WFS → GeoPackage  (FUNAI Aldeias via OGR fallback)
  - Item 4: WCS → GeoTIFF     (EPE via provider WCS)

Roda do console Python do QGIS:
    exec(open(r'C:/Users/nohti/Desktop/rth_project/test/test_geobase_download.py').read())
────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
import tempfile
import traceback
import urllib.parse
import urllib.request

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET  # noqa: S405

SEP  = '─' * 72
SEP2 = '═' * 72

def p(msg=''):
    print(msg)

# ── Endpoints ─────────────────────────────────────────────────────────────────

FUNAI_BASE    = 'https://geoserver.funai.gov.br/geoserver/ows'
FUNAI_LAYER   = 'Funai:aldeias_pontos'

EPE_BASE      = 'https://geoservicos.inde.gov.br/geoserver/EPE/ows'
EPE_WCS_CAP   = f'{EPE_BASE}?service=wcs&request=GetCapabilities&version=1.1.1'


def _fetch(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'QGIS-RTH-Test/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            return r.getcode(), r.read().decode('utf-8', errors='replace'), None
    except Exception as e:
        return None, None, str(e)


# ── ITEM 3: WFS → GeoPackage (end-to-end) ────────────────────────────────────

def section_3_wfs_download():
    p(SEP2)
    p('ITEM 3 — WFS → GeoPackage (caminho completo do plugin)')
    p(SEP2)

    try:
        from qgis.core import (
            QgsVectorLayer, QgsVectorFileWriter,
            QgsCoordinateTransformContext, QgsProject,
        )
    except ImportError:
        p('QGIS não disponível — pulando')
        return

    # ── 3a: Carregar camada via OGR (mesmo path do plugin _download_selected) ──
    p('3a. Carregar QgsVectorLayer via OGR WFS (fallback do plugin)…')
    ogr_uri = (
        f'WFS:{FUNAI_BASE}'
        f'?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetCapabilities'
        f'|layername={FUNAI_LAYER}'
    )
    vlayer = QgsVectorLayer(ogr_uri, FUNAI_LAYER, 'ogr')
    p(f'  isValid:      {vlayer.isValid()}')
    if not vlayer.isValid():
        p('  ❌ Camada inválida — abortando item 3')
        return

    dp = vlayer.dataProvider()
    feat_count = dp.featureCount() if dp else -1
    field_count = dp.fields().count() if dp else -1
    crs = dp.crs().authid() if dp else '?'
    p(f'  feições:      {feat_count}')
    p(f'  campos:       {field_count}')
    p(f'  CRS:          {crs}')
    p(f'  extent:       {vlayer.extent().toString()[:80]}')
    p()

    # ── 3b: Salvar → GeoPackage (mesmo código do plugin) ──────────────────────
    out_path = os.path.join(tempfile.gettempdir(), 'rth_test_FUNAI_aldeias_pontos.gpkg')
    p(f'3b. Salvar GeoPackage em: {out_path}')

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName   = 'GPKG'
    opts.fileEncoding = 'UTF-8'

    try:
        result, err_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
            vlayer, out_path, QgsCoordinateTransformContext(), opts)
    except (AttributeError, TypeError):
        result, err_msg = QgsVectorFileWriter.writeAsVectorFormatV2(
            vlayer, out_path, QgsCoordinateTransformContext(), opts)

    p(f'  resultado:    {result}  (0 = NoError)')
    p(f'  erro msg:     {err_msg!r}')

    if result != QgsVectorFileWriter.NoError:
        p(f'  ❌ Falha ao salvar GeoPackage (código {result})')
        return

    size = os.path.getsize(out_path) if os.path.exists(out_path) else -1
    p(f'  tamanho:      {size:,} bytes')
    p()

    # ── 3c: Abrir o GPKG salvo e verificar integridade ────────────────────────
    p(f'3c. Abrir GPKG salvo e verificar integridade…')
    local_lyr = QgsVectorLayer(out_path, 'aldeias_test', 'ogr')
    p(f'  isValid:      {local_lyr.isValid()}')
    if not local_lyr.isValid():
        p('  ❌ GPKG salvo não abre corretamente')
        return

    local_dp = local_lyr.dataProvider()
    local_feat = local_dp.featureCount() if local_dp else -1
    local_fields = local_dp.fields().count() if local_dp else -1
    local_crs = local_dp.crs().authid() if local_dp else '?'
    p(f'  feições:      {local_feat}')
    p(f'  campos:       {local_fields}')
    p(f'  CRS:          {local_crs}')

    # Verificar consistência com a origem
    if local_feat == feat_count:
        p(f'  ✅ Feições consistentes ({feat_count} → {local_feat})')
    else:
        p(f'  ⚠  Feições divergentes: origem={feat_count} gpkg={local_feat}')

    if local_fields == field_count:
        p(f'  ✅ Campos consistentes ({field_count})')
    else:
        p(f'  ⚠  Campos divergentes: origem={field_count} gpkg={local_fields}')

    # Lê as primeiras 3 feições para confirmar que os dados estão lá
    p('  Primeiras 3 feições (amostra):')
    for i, feat in enumerate(local_lyr.getFeatures()):
        if i >= 3:
            break
        attrs = [str(v)[:30] for v in feat.attributes()[:4]]
        p(f'    [{i+1}] {attrs}')

    p()
    p(f'  ✅ GPKG íntegro — {local_feat} feições, {local_fields} campos, {local_crs}')
    p(f'  Arquivo: {out_path}')


# ── ITEM 4: WCS → GeoTIFF (EPE) ──────────────────────────────────────────────

def section_4_wcs_download():
    p()
    p(SEP2)
    p('ITEM 4 — WCS → GeoTIFF (EPE via provider WCS)')
    p(SEP2)

    # ── 4a: Fetch GetCapabilities e listar coverages ───────────────────────────
    p('4a. WCS GetCapabilities (urllib)…')
    p(f'  URL: {EPE_WCS_CAP}')
    code, text, err = _fetch(EPE_WCS_CAP)
    p(f'  HTTP {code}  err={err}')
    if not text or code != 200:
        p('  ❌ Servidor inacessível — abortando item 4')
        return

    # Parsear identifiers
    try:
        root = ET.fromstring(text)  # nosec B314
        identifiers = []
        for elem in root.iter():
            local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if local == 'Identifier' and elem.text and elem.text.strip():
                identifiers.append(elem.text.strip())
        p(f'  Coverages encontradas: {len(identifiers)}')
        for i, ident in enumerate(identifiers[:6]):
            p(f'    [{i+1}] {ident}')
    except Exception as exc:
        p(f'  Erro ao parsear XML: {exc}')
        return

    if not identifiers:
        p('  ❌ Nenhuma coverage encontrada — abortando')
        return

    # ── 4b: Criar QgsRasterLayer WCS para primeira coverage ───────────────────
    try:
        from qgis.core import QgsRasterLayer
    except ImportError:
        p('QGIS não disponível — pulando')
        return

    p()
    target = identifiers[0]
    p(f'4b. Criar QgsRasterLayer WCS para: {target}')

    def _make_wcs_uri(identifier, base_url, crs='EPSG:4674'):
        from urllib.parse import quote
        return (
            f'identifier={quote(identifier, safe=":")}'
            f'&url={base_url}'
            f'&version=1.1.1'
            f'&crs={crs}'
        )

    rlyr = None
    for crs in ('EPSG:4674', 'EPSG:4326'):
        for prov in ('wcs', 'WCS'):
            uri = _make_wcs_uri(target, EPE_BASE, crs)
            lyr = QgsRasterLayer(uri, target, prov)
            p(f'  [{prov} / {crs}] isValid={lyr.isValid()}')
            if lyr.isValid():
                rlyr = lyr
                break
        if rlyr:
            break

    if not rlyr or not rlyr.isValid():
        # GDAL WCS fallback — WCS 1.0.0 (same pattern as WMS/WFS fallbacks in plugin)
        p('  → providers nativos falharam, tentando GDAL WCS 1.0.0…')
        import tempfile as _tmp
        xml = (
            '<WCS_GDAL>'
            f'<ServiceURL>{EPE_BASE}?</ServiceURL>'
            '<Version>1.0.0</Version>'
            f'<CoverageName>{target}</CoverageName>'
            '</WCS_GDAL>'
        )
        tf = _tmp.NamedTemporaryFile(suffix='.xml', delete=False, mode='w')
        tf.write(xml); tf.close()
        rlyr = QgsRasterLayer(tf.name, target, 'gdal')
        try: os.unlink(tf.name)
        except: pass
        p(f'  [GDAL WCS 1.0.0] isValid={rlyr.isValid()}')

    if not rlyr or not rlyr.isValid():
        dp = rlyr.dataProvider() if rlyr else None
        err_msg = ''
        if dp:
            err = dp.error()
            if err:
                err_msg = err.message()
        p(f'  ❌ Todas as variantes falharam. Último erro: {err_msg!r}')
        return

    p(f'  ✅ Camada válida')
    p(f'  CRS:     {rlyr.crs().authid()}')
    p(f'  Extent:  {rlyr.extent().toString()[:80]}')
    p(f'  Bandas:  {rlyr.bandCount()}')
    p()

    # ── 4c: Exportar para GeoTIFF (mesmo código do plugin _download_raster) ───
    try:
        from qgis.core import QgsRasterFileWriter, QgsRasterPipe
        from qgis.PyQt.QtWidgets import QApplication
    except ImportError:
        p('  QgsRasterFileWriter não disponível — pulando 4c')
        return

    out_path = os.path.join(tempfile.gettempdir(), 'rth_test_EPE_wcs.tif')
    p(f'4c. Exportar GeoTIFF: {out_path}')

    extent = rlyr.extent()
    if not extent.isFinite() or extent.isEmpty():
        p('  ❌ Extent inválido — não é possível exportar')
        return

    # Cap 512px lado maior (mesmo critério do plugin)
    aspect = extent.width() / max(extent.height(), 1e-10)
    if aspect >= 1:
        cols, rows = 512, max(1, int(512 / aspect))
    else:
        rows, cols = 512, max(1, int(512 * aspect))
    p(f'  Tamanho: {cols} x {rows} px')

    pipe = QgsRasterPipe()
    if not pipe.set(rlyr.dataProvider().clone()):
        p('  ❌ Não foi possível criar o raster pipe')
        return

    writer = QgsRasterFileWriter(out_path)
    writer.setOutputFormat('GTiff')
    QApplication.processEvents()

    error = writer.writeRaster(pipe, cols, rows, extent, rlyr.crs())
    try:
        no_err = QgsRasterFileWriter.WriterError.NoError
    except AttributeError:
        no_err = QgsRasterFileWriter.NoError

    if error == no_err:
        size = os.path.getsize(out_path) if os.path.exists(out_path) else -1
        p(f'  ✅ GeoTIFF salvo — {size:,} bytes em {out_path}')

        # Abrir o GeoTIFF salvo e verificar
        from qgis.core import QgsRasterLayer as QRL
        check = QRL(out_path, 'EPE_wcs_test', 'gdal')
        p(f'  Reabrir com GDAL: isValid={check.isValid()}')
        if check.isValid():
            p(f'  CRS: {check.crs().authid()}  Bandas: {check.bandCount()}')
            p(f'  Extent: {check.extent().toString()[:80]}')
            p('  ✅ GeoTIFF íntegro')
        else:
            p('  ⚠  GeoTIFF salvo mas não abre corretamente')
    else:
        p(f'  ❌ writeRaster falhou (código: {error})')


# ── Main ──────────────────────────────────────────────────────────────────────

def run_all():
    p(SEP2)
    p('  RTH PROJECT — GeoBase Download End-to-End Test')
    p('  Items 3 (WFS→GPKG) e 4 (WCS→GeoTIFF)')
    p(SEP2)

    section_3_wfs_download()
    section_4_wcs_download()

    p()
    p(SEP2)
    p('  TESTE CONCLUÍDO')
    p(SEP2)


if __name__ == '__main__':
    run_all()
else:
    run_all()
