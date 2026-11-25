# -*- coding: utf-8 -*-
"""
Utilitário UTM regional - Detecta o datum e EPSG UTM mais apropriado para uma localização
Regional UTM utility - Detects the most appropriate datum and UTM EPSG for a location

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Importação do módulo matemático / Math module import
import math


def detect_regional_utm(lon, lat):
    """
    Detecta o EPSG UTM mais apropriado para a localização usando o datum regional oficial.
    Detects the most appropriate UTM EPSG for the location using the official regional datum.

    Regiões / Regions:
      - América do Sul   / South America  → SIRGAS 2000  (EPSG 31971–31985)
      - Europa           / Europe         → ETRS89       (EPSG 25828–25838)
      - América do Norte / North America  → NAD83        (EPSG 26901–26923)
      - Austrália        / Australia      → GDA2020      (EPSG 7849–7856)
      - Demais regiões   / Other regions  → WGS 84       (EPSG 32601–32760)

    Parâmetros / Parameters:
      lon (float): longitude em graus decimais WGS84 / longitude in WGS84 decimal degrees
      lat (float): latitude em graus decimais WGS84  / latitude in WGS84 decimal degrees

    Retorna / Returns:
      tuple: (epsg: int, datum_name: str, zone: int, hemisphere: str)
    """
    # Zona UTM de 1 a 60 calculada pela longitude / UTM zone 1 to 60 calculated from longitude
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    # Hemisfério baseado na latitude / Hemisphere based on latitude
    hemi = 'N' if lat >= 0 else 'S'
    # EPSG WGS84 UTM reutilizado como fallback / WGS84 UTM EPSG reused as fallback
    wgs_epsg = (32600 + zone) if hemi == 'N' else (32700 + zone)

    # ── América do Sul: SIRGAS 2000 ──────────────────────────────────────────
    # Cobertura: lon -85° a -30°, lat -60° a +15° / Coverage: lon -85° to -30°, lat -60° to +15°
    if -85.0 <= lon <= -30.0 and -60.0 <= lat <= 15.0:
        if hemi == 'N' and 17 <= zone <= 22:
            # SIRGAS 2000 / UTM norte, zonas 17N–22N: EPSG 31971–31976
            # SIRGAS 2000 / UTM north, zones 17N–22N: EPSG 31971–31976
            return 31954 + zone, 'SIRGAS 2000', zone, hemi
        if hemi == 'S' and 17 <= zone <= 25:
            # SIRGAS 2000 / UTM sul, zonas 17S–25S: EPSG 31977–31985
            # SIRGAS 2000 / UTM south, zones 17S–25S: EPSG 31977–31985
            return 31960 + zone, 'SIRGAS 2000', zone, hemi

    # ── Europa: ETRS89 ───────────────────────────────────────────────────────
    # Cobertura: lon -10° a +40°, lat +35° a +75° / Coverage: lon -10° to +40°, lat +35° to +75°
    elif -10.0 <= lon <= 40.0 and 35.0 <= lat <= 75.0:
        if 28 <= zone <= 38:
            # ETRS89 / UTM norte, zonas 28N–38N: EPSG 25828–25838
            # ETRS89 / UTM north, zones 28N–38N: EPSG 25828–25838
            return 25800 + zone, 'ETRS89', zone, hemi

    # ── América do Norte: NAD83 ──────────────────────────────────────────────
    # Cobertura: lon -170° a -52°, lat +15° a +85° / Coverage: lon -170° to -52°, lat +15° to +85°
    elif -170.0 <= lon <= -52.0 and 15.0 <= lat <= 85.0:
        if 1 <= zone <= 23:
            # NAD83 / UTM norte, zonas 1N–23N: EPSG 26901–26923
            # NAD83 / UTM north, zones 1N–23N: EPSG 26901–26923
            return 26900 + zone, 'NAD83', zone, hemi

    # ── Austrália: GDA2020 ───────────────────────────────────────────────────
    # Cobertura: lon +110° a +155°, lat -45° a -10° / Coverage: lon +110° to +155°, lat -45° to -10°
    elif 110.0 <= lon <= 155.0 and -45.0 <= lat <= -10.0:
        if 49 <= zone <= 56:
            # GDA2020 / MGA sul, zonas 49S–56S: EPSG 7849–7856
            # GDA2020 / MGA south, zones 49S–56S: EPSG 7849–7856
            return 7800 + zone, 'GDA2020', zone, hemi

    # ── Fallback global: WGS 84 ───────────────────────────────────────────────
    # Regiões sem datum continental unificado (África, Ásia, Oceania, regiões polares)
    # Regions without a unified continental datum (Africa, Asia, Oceania, polar regions)
    return wgs_epsg, 'WGS 84', zone, hemi
