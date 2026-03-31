# -*- coding: utf-8 -*-
"""
rth_band_resolver — Normalização e resolução de nomes de bandas STAC
rth_band_resolver — STAC band name normalization and resolution

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para expressões regulares / Standard library for regular expressions
import re

# Mapeamento de número de banda → common_names STAC para Sentinel-2, Landsat e outros sensores
# Band number → STAC common_names mapping for Sentinel-2, Landsat and other sensors
# Cobre bandas do Sentinel-2 (B01–B12) e Landsat OLI / Covers Sentinel-2 (B01–B12) and Landsat OLI bands
# Necessário para resolver assets do Element84 (chaves = common_names) a partir de nomes de banda da API
# Needed to resolve Element84 assets (keys = common_names) from API band names
_BAND_NUM_TO_COMMON = {
    '1':  ('coastal',),
    '2':  ('blue',),
    '3':  ('green',),
    '4':  ('red',),
    '5':  ('rededge', 'rededge1', 'nir', 'nir08'),  # Sentinel-2 B05=rededge; Landsat B5=nir
    '6':  ('rededge2', 'swir16'),                    # Sentinel-2 B06=rededge2; Landsat B6=swir16
    '7':  ('rededge3', 'swir22'),                    # Sentinel-2 B07=rededge3; Landsat B7=swir22
    '8':  ('nir',),                                  # Sentinel-2 B08=nir 10m
    '9':  ('nir09', 'nir09'),                        # Sentinel-2 B09=nir09
    '10': ('cirrus',),                               # Sentinel-2 B10=cirrus
    '11': ('swir16',),                               # Sentinel-2 B11=swir16 20m
    '12': ('swir22',),                               # Sentinel-2 B12=swir22 20m
}


def normalize_band(name):
    """Normaliza nome de banda: maiúsculas e remove zeros à esquerda do sufixo numérico / Normalize band name: uppercase and strip leading zeros from numeric suffix.

    Exemplos / Examples: B04 → B4, BAND05 → BAND5, SR_B04 → SR_B4

    :param name: nome original da banda / original band name
    :returns: nome normalizado / normalized name
    :rtype: str
    """
    # Regex: prefixo alfabético (com _ permitido), zeros opcionais, número, sufixo opcional
    # Regex: alphabetic prefix (underscore allowed), optional zeros, number, optional suffix
    m = re.match(r'^([A-Za-z][A-Za-z0-9_]*?[A-Za-z])0*(\d+)([A-Za-z0-9_]*)$', name)
    if m:
        return (m.group(1) + str(int(m.group(2))) + m.group(3)).upper()
    # Sem número — converte apenas para maiúsculas / No number — just uppercase
    return name.upper()


def find_asset_key(assets, band_name):
    """Busca a chave do asset com correspondência progressivamente flexível / Search asset key with progressively flexible matching.

    Estratégias em ordem / Strategies in order:
    1. Exata / Exact
    2. Case-insensitive
    3. Normalizada (B04 == B4) / Normalized
    4. Chave começa com banda + separador / Key starts with band + separator
    5. Chave termina com nome da banda / Key ends with band name
    6. Normalizada termina com a banda normalizada / Normalized ends with normalized band
    7. Remove sufixo de resolução (_10m, _20m, _60m) e tenta novamente / Strip resolution suffix and retry
    8. Common_name aliases para Landsat e outros sensores / Common_name aliases for Landsat and other sensors

    :param assets: dicionário de assets da feature / feature assets dict
    :param band_name: nome da banda a encontrar / band name to find
    :returns: chave encontrada ou None / found key or None
    :rtype: str | None
    """
    # 1. Correspondência exata / Exact match
    if band_name in assets:
        return band_name

    bl = band_name.lower()

    # 2. Case-insensitive / Case-insensitive match
    for k in assets:
        if k.lower() == bl:
            return k

    # 3. Normalizada (B04 ↔ B4, BAND05 ↔ BAND5) / Normalized match
    bn = normalize_band(band_name)
    for k in assets:
        if normalize_band(k) == bn:
            return k

    # 4. Chave começa com a banda seguida de separador (B04_10m → B04) / Key starts with band + separator
    for k in assets:
        kl = k.lower()
        if kl.startswith(bl) and (len(kl) == len(bl) or kl[len(bl)] in ('_', '-', '.')):
            return k

    # 5. Chave termina com o nome da banda (SR_B04 → B04) / Key ends with band name
    for k in assets:
        kl = k.lower()
        if kl.endswith(bl) and (len(kl) == len(bl) or kl[-(len(bl) + 1)] in ('_', '-', '.')):
            return k

    # 6. Normalizada termina com a banda normalizada / Normalized ends with normalized band
    for k in assets:
        kn = normalize_band(k)
        if kn.endswith(bn) and (len(kn) == len(bn) or kn[-(len(bn) + 1)] in ('_', '-', '.')):
            return k

    # 7. Remove sufixo de resolução (_10m, _20m, _60m) e tenta de novo / Strip resolution suffix then retry
    bl_base = re.sub(r'_\d+m$', '', bl, flags=re.IGNORECASE)
    if bl_base != bl:
        for k in assets:
            kl_base = re.sub(r'_\d+m$', '', k.lower(), flags=re.IGNORECASE)
            if kl_base == bl_base:
                return k
            if normalize_band(kl_base) == normalize_band(bl_base):
                return k

    # 8. Common_name aliases para sensores conhecidos / Common_name aliases for known sensors
    m_digits = re.search(r'(\d+)$', band_name)
    if m_digits:
        num = m_digits.group(1).lstrip('0') or '0'
        for alias in _BAND_NUM_TO_COMMON.get(num, ()):
            if alias in assets:
                return alias
            # Busca case-insensitive do alias / Case-insensitive alias search
            for k in assets:
                if k.lower() == alias:
                    return k

    return None
