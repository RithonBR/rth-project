# -*- coding: utf-8 -*-
"""
Constantes do RTH DEM Downloader / RTH DEM Downloader constants

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Chave da fonte INPE exibida na UI / INPE source key shown in UI
SOURCE_INPE = 'INPE Data (Brazil Only)'

# Chave da fonte Copernicus 30m exibida na UI / Copernicus 30m source key shown in UI
SOURCE_COPERNICUS = 'Copernicus DEM 30M'

# Chave da fonte Copernicus 90m exibida na UI / Copernicus 90m source key shown in UI
SOURCE_COPERNICUS_90 = 'Copernicus DEM 90M'

# URL base da API STAC do INPE para a coleção Topodata / Base URL of INPE STAC API for Topodata collection
STAC_COLLECTION_URL = 'https://data.inpe.br/bdc/stac/v1/collections/topodata-1/items'

# URL base do bucket S3 público do Copernicus DEM 30m (1 arco-segundo) / Base URL of Copernicus DEM 30m public S3 bucket (1 arc-second)
COPERNICUS_BASE_URL = 'https://copernicus-dem-30m.s3.amazonaws.com'

# URL base do bucket S3 público do Copernicus DEM 90m (3 arco-segundos) / Base URL of Copernicus DEM 90m public S3 bucket (3 arc-seconds)
COPERNICUS_BASE_URL_90M = 'https://copernicus-dem-90m.s3.amazonaws.com'

# Tipos de dado disponíveis na coleção INPE Topodata / Data types available in the INPE Topodata collection
# Chave: label exibido na UI / Key: label shown in UI
# Valor: código do asset no STAC / Value: asset code in STAC
DATA_TYPES = {
    'Altitude — ZN':                     'ZN',
    'Declividade — SN':                  'SN',
    'Orientação de Vertente — ON':       'ON',
    'Curvatura Vertical — VN':           'VN',
    'Curvatura Horizontal — HN':         'HN',
    'Relevo Sombreado — RS':             'RS',
    'Declividade Marques 1971 — SA':     'SA',
    'Declividade Lepsch 1991 — SB':      'SB',
    'Declividade EMBRAPA 1999 — SC':     'SC',
    'Orientação em Octantes — OC':       'OC',
    'Curvatura Vertical 3 classes — V3': 'V3',
    'Curvatura Vertical 5 classes — V5': 'V5',
    'Curvatura Horizontal 3 cl. — H3':  'H3',
    'Curvatura Horizontal 5 cl. — H5':  'H5',
    'Forma de Terreno — FT':             'FT',
    'Divisores e Talvegues — DD':        'DD',
}
