# -*- coding: utf-8 -*-
"""
rth_catalog — Catálogo estático de bandas e funções de composição
rth_catalog — Static band catalog and composition functions

Usado como fallback quando o detalhe da coleção não está disponível via API.
Used as fallback when collection detail is not available via API.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# ── Catálogo estático de satélites → coleções (fallback) ────────────────────
# Apenas os satélites e coleções desejados / Only desired satellites and collections
SATELLITE_COLLECTIONS = {

    'Sentinel-2': [
        # Brazil Data Cube — INPE / Brazil Data Cube — INPE
        ('S2_L2A-1',           'Sentinel-2 — Imagens  [INPE/BDC] (Brazil only)'),
        ('S2-16D-2',           'Sentinel-2 — DataCube 16 dias  [INPE/BDC] (Brazil only)'),
        # Microsoft Planetary Computer — cobertura global / global coverage
        ('sentinel-2-l2a',     'Sentinel-2 — Imagens Globais  [Planetary Computer]'),
        # AWS Element84 — cobertura global / global coverage
        ('sentinel-2-l2a-aws', 'Sentinel-2 — Imagens Globais  [AWS Element84]'),
    ],

    'Landsat': [
        # Brazil Data Cube — INPE / Brazil Data Cube — INPE
        ('landsat-2',      'Landsat 5 · 7 · 8 · 9 — Imagens  [INPE/BDC] (Brazil only)'),
        ('LANDSAT-16D-1',  'Landsat 5 · 7 · 8 · 9 — DataCube 16 dias  [INPE/BDC] (Brazil only)'),
        # Microsoft Planetary Computer — cobertura global L4-9 / global coverage L4-9
        ('landsat-c2-l2',  'Landsat 4 · 5 · 7 · 8 · 9 — Imagens Globais  [Planetary Computer]'),
    ],

    'CBERS-4': [
        # WFI — Wide Field Imager: BAND13=Blue, BAND14=Green, BAND15=Red, BAND16=NIR
        ('CB4-WFI-L4-SR-1',     'WFI — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('CB4-WFI-L4-DN-1',     'WFI — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4-WFI-L2-DN-1',     'WFI — Level-2 DN  [INPE/BDC] (Brazil only)'),
        ('CBERS4-WFI-16D-2',    'WFI — Data Cube — 16 dias  [INPE/BDC] (Brazil only)'),
        # MUX — Multispectral Camera: BAND5=Blue, BAND6=Green, BAND7=Red, BAND8=NIR
        ('CB4-MUX-L4-SR-1',    'MUX — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('CB4-MUX-L4-DN-1',    'MUX — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4-MUX-L2-DN-1',    'MUX — Level-2 DN  [INPE/BDC] (Brazil only)'),
        # MUX Data Cube LCF 2 meses: bandas multiespectrais + EVI + NDVI / MUX Data Cube LCF 2 months: MS bands + EVI + NDVI
        ('CBERS4-MUX-2M-1',   'MUX — Data Cube — LCF 2 Meses / 2-Month LCF  [INPE/BDC] (Brazil only)'),
        # PAN5M — Pancromático 5m: BAND1=PAN / Panchromatic 5m: BAND1=PAN
        ('CB4-PAN5M-L4-DN-1',  'PAN5M — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4-PAN5M-L2-DN-1',  'PAN5M — Level-2 DN  [INPE/BDC] (Brazil only)'),
        # PAN10M — Multiespectral 10m sem azul: BAND2=Green, BAND3=Red, BAND4=NIR
        ('CB4-PAN10M-L4-DN-1', 'PAN10M — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4-PAN10M-L2-DN-1', 'PAN10M — Level-2 DN  [INPE/BDC] (Brazil only)'),
    ],

    'CBERS-4A': [
        # WFI — Wide Field Imager: BAND13=Blue, BAND14=Green, BAND15=Red, BAND16=NIR
        ('CB4A-WFI-L4-SR-1',  'WFI — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('CB4A-WFI-L4-DN-1',  'WFI — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4A-WFI-L2-DN-1',  'WFI — Level-2 DN  [INPE/BDC] (Brazil only)'),
        ('CB4A-WFI-16D-2',    'WFI — Data Cube — 16 dias  [INPE/BDC] (Brazil only)'),
        # MUX — Multispectral Camera: BAND5=Blue, BAND6=Green, BAND7=Red, BAND8=NIR
        ('CB4A-MUX-L4-SR-1',  'MUX — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('CB4A-MUX-L4-DN-1',  'MUX — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4A-MUX-L2-DN-1',  'MUX — Level-2 DN  [INPE/BDC] (Brazil only)'),
        # WPM — Wide Panchromatic and Multispectral: BAND0=PAN, BAND1=Blue, BAND2=Green, BAND3=Red, BAND4=NIR
        ('CB4A-WPM-L4-SR-1',  'WPM — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('CB4A-WPM-L4-DN-1',  'WPM — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('CB4A-WPM-L2-DN-1',  'WPM — Level-2 DN  [INPE/BDC] (Brazil only)'),
    ],

    'Amazonia-1': [
        # Satélite brasileiro operado pelo INPE — cobertura restrita ao Brasil / Brazilian satellite operated by INPE — coverage restricted to Brazil
        ('AMZ1-WFI-L4-SR-1',  'WFI — Level-4 SR — COG  [INPE/BDC] (Brazil only)'),
        ('AMZ1-WFI-L4-DN-1',  'WFI — Level-4 DN  [INPE/BDC] (Brazil only)'),
        ('AMZ1-WFI-L2-DN-1',  'WFI — Level-2 DN  [INPE/BDC] (Brazil only)'),
        ('AMZ1-WFI-3M-1',     'WFI — Mosaico 3 Meses / 3-Month Mosaic  [INPE/BDC] (Brazil only)'),
    ],

    # Sentinel-1 RTC: Planetary Computer (global, VV/VH, 10m COG) e INPE/BDC (leste do Brasil, Gamma0_VV/VH, COG direto).
    # Sentinel-1 RTC: Planetary Computer (global, VV/VH, 10m COG) and INPE/BDC (eastern Brazil, Gamma0_VV/VH, direct COG).
    # Nota: cobertura PC tem lacunas em 2022-2024 nos estados do sul (falha S1B); 2021 e 2025 têm cobertura completa.
    # Note: PC coverage has gaps in 2022-2024 for southern states (S1B failure); 2021 and 2025 have full coverage.
    'Sentinel-1': [
        ('sentinel-1-rtc', 'RTC — Radiometricamente Corrigido / Radiometrically Terrain Corrected (VV·VH, 10m) — COG  [Planetary Computer]'),
    ],

}

# ── Satélites sem cobertura de nuvens ────────────────────────────────────────
# SAR (S1) não tem eo:cloud_cover — oculta o slider de nuvens para esses satélites
# SAR (S1) has no eo:cloud_cover — hide cloud slider for these satellites
NO_CLOUD_SATELLITES = frozenset({'Sentinel-1'})

# ── Coleções com sensor de composição exclusiva ───────────────────────────────
# Sensores PAN-only: exibem apenas a composição PAN no combo / PAN-only sensors: show only PAN in combo
_PAN_ONLY_COLLECTIONS = {
    'CB4-PAN5M-L4-DN-1',
    'CB4-PAN5M-L2-DN-1',
}

# Sensores sem banda azul (PAN10M): exibem apenas RED-NIR-GREEN / Sensors without blue (PAN10M): show only RED-NIR-GREEN
_RED_NIR_GREEN_ONLY_COLLECTIONS = {
    'CB4-PAN10M-L4-DN-1',
    'CB4-PAN10M-L2-DN-1',
}

# SAR: composição VV-VH-VV em falsa cor / SAR: VV-VH-VV false color composition
_SAR_ONLY_COLLECTIONS: set = {'sentinel-1-rtc'}

# Coleções de banda única com label customizado: {collection_id: (label, composition_key)}
# Single-band collections with custom label: {collection_id: (label, composition_key)}
_SINGLE_BAND_LABELS: dict = {}

# ── Bandas RGB por coleção (fallback): (vermelho, verde, azul) ───────────────
COLLECTION_RGB = {
    # Sentinel-2: B04=Red, B03=Green, B02=Blue
    'S2-16D-2':        ('B04', 'B03', 'B02'),
    'S2_L2A-1':        ('B04', 'B03', 'B02'),
    'sentinel-2-l2a':  ('B04', 'B03', 'B02'),
    # Landsat — asset keys são common_names / asset keys are common_names
    'LANDSAT-16D-1':   ('red', 'green', 'blue'),
    'landsat-2':       ('red', 'green', 'blue'),
    'landsat-c2-l2':   ('red', 'green', 'blue'),
    # Amazonia-1 WFI: BAND3=Red, BAND2=Green, BAND1=Blue
    'AMZ1-WFI-L4-SR-1':  ('BAND3', 'BAND2', 'BAND1'),
    'AMZ1-WFI-L4-DN-1':  ('BAND3', 'BAND2', 'BAND1'),
    'AMZ1-WFI-L2-DN-1':  ('BAND3', 'BAND2', 'BAND1'),
    'AMZ1-WFI-3M-1':     ('BAND3', 'BAND2', 'BAND1'),
    # CBERS-4 WFI: BAND15=Red, BAND14=Green, BAND13=Blue
    'CB4-WFI-L4-SR-1':   ('BAND15', 'BAND14', 'BAND13'),
    'CB4-WFI-L4-DN-1':   ('BAND15', 'BAND14', 'BAND13'),
    'CB4-WFI-L2-DN-1':   ('BAND15', 'BAND14', 'BAND13'),
    'CBERS4-WFI-16D-2':  ('BAND15', 'BAND14', 'BAND13'),
    # CBERS-4 MUX: BAND7=Red, BAND6=Green, BAND5=Blue
    'CB4-MUX-L4-SR-1':   ('BAND7', 'BAND6', 'BAND5'),
    'CB4-MUX-L4-DN-1':   ('BAND7', 'BAND6', 'BAND5'),
    'CB4-MUX-L2-DN-1':   ('BAND7', 'BAND6', 'BAND5'),
    'CBERS4-MUX-2M-1':  ('BAND7', 'BAND6', 'BAND5'),
    # CBERS-4A WFI: BAND15=Red, BAND14=Green, BAND13=Blue
    'CB4A-WFI-L4-SR-1':  ('BAND15', 'BAND14', 'BAND13'),
    'CB4A-WFI-L4-DN-1':  ('BAND15', 'BAND14', 'BAND13'),
    'CB4A-WFI-L2-DN-1':  ('BAND15', 'BAND14', 'BAND13'),
    'CB4A-WFI-16D-2':    ('BAND15', 'BAND14', 'BAND13'),
    # CBERS-4A MUX: BAND7=Red, BAND6=Green, BAND5=Blue
    'CB4A-MUX-L4-SR-1':  ('BAND7', 'BAND6', 'BAND5'),
    'CB4A-MUX-L4-DN-1':  ('BAND7', 'BAND6', 'BAND5'),
    'CB4A-MUX-L2-DN-1':  ('BAND7', 'BAND6', 'BAND5'),
    # CBERS-4A WPM: BAND3=Red, BAND2=Green, BAND1=Blue (BAND0=PAN, BAND4=NIR)
    'CB4A-WPM-L4-SR-1':  ('BAND3', 'BAND2', 'BAND1'),
    'CB4A-WPM-L4-DN-1':  ('BAND3', 'BAND2', 'BAND1'),
    'CB4A-WPM-L2-DN-1':  ('BAND3', 'BAND2', 'BAND1'),
    # PAN5M e PAN10M não têm RGB / PAN5M and PAN10M have no RGB
    # Sentinel-1 SAR: falsa cor VV-VH-VV / SAR false color VV-VH-VV
    'sentinel-1-rtc': ('vv', 'vh', 'vv'),
}

# ── Bandas RED-NIR-BLUE por coleção (fallback): (Red, NIR, Blue) ─────────────
COLLECTION_RED_NIR_BLUE = {
    # Sentinel-2: B04=Red, B08=NIR 10m, B02=Blue
    'S2-16D-2':        ('B04', 'B08', 'B02'),
    'S2_L2A-1':        ('B04', 'B08', 'B02'),
    'sentinel-2-l2a':  ('B04', 'B08', 'B02'),
    # Landsat — common_names
    'LANDSAT-16D-1':   ('red', 'nir08', 'blue'),
    'landsat-2':       ('red', 'nir08', 'blue'),
    'landsat-c2-l2':   ('red', 'nir08', 'blue'),
    # Amazonia-1 WFI: BAND3=Red, BAND4=NIR, BAND1=Blue
    'AMZ1-WFI-L4-SR-1':  ('BAND3', 'BAND4', 'BAND1'),
    'AMZ1-WFI-L4-DN-1':  ('BAND3', 'BAND4', 'BAND1'),
    'AMZ1-WFI-L2-DN-1':  ('BAND3', 'BAND4', 'BAND1'),
    'AMZ1-WFI-3M-1':     ('BAND3', 'BAND4', 'BAND1'),
    # CBERS-4 WFI: BAND15=Red, BAND16=NIR, BAND13=Blue
    'CB4-WFI-L4-SR-1':   ('BAND15', 'BAND16', 'BAND13'),
    'CB4-WFI-L4-DN-1':   ('BAND15', 'BAND16', 'BAND13'),
    'CB4-WFI-L2-DN-1':   ('BAND15', 'BAND16', 'BAND13'),
    'CBERS4-WFI-16D-2':  ('BAND15', 'BAND16', 'BAND13'),
    # CBERS-4 MUX: BAND7=Red, BAND8=NIR, BAND5=Blue
    'CB4-MUX-L4-SR-1':   ('BAND7', 'BAND8', 'BAND5'),
    'CB4-MUX-L4-DN-1':   ('BAND7', 'BAND8', 'BAND5'),
    'CB4-MUX-L2-DN-1':   ('BAND7', 'BAND8', 'BAND5'),
    'CBERS4-MUX-2M-1':  ('BAND7', 'BAND8', 'BAND5'),
    # CBERS-4A WFI: BAND15=Red, BAND16=NIR, BAND13=Blue
    'CB4A-WFI-L4-SR-1':  ('BAND15', 'BAND16', 'BAND13'),
    'CB4A-WFI-L4-DN-1':  ('BAND15', 'BAND16', 'BAND13'),
    'CB4A-WFI-L2-DN-1':  ('BAND15', 'BAND16', 'BAND13'),
    'CB4A-WFI-16D-2':    ('BAND15', 'BAND16', 'BAND13'),
    # CBERS-4A MUX: BAND7=Red, BAND8=NIR, BAND5=Blue
    'CB4A-MUX-L4-SR-1':  ('BAND7', 'BAND8', 'BAND5'),
    'CB4A-MUX-L4-DN-1':  ('BAND7', 'BAND8', 'BAND5'),
    'CB4A-MUX-L2-DN-1':  ('BAND7', 'BAND8', 'BAND5'),
    # CBERS-4A WPM: BAND3=Red, BAND4=NIR, BAND1=Blue
    'CB4A-WPM-L4-SR-1':  ('BAND3', 'BAND4', 'BAND1'),
    'CB4A-WPM-L4-DN-1':  ('BAND3', 'BAND4', 'BAND1'),
    'CB4A-WPM-L2-DN-1':  ('BAND3', 'BAND4', 'BAND1'),
}

# ── Bandas NIR-SWIR-RED por coleção (fallback): (NIR, SWIR1, Red) ────────────
# Apenas sensores com SWIR / Only sensors with SWIR
COLLECTION_NIR_SWIR_RED = {
    # Sentinel-2: B08=NIR 10m, B11=SWIR1 20m, B04=Red 10m
    'S2-16D-2':        ('B08', 'B11', 'B04'),
    'S2_L2A-1':        ('B08', 'B11', 'B04'),
    'sentinel-2-l2a':  ('B08', 'B11', 'B04'),
    # Landsat — common_names: nir08=NIR, swir16=SWIR1, red=Red
    'LANDSAT-16D-1':   ('nir08', 'swir16', 'red'),
    'landsat-2':       ('nir08', 'swir16', 'red'),
    'landsat-c2-l2':   ('nir08', 'swir16', 'red'),
    # Demais sensores não possuem SWIR / Other sensors do not have SWIR
}

# ── Bandas RED-NIR-GREEN por coleção: (Red, NIR, Green) ──────────────────────
# Para sensores sem banda azul / For sensors without blue band
COLLECTION_RED_NIR_GREEN = {
    # CBERS-4 PAN10M: BAND3=Red, BAND4=NIR, BAND2=Green (sem banda azul / no blue band)
    'CB4-PAN10M-L4-DN-1': ('BAND3', 'BAND4', 'BAND2'),
    'CB4-PAN10M-L2-DN-1': ('BAND3', 'BAND4', 'BAND2'),
}

# ── Banda PAN por coleção: nome do asset pancromático ────────────────────────
# Retorna string com o nome do asset / Returns string with asset name
COLLECTION_PAN = {
    # CBERS-4 PAN5M: BAND1=PAN (~5m resolução/resolution)
    'CB4-PAN5M-L4-DN-1':  'BAND1',
    'CB4-PAN5M-L2-DN-1':  'BAND1',
    # CBERS-4A WPM: BAND0=PAN (~2m resolução/resolution)
    'CB4A-WPM-L4-SR-1':   'BAND0',
    'CB4A-WPM-L4-DN-1':   'BAND0',
    'CB4A-WPM-L2-DN-1':   'BAND0',
}

# ── Índice EVI por coleção: nome do asset pré-computado ──────────────────────
# Asset de índice EVI disponível diretamente no item STAC / EVI index asset available directly in STAC item
COLLECTION_EVI = {
    # CBERS-4 MUX Data Cube LCF 2 meses / 2-month LCF
    'CBERS4-MUX-2M-1': 'EVI',
}

# ── Índice NDVI por coleção: nome do asset pré-computado ─────────────────────
# Asset de índice NDVI disponível diretamente no item STAC / NDVI index asset available directly in STAC item
COLLECTION_NDVI = {
    # CBERS-4 MUX Data Cube LCF 2 meses / 2-month LCF
    'CBERS4-MUX-2M-1': 'NDVI',
}


def get_band_tuple(collection_id, composition_key):
    """Retorna a tupla de bandas ou nome de asset do catálogo estático / Return band tuple or asset name from static catalog.

    Composições de banda única (PAN, EVI, NDVI) retornam string com nome do asset.
    Single-band compositions (PAN, EVI, NDVI) return string with asset name.

    :param collection_id: ID da coleção / Collection ID
    :param composition_key: 'RGB', 'RED_NIR_BLUE', 'NIR_SWIR_RED', 'RED_NIR_GREEN', 'PAN', 'EVI' ou 'NDVI'
    :returns: tupla (ch1, ch2, ch3), string do asset ou None
    :rtype: tuple | str | None
    """
    # SAR: banda única VV ou VH — deriva do COLLECTION_RGB para reutilizar os nomes de asset
    # SAR: single band VV or VH — derived from COLLECTION_RGB to reuse asset names
    if composition_key in ('SAR_VV', 'SAR_VH'):
        rgb = COLLECTION_RGB.get(collection_id)
        if rgb:
            band = rgb[0] if composition_key == 'SAR_VV' else rgb[1]
            return (band, band, band)
        return None
    if composition_key == 'NIR_SWIR_RED':
        return COLLECTION_NIR_SWIR_RED.get(collection_id)
    if composition_key == 'RED_NIR_BLUE':
        return COLLECTION_RED_NIR_BLUE.get(collection_id)
    if composition_key == 'RED_NIR_GREEN':
        return COLLECTION_RED_NIR_GREEN.get(collection_id)
    if composition_key == 'PAN':
        return COLLECTION_PAN.get(collection_id)
    if composition_key == 'EVI':
        return COLLECTION_EVI.get(collection_id)
    if composition_key == 'NDVI':
        return COLLECTION_NDVI.get(collection_id)
    # Padrão: RGB / Default: RGB
    return COLLECTION_RGB.get(collection_id)


def get_rgb_from_eo_bands(eo_bands, composition_key='RGB'):
    """Extrai nomes de banda de uma lista eo:bands usando o campo common_name / Extract band names from an eo:bands list using the common_name field.

    Fonte primária quando os metadados da coleção estão disponíveis via API.
    Primary source when collection metadata is available via API.

    :param eo_bands: lista de objetos de banda de summaries.eo:bands / list of band objects from summaries.eo:bands
    :param composition_key: chave de composição / composition key
    :returns: tupla (ch1, ch2, ch3) ou string do asset ou None
    :rtype: tuple | str | None
    """
    # Mapeia common_name → nome da banda / Map common_name → band name
    by_common = {}
    for b in eo_bands:
        cn   = (b.get('common_name') or '').lower().strip()
        name = b.get('name', '').strip()
        if cn and name:
            by_common[cn] = name

    # Resolve NIR a partir de vários common_names / Resolve NIR from several possible common_names
    nir_val = (by_common.get('nir') or by_common.get('nir08') or
               by_common.get('nir09') or by_common.get('near-infrared'))

    if composition_key == 'NIR_SWIR_RED':
        swir = by_common.get('swir16') or by_common.get('swir22') or by_common.get('swir')
        red  = by_common.get('red')
        if nir_val and swir and red:
            return (nir_val, swir, red)
        return None

    if composition_key == 'RED_NIR_BLUE':
        red  = by_common.get('red')
        blue = by_common.get('blue')
        if red and nir_val and blue:
            return (red, nir_val, blue)
        return None

    if composition_key == 'RED_NIR_GREEN':
        # Falsa cor para sensores sem banda azul / False color for sensors without blue band
        red   = by_common.get('red')
        green = by_common.get('green')
        if red and nir_val and green:
            return (red, nir_val, green)
        return None

    if composition_key == 'PAN':
        return by_common.get('pan')

    if composition_key == 'EVI':
        return by_common.get('evi')

    if composition_key == 'NDVI':
        return by_common.get('ndvi')

    # Padrão: RGB / Default: RGB
    red   = by_common.get('red')
    green = by_common.get('green')
    blue  = by_common.get('blue')
    if red and green and blue:
        return (red, green, blue)
    return None


# ── Catálogo de bandas com nomes amigáveis por coleção ───────────────────────
# Usado pelo dialog de composição personalizada / Used by custom composition dialog

_S2_BANDS = [
    ('B01', 'Aerossol Costeiro / Coastal Aerosol (B01 · 443nm)'),
    ('B02', 'Azul / Blue (B02 · 490nm)'),
    ('B03', 'Verde / Green (B03 · 560nm)'),
    ('B04', 'Vermelho / Red (B04 · 665nm)'),
    ('B05', 'Red Edge-1 (B05 · 705nm)'),
    ('B06', 'Red Edge-2 (B06 · 740nm)'),
    ('B07', 'Red Edge-3 (B07 · 783nm)'),
    ('B08', 'NIR — Infravermelho Próximo / Near Infrared (B08 · 842nm)'),
    ('B8A', 'NIR Estreito / Narrow NIR (B8A · 865nm)'),
    ('B09', 'Vapor d\'Água / Water Vapour (B09 · 945nm)'),
    ('B11', 'SWIR-1 — Infravermelho Médio / Mid Infrared (B11 · 1610nm)'),
    ('B12', 'SWIR-2 — Infravermelho Médio / Mid Infrared (B12 · 2190nm)'),
]

_LANDSAT_BANDS = [
    ('blue',   'Azul / Blue'),
    ('green',  'Verde / Green'),
    ('red',    'Vermelho / Red'),
    ('nir08',  'NIR — Infravermelho Próximo / Near Infrared (NIR08)'),
    ('swir16', 'SWIR-1 — Infravermelho Médio / Mid Infrared (SWIR16 · 1.6µm)'),
    ('swir22', 'SWIR-2 — Infravermelho Médio / Mid Infrared (SWIR22 · 2.2µm)'),
    ('lwir11', 'Termal / Thermal (LWIR11)'),
]

_CB4_WFI_BANDS = [
    ('BAND13', 'Azul / Blue (BAND13 · 450nm)'),
    ('BAND14', 'Verde / Green (BAND14 · 555nm)'),
    ('BAND15', 'Vermelho / Red (BAND15 · 660nm)'),
    ('BAND16', 'NIR — Infravermelho Próximo / Near Infrared (BAND16 · 830nm)'),
]

_CB4_MUX_BANDS = [
    ('BAND5', 'Azul / Blue (BAND5 · 450nm)'),
    ('BAND6', 'Verde / Green (BAND6 · 555nm)'),
    ('BAND7', 'Vermelho / Red (BAND7 · 660nm)'),
    ('BAND8', 'NIR — Infravermelho Próximo / Near Infrared (BAND8 · 830nm)'),
]

_CB4A_WPM_BANDS = [
    ('BAND0', 'PAN — Pancromático / Panchromatic (BAND0 · ~580nm)'),
    ('BAND1', 'Azul / Blue (BAND1 · 450nm)'),
    ('BAND2', 'Verde / Green (BAND2 · 555nm)'),
    ('BAND3', 'Vermelho / Red (BAND3 · 660nm)'),
    ('BAND4', 'NIR — Infravermelho Próximo / Near Infrared (BAND4 · 830nm)'),
]

_AMZ1_WFI_BANDS = [
    ('BAND1', 'Azul / Blue (BAND1 · 450nm)'),
    ('BAND2', 'Verde / Green (BAND2 · 520nm)'),
    ('BAND3', 'Vermelho / Red (BAND3 · 670nm)'),
    ('BAND4', 'NIR — Infravermelho Próximo / Near Infrared (BAND4 · 790nm)'),
]

# Catálogo de bandas por coleção: {collection_id: [(band_key, label_PT/EN), ...]}
# Band catalog per collection: {collection_id: [(band_key, label_PT/EN), ...]}
BAND_CATALOG = {
    # Sentinel-2
    'S2_L2A-1':           _S2_BANDS,
    'S2-16D-2':           _S2_BANDS,
    'sentinel-2-l2a':     _S2_BANDS,
    'sentinel-2-l2a-aws': _S2_BANDS,
    # Landsat
    'landsat-2':          _LANDSAT_BANDS,
    'LANDSAT-16D-1':      _LANDSAT_BANDS,
    'landsat-c2-l2':      _LANDSAT_BANDS,
    # CBERS-4 WFI
    'CB4-WFI-L4-SR-1':    _CB4_WFI_BANDS,
    'CB4-WFI-L4-DN-1':    _CB4_WFI_BANDS,
    'CB4-WFI-L2-DN-1':    _CB4_WFI_BANDS,
    'CBERS4-WFI-16D-2':   _CB4_WFI_BANDS,
    # CBERS-4 MUX
    'CB4-MUX-L4-SR-1':    _CB4_MUX_BANDS,
    'CB4-MUX-L4-DN-1':    _CB4_MUX_BANDS,
    'CB4-MUX-L2-DN-1':    _CB4_MUX_BANDS,
    'CBERS4-MUX-2M-1':    _CB4_MUX_BANDS,
    # CBERS-4 PAN5M — banda única / single band
    'CB4-PAN5M-L4-DN-1':  [('BAND1', 'PAN — Pancromático / Panchromatic (BAND1 · 450–750nm)')],
    'CB4-PAN5M-L2-DN-1':  [('BAND1', 'PAN — Pancromático / Panchromatic (BAND1 · 450–750nm)')],
    # CBERS-4 PAN10M
    'CB4-PAN10M-L4-DN-1': [
        ('BAND2', 'Verde / Green (BAND2 · 555nm)'),
        ('BAND3', 'Vermelho / Red (BAND3 · 660nm)'),
        ('BAND4', 'NIR — Infravermelho Próximo / Near Infrared (BAND4 · 830nm)'),
    ],
    'CB4-PAN10M-L2-DN-1': [
        ('BAND2', 'Verde / Green (BAND2 · 555nm)'),
        ('BAND3', 'Vermelho / Red (BAND3 · 660nm)'),
        ('BAND4', 'NIR — Infravermelho Próximo / Near Infrared (BAND4 · 830nm)'),
    ],
    # CBERS-4A WFI
    'CB4A-WFI-L4-SR-1':   _CB4_WFI_BANDS,
    'CB4A-WFI-L4-DN-1':   _CB4_WFI_BANDS,
    'CB4A-WFI-L2-DN-1':   _CB4_WFI_BANDS,
    'CB4A-WFI-16D-2':     _CB4_WFI_BANDS,
    # CBERS-4A MUX
    'CB4A-MUX-L4-SR-1':   _CB4_MUX_BANDS,
    'CB4A-MUX-L4-DN-1':   _CB4_MUX_BANDS,
    'CB4A-MUX-L2-DN-1':   _CB4_MUX_BANDS,
    # CBERS-4A WPM
    'CB4A-WPM-L4-SR-1':   _CB4A_WPM_BANDS,
    'CB4A-WPM-L4-DN-1':   _CB4A_WPM_BANDS,
    'CB4A-WPM-L2-DN-1':   _CB4A_WPM_BANDS,
    # Amazonia-1 WFI
    'AMZ1-WFI-L4-SR-1':   _AMZ1_WFI_BANDS,
    'AMZ1-WFI-L4-DN-1':   _AMZ1_WFI_BANDS,
    'AMZ1-WFI-L2-DN-1':   _AMZ1_WFI_BANDS,
    'AMZ1-WFI-3M-1':      _AMZ1_WFI_BANDS,
    # Sentinel-1 SAR — bandas / bands
    'sentinel-1-rtc': [
        ('vv', 'VV — Vertical/Vertical (backscatter, dB)'),
        ('vh', 'VH — Vertical/Horizontal (backscatter, dB)'),
    ],
}


def needs_eo_bands(collection_id):
    """Retorna True se a coleção pode usar eo:bands da API para resolver composições / Return True if collection may use API eo:bands for composition building.

    SAR, PAN, e coleções de banda única têm composição fixa — não precisam de eo:bands.
    Usado para evitar chamadas de rede desnecessárias na thread principal.
    SAR, PAN, and single-band collections have fixed compositions — they don't need eo:bands.
    Used to avoid unnecessary network calls on the main thread.
    """
    return collection_id not in (
        _SAR_ONLY_COLLECTIONS
        | _PAN_ONLY_COLLECTIONS
        | _RED_NIR_GREEN_ONLY_COLLECTIONS
        | set(_SINGLE_BAND_LABELS)
    )


def get_band_catalog(collection_id):
    """Retorna lista de (band_key, label) para a coleção / Return list of (band_key, label) for collection.

    :param collection_id: ID da coleção / Collection ID
    :returns: lista de tuplas (chave, rótulo amigável) / list of (key, friendly_label) tuples
    :rtype: list[tuple[str, str]]
    """
    return BAND_CATALOG.get(collection_id, [])


# ── Persistência de composições personalizadas via QgsSettings ────────────────

import re as _re
import json as _json


def _coll_key(collection_id):
    """Sanitiza o ID da coleção para uso como chave QgsSettings / Sanitize collection ID for QgsSettings key."""
    return _re.sub(r'[^a-zA-Z0-9]', '_', collection_id)


def get_custom_compositions(collection_id):
    """Carrega composições personalizadas salvas para a coleção / Load saved custom compositions for collection.

    :returns: lista de dicts {name, r, g, b, extra} / list of dicts {name, r, g, b, extra}
    :rtype: list[dict]
    """
    try:
        from qgis.core import QgsSettings
        raw = QgsSettings().value(
            'rth_project/custom_compositions/' + _coll_key(collection_id), '[]')
        return _json.loads(raw) if raw else []
    except Exception:
        return []


def save_custom_composition(collection_id, name, r, g, b, extra=None):
    """Salva ou atualiza uma composição personalizada em QgsSettings / Save or update a custom composition in QgsSettings.

    :param name: nome da composição (chave única) / composition name (unique key)
    :param r: chave da banda vermelha / red band key
    :param g: chave da banda verde / green band key
    :param b: chave da banda azul / blue band key
    :param extra: lista de chaves de bandas extras / list of extra band keys
    """
    try:
        from qgis.core import QgsSettings
        comps = [c for c in get_custom_compositions(collection_id) if c.get('name') != name]
        comps.append({'name': name, 'r': r, 'g': g, 'b': b, 'extra': extra or []})
        QgsSettings().setValue(
            'rth_project/custom_compositions/' + _coll_key(collection_id),
            _json.dumps(comps))
    except Exception:
        pass


def delete_custom_composition(collection_id, name):
    """Remove uma composição personalizada do QgsSettings / Remove a custom composition from QgsSettings.

    :param name: nome da composição a remover / composition name to remove
    """
    try:
        from qgis.core import QgsSettings
        comps = [c for c in get_custom_compositions(collection_id) if c.get('name') != name]
        QgsSettings().setValue(
            'rth_project/custom_compositions/' + _coll_key(collection_id),
            _json.dumps(comps))
    except Exception:
        pass


def get_compositions(collection_id, eo_bands=None):
    """Retorna as composições disponíveis para a coleção / Return available compositions for the collection.

    Coleções PAN-only e RED_NIR_GREEN-only retornam apenas sua composição exclusiva.
    PAN-only and RED_NIR_GREEN-only collections return only their exclusive composition.

    :param collection_id: ID da coleção / Collection ID
    :param eo_bands: lista eo:bands da API (opcional) / eo:bands list from API (optional)
    :returns: lista de (label, key) / list of (label, key)
    :rtype: list[tuple[str, str]]
    """
    # ── Sensores com composição exclusiva ─────────────────────────────────────
    # Exclusive composition sensors

    # SAR: Sentinel-1 RTC — VV e VH como banda única (cinza nativo) + composição dual-pol
    # SAR: Sentinel-1 RTC — VV and VH as single band (native gray) + dual-pol composite
    if collection_id in _SAR_ONLY_COLLECTIONS:
        return [
            ('VV  (Banda Única / Single Band)', 'SAR_VV'),
            ('VH  (Banda Única / Single Band)', 'SAR_VH'),
            ('VV – VH – VV  (Composição Dual-Pol / Dual-Pol Composite)', 'RGB'),
        ]

    # Banda única com label customizado (ex: Ficocianina) / Single band with custom label (e.g. Phycocyanin)
    if collection_id in _SINGLE_BAND_LABELS:
        return [_SINGLE_BAND_LABELS[collection_id]]

    # PAN5M: sensor pancromático puro — somente composição PAN / Pure panchromatic sensor — PAN only
    if collection_id in _PAN_ONLY_COLLECTIONS:
        return [('PAN  (Pancromática / Panchromatic)', 'PAN')]

    # PAN10M: sem banda azul — somente RED-NIR-GREEN / No blue band — RED-NIR-GREEN only
    if collection_id in _RED_NIR_GREEN_ONLY_COLLECTIONS:
        return [('RED – NIR – GREEN  (Falsa Cor / False Color)', 'RED_NIR_GREEN')]

    # ── Composições gerais para sensores multiespectrais ──────────────────────
    # General compositions for multispectral sensors

    # RGB sempre disponível (exceto sensores exclusivos acima) / RGB always available (except exclusive sensors above)
    options = [('R–G–B  (Cor verdadeira / True Color)', 'RGB')]

    if eo_bands:
        # Verifica common_names disponíveis via API / Check available common_names via API
        commons  = {(b.get('common_name') or '').lower() for b in eo_bands}
        has_nir  = bool(commons & {'nir', 'nir08', 'nir09', 'near-infrared'})
        has_swir = bool(commons & {'swir16', 'swir22', 'swir'})
        has_blue = 'blue' in commons
        has_pan  = 'pan' in commons
        has_evi  = 'evi' in commons
        has_ndvi = 'ndvi' in commons
        has_red_nir_blue = has_nir and has_blue
        has_nir_swir     = has_nir and has_swir
    else:
        # Fallback: catálogo estático / Fallback: static catalog
        has_nir_swir     = collection_id in COLLECTION_NIR_SWIR_RED
        has_red_nir_blue = collection_id in COLLECTION_RED_NIR_BLUE
        has_pan          = collection_id in COLLECTION_PAN
        has_evi          = collection_id in COLLECTION_EVI
        has_ndvi         = collection_id in COLLECTION_NDVI

    if has_red_nir_blue:
        options.append(('RED – NIR – BLUE  (Valoração / Valuation)', 'RED_NIR_BLUE'))

    if has_nir_swir:
        options.append(('NIR – SWIR – RED  (Mapeamento agrícola / Agriculture mapping)', 'NIR_SWIR_RED'))

    if has_evi:
        # Índice pré-computado EVI disponível no cubo / Pre-computed EVI index available in cube
        options.append(('EVI  (Índice de Vegetação / Vegetation Index)', 'EVI'))

    if has_ndvi:
        # Índice pré-computado NDVI disponível no cubo / Pre-computed NDVI index available in cube
        options.append(('NDVI  (Índice de Vegetação / Vegetation Index)', 'NDVI'))

    if has_pan:
        options.append(('PAN  (Pancromática / Panchromatic)', 'PAN'))

    return options
