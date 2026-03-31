# -*- coding: utf-8 -*-
"""
rth_dialog_catalog — Mixin de gerenciamento de catálogo, coleções e bandas do diálogo RTH
rth_dialog_catalog — RTH dialog mixin for catalog, collection and band management

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulo Qt para processar eventos da interface / Qt module to process UI events
from qgis.PyQt.QtWidgets import QApplication

# Importa catálogo e funções de composição / Import catalog and composition functions
from rth_catalog import (
    SATELLITE_COLLECTIONS, get_compositions, get_band_tuple, get_rgb_from_eo_bands
)
# Importa busca de catálogo e detalhes de coleção da API / Import catalog fetch and collection detail from API
from rth_stac_api import fetch_stac_catalog, fetch_collection_detail


class CatalogMixin:
    """Gerenciamento de satélites, coleções, composições e resolução de bandas / Satellite, collection, composition and band resolution management."""

    # Satélites exibidos no combo / Satellites shown in combo
    _DESIRED_SATS = frozenset({'Sentinel-2', 'Landsat', 'Amazonia-1', 'CBERS-4', 'CBERS-4A'})

    # Palavras-chave de exclusão nos IDs de coleção / Exclusion keywords in collection IDs
    # 'bundle'     → arquivos ZIP SAFE sem assets de banda individual / ZIP SAFE archives without individual band assets
    # 's2_l1c'     → Sentinel-2 Level-1C (existe apenas como bundle no BDC) / only exists as bundle in BDC
    # 'tsirf', 'bimonthly', 'yearly' → produtos mosaico TSIRF / TSIRF mosaic products
    # 'irs'        → sensor IRS monoespectral / IRS monospectral sensor
    _EXCLUDED_KEYWORDS = ('tsirf', 'bimonthly', 'yearly', 'irs', 'bundle', 's2_l1c')

    def _populate_satellites(self, catalog):
        """Preenche o combo de satélites com o catálogo fornecido / Fill satellite combo with given catalog.

        :param catalog: dicionário {satélite: [(id, título)]} / dict {satellite: [(id, title)]}
        """
        # Preserva o satélite selecionado atualmente / Preserve currently selected satellite
        current_sat = self.combo_satelite.currentText()
        self.combo_satelite.blockSignals(True)
        self.combo_satelite.clear()
        for sat in catalog:
            self.combo_satelite.addItem(sat)
        # Restaura a seleção anterior se possível / Restore previous selection if possible
        idx = self.combo_satelite.findText(current_sat)
        if idx >= 0:
            self.combo_satelite.setCurrentIndex(idx)
        self.combo_satelite.blockSignals(False)
        self._update_collections_for_current_sat()

    def _update_collections_for_current_sat(self):
        """Preenche o combo de coleções para o satélite selecionado / Fill collection combo for selected satellite."""
        sat     = self.combo_satelite.currentText()
        catalog = self._api_catalog if self._api_catalog else SATELLITE_COLLECTIONS
        self.combo_colecao.blockSignals(True)
        self.combo_colecao.clear()
        for col_id, col_desc in catalog.get(sat, []):
            # Armazena o ID como data, exibe a descrição / Store ID as data, display description
            self.combo_colecao.addItem(col_desc, col_id)
        self.combo_colecao.blockSignals(False)
        self._on_colecao_changed(0)

    def _refresh_catalog_from_api(self):
        """Tenta buscar o catálogo real da API BDC e filtra aos satélites desejados / Try to fetch real catalog from BDC API and filter to desired satellites."""
        self._set_status('Carregando catálogo da API BDC... / Loading BDC API catalog...')
        QApplication.processEvents()
        try:
            raw      = fetch_stac_catalog()
            filtered = {}
            for sat, colls in raw.items():
                if sat not in self._DESIRED_SATS:
                    continue
                # Remove coleções com palavras-chave excluídas e adiciona marcador (Brazil only)
                # Remove collections with excluded keywords and add (Brazil only) marker
                clean = [
                    (cid, title if '(Brazil only)' in title else title + '  [INPE/BDC] (Brazil only)')
                    for cid, title in colls
                    if not any(kw in cid.lower() for kw in self._EXCLUDED_KEYWORDS)
                ]
                if clean:
                    filtered[sat] = clean

            # Garante que coleções externas (PC e AWS) sejam sempre incluídas / Ensure external collections (PC and AWS) are always included
            _EXTRA_S2 = [
                ('sentinel-2-l2a',      'Level-2A SR — COG  [Planetary Computer]'),
                ('sentinel-2-l2a-aws',  'Level-2A SR — COG  [AWS Element84]'),
            ]
            _EXTRA_LS = [
                ('landsat-c2-l2',  'Collection 2 — Level-2 SR — L4-9  [Planetary Computer]'),
            ]

            existing_s2 = {cid for cid, _ in filtered.get('Sentinel-2', [])}
            for entry in _EXTRA_S2:
                if entry[0] not in existing_s2:
                    filtered.setdefault('Sentinel-2', []).append(entry)

            existing_ls = {cid for cid, _ in filtered.get('Landsat', [])}
            for entry in _EXTRA_LS:
                if entry[0] not in existing_ls:
                    filtered.setdefault('Landsat', []).append(entry)

            self._api_catalog = filtered
            self._populate_satellites(self._api_catalog)
            self._set_status(
                'Catálogo atualizado ({} satélites) / Catalog updated ({} satellites)'.format(
                    len(self._api_catalog), len(self._api_catalog)))
        except Exception as e:
            # Mantém o catálogo estático como fallback / Keep static catalog as fallback
            self._set_status(
                'Catálogo estático (API indisponível: {}) / Static catalog (API unavailable: {})'.format(
                    str(e)[:60], str(e)[:60]))

    def _on_satellite_changed(self, _idx):
        """Atualiza coleções ao mudar o satélite / Update collections when satellite changes."""
        self._update_collections_for_current_sat()

    def _on_colecao_changed(self, _idx):
        """Atualiza composições disponíveis ao mudar a coleção / Update available compositions when collection changes."""
        collection_id = self.combo_colecao.currentData()
        if not collection_id:
            return
        # Busca metadados da coleção para resolução de bandas / Fetch collection metadata for band resolution
        eo_bands = self._get_eo_bands(collection_id)
        self.combo_composicao.blockSignals(True)
        self.combo_composicao.clear()
        for label, key in get_compositions(collection_id, eo_bands):
            self.combo_composicao.addItem(label, key)
        self.combo_composicao.blockSignals(False)

    def _get_eo_bands(self, collection_id):
        """Retorna a lista eo:bands da coleção com cache / Return eo:bands list for collection with cache.

        :param collection_id: ID da coleção / Collection ID
        :returns: lista eo:bands ou [] / eo:bands list or []
        :rtype: list[dict]
        """
        # Verifica o cache primeiro / Check cache first
        if collection_id in self._collection_cache:
            detail = self._collection_cache[collection_id]
        else:
            try:
                detail = fetch_collection_detail(collection_id)
                self._collection_cache[collection_id] = detail
            except Exception:
                return []
        return detail.get('summaries', {}).get('eo:bands', [])

    def _get_band_tuple(self, collection_id, composition_key):
        """Resolve a tupla de bandas via eo:bands da API ou catálogo estático / Resolve band tuple via API eo:bands or static catalog.

        Prioridade / Priority:
        1. Metadados da coleção via common_name (mais preciso) / Collection metadata via common_name (more accurate)
        2. Catálogo estático como fallback / Static catalog as fallback

        :returns: tuple (ch1, ch2, ch3) ou None / tuple or None
        :rtype: tuple[str, str, str] | None
        """
        eo_bands = self._get_eo_bands(collection_id)
        if eo_bands:
            result = get_rgb_from_eo_bands(eo_bands, composition_key)
            if result:
                return result
        # Fallback: catálogo estático / Fallback: static catalog
        return get_band_tuple(collection_id, composition_key)

    def _on_slider_changed(self, value):
        """Atualiza o rótulo percentual do slider de nuvens / Update cloud slider percent label."""
        self.lbl_nuvem_val.setText('{}%'.format(value))
