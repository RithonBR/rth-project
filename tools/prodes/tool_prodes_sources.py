# -*- coding: utf-8 -*-
"""
Constantes de fonte de dados PRODES — TerraBrasilis / INPE.
Dados extraídos do JSON oficial: terrabrasilis/terrabrasilis_datasource
"""

PRODES_WMS_BASE = 'https://terrabrasilis.dpi.inpe.br/geoserver'
PRODES_WFS_BASE = 'https://terrabrasilis.dpi.inpe.br/geoserver'

# Biomas com workspace, camadas, anos e CRS conforme JSON oficial do TerraBrasilis.
# ATENÇÃO:
#   - Amazônia (biome) usa sufixo _biome nos nomes de camada
#   - Amazônia Não Floresta compartilha workspace com Amazônia mas tem CRS 4326 e só mosaico temporal
#   - Amazônia Legal usa workspace próprio: prodes-legal-amz
BIOMES = [
    {
        'name':             u'Amazônia',
        'workspace':        'prodes-amazon-nb',
        'yearly_layer':     'yearly_deforestation_biome',
        'accumulated_layer': 'accumulated_deforestation_2007_biome',
        'crs':              4674,
        'times': [
            '2008','2009','2010','2011','2012','2013','2014',
            '2015','2016','2017','2018','2019','2020','2021',
            '2022','2023','2024','2025',
        ],
    },
    {
        'name':             u'Amazônia Legal',
        'workspace':        'prodes-legal-amz',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2007',
        'crs':              4674,
        'times': [
            '2008','2009','2010','2011','2012','2013','2014',
            '2015','2016','2017','2018','2019','2020','2021',
            '2022','2023','2024','2025',
        ],
    },
    {
        'name':             u'Amazônia — Não Floresta',
        'workspace':        'prodes-amazon-nb',
        'yearly_layer':     'temporal_mosaic_amazon_nf',
        'accumulated_layer': None,
        'crs':              4326,
        'times': [
            '1980','2000','2002','2004','2006','2008','2010',
            '2013','2014','2016','2018','2019','2020','2021',
            '2022','2023',
        ],
    },
    {
        'name':             u'Cerrado',
        'workspace':        'prodes-cerrado-nb',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2000',
        'crs':              4674,
        'times': [
            '2002','2004','2006','2008','2010','2012','2013',
            '2014','2015','2016','2017','2018','2019','2020',
            '2021','2022','2023','2024','2025',
        ],
    },
    {
        'name':             u'Caatinga',
        'workspace':        'prodes-caatinga-nb',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2000',
        'crs':              4674,
        'times': [
            '2004','2006','2008','2010','2011','2013','2014',
            '2016','2017','2018','2019','2020','2021','2022',
            '2023','2024',
        ],
    },
    {
        'name':             u'Mata Atlântica',
        'workspace':        'prodes-mata-atlantica-nb',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2000',
        'crs':              4674,
        'times': [
            '2004','2006','2008','2010','2011','2013','2014',
            '2016','2017','2018','2019','2020','2021','2022',
            '2023','2024',
        ],
    },
    {
        'name':             u'Pampa',
        'workspace':        'prodes-pampa-nb',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2000',
        'crs':              4674,
        'times': [
            '2004','2006','2008','2010','2011','2013','2014',
            '2016','2017','2018','2019','2020','2021','2022',
            '2023','2024',
        ],
    },
    {
        'name':             u'Pantanal',
        'workspace':        'prodes-pantanal-nb',
        'yearly_layer':     'yearly_deforestation',
        'accumulated_layer': 'accumulated_deforestation_2000',
        'crs':              4674,
        'times': [
            '2004','2006','2008','2010','2011','2013','2014',
            '2016','2017','2018','2019','2020','2021','2022',
            '2023','2024','2025',
        ],
    },
]
