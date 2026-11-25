# -*- coding: utf-8 -*-
"""
rth_dialog_catalog — Mixin de gerenciamento de catálogo, coleções e bandas do diálogo RTH
rth_dialog_catalog — RTH dialog mixin for catalog, collection and band management

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Módulo Qt para processar eventos da interface / Qt module to process UI events
from qgis.PyQt.QtWidgets import QApplication, QDialog

# Importa catálogo e funções de composição / Import catalog and composition functions
from .rth_catalog import (
    SATELLITE_COLLECTIONS, get_compositions, get_band_tuple, get_rgb_from_eo_bands,
    get_band_catalog, get_custom_compositions, save_custom_composition, delete_custom_composition,
    NO_CLOUD_SATELLITES, needs_eo_bands,
)
# Importa busca de catálogo e detalhes de coleção da API / Import catalog fetch and collection detail from API
from .rth_stac_api import fetch_stac_catalog, fetch_collection_detail


class CatalogMixin:
    """Gerenciamento de satélites, coleções, composições e resolução de bandas / Satellite, collection, composition and band resolution management."""

    # Satélites exibidos no combo / Satellites shown in combo
    _DESIRED_SATS = frozenset({'Sentinel-2', 'Landsat', 'Amazonia-1', 'CBERS-4', 'CBERS-4A'})

    # Palavras-chave de exclusão nos IDs de coleção / Exclusion keywords in collection IDs
    # 'bundle'     → arquivos ZIP SAFE sem assets de banda individual / ZIP SAFE archives without individual band assets
    # 's2_l1c'     → Sentinel-2 Level-1C (existe apenas como bundle no BDC) / only exists as bundle in BDC
    # 'tsirf', 'bimonthly', 'yearly' → produtos mosaico TSIRF / TSIRF mosaic products
    # 'irs'        → sensor IRS monoespectral / IRS monospectral sensor
    # 'rtc-1'      → sentinel-1-rtc-1 BDC (cobertura incompleta, <2% do Brasil em 2024) / BDC RTC-1 (sparse, <2% Brazil coverage in 2024)
    # 'mapaquali'  → coleção MAPAQUALI Sentinel-2 removida a pedido (ID usa abreviação 'mq') /
    #               MAPAQUALI Sentinel-2 collection removed on request (ID uses abbreviation 'mq')
    # 'mq_rrs'    → s2_msi_mq_rrs-1 (MAPAQUALI Aquatic Remote Sensing Reflectance)
    # 'mq_wqp'    → s2_msi_mq_wqp-1 (MAPAQUALI Water Quality Parameters)
    _EXCLUDED_KEYWORDS = ('tsirf', 'bimonthly', 'yearly', 'irs', 'bundle', 's2_l1c', 'rtc-1',
                          'mapaquali', 'mq_rrs', 'mq_wqp')

    # Sobrescreve títulos vagos que a API BDC retorna com nomes mais descritivos
    # Override vague BDC API titles with more descriptive names
    _COLLECTION_TITLE_OVERRIDES = {
        # Landsat — INPE/BDC
        'landsat-2':     'Landsat 5 · 7 · 8 · 9 — Imagens  [INPE/BDC] (Brazil only)',
        'LANDSAT-16D-1': 'Landsat 5 · 7 · 8 · 9 — DataCube 16 dias  [INPE/BDC] (Brazil only)',
        # Sentinel-2 — INPE/BDC
        'S2_L2A-1':      'Sentinel-2 — Imagens  [INPE/BDC] (Brazil only)',
        'S2-16D-2':      'Sentinel-2 — DataCube 16 dias  [INPE/BDC] (Brazil only)',
    }

    # Ordem de exibição por satélite: Cenas → DataCube 16 dias → Global
    # Display order per satellite: Scenes → 16-day DataCube → Global
    _COLLECTION_ORDER = {
        'Sentinel-2': ['S2_L2A-1', 'S2-16D-2', 'sentinel-2-l2a', 'sentinel-2-l2a-aws'],
        'Landsat':    ['landsat-2', 'LANDSAT-16D-1', 'landsat-c2-l2'],
    }

    # Ordem dos satélites no combo / Satellite display order in combo
    _SATELLITE_ORDER = ['Sentinel-2', 'Landsat', 'CBERS-4', 'CBERS-4A', 'Amazonia-1']

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
                # Remove coleções com palavras-chave excluídas, aplica overrides e adiciona marcador (Brazil only)
                # Remove excluded collections, apply title overrides and add (Brazil only) marker
                clean = []
                for cid, title in colls:
                    if any(kw in cid.lower() for kw in self._EXCLUDED_KEYWORDS):
                        continue
                    # Override tem prioridade sobre o título vago da API / Override takes priority over vague API title
                    if cid in self._COLLECTION_TITLE_OVERRIDES:
                        clean.append((cid, self._COLLECTION_TITLE_OVERRIDES[cid]))
                    else:
                        clean.append((cid, title if '(Brazil only)' in title else title + '  [INPE/BDC] (Brazil only)'))
                if clean:
                    filtered[sat] = clean

            # Garante que coleções externas (PC e AWS) sejam sempre incluídas / Ensure external collections (PC and AWS) are always included
            _EXTRA_S2 = [
                ('sentinel-2-l2a',      'Sentinel-2 — Imagens Globais  [Planetary Computer]'),
                ('sentinel-2-l2a-aws',  'Sentinel-2 — Imagens Globais  [AWS Element84]'),
            ]
            _EXTRA_LS = [
                ('landsat-c2-l2',  'Landsat 4 · 5 · 7 · 8 · 9 — Imagens Globais  [Planetary Computer]'),
            ]

            existing_s2 = {cid for cid, _ in filtered.get('Sentinel-2', [])}
            for entry in _EXTRA_S2:
                if entry[0] not in existing_s2:
                    filtered.setdefault('Sentinel-2', []).append(entry)

            existing_ls = {cid for cid, _ in filtered.get('Landsat', [])}
            for entry in _EXTRA_LS:
                if entry[0] not in existing_ls:
                    filtered.setdefault('Landsat', []).append(entry)

            # Aplica ordem de coleções por satélite (Imagens → DataCube → Global) / Apply collection order per satellite
            for sat, order in self._COLLECTION_ORDER.items():
                if sat not in filtered:
                    continue
                by_id     = {e[0]: e for e in filtered[sat]}
                ordered   = [by_id[cid] for cid in order if cid in by_id]
                remaining = [e for e in filtered[sat] if e[0] not in set(order)]
                filtered[sat] = ordered + remaining

            # Aplica ordem dos satélites no combo / Apply satellite order in combo
            ordered_catalog = {}
            for sat in self._SATELLITE_ORDER:
                if sat in filtered:
                    ordered_catalog[sat] = filtered[sat]
            # Satélites não listados em _SATELLITE_ORDER vão ao final / Unlisted satellites go at the end
            for sat in filtered:
                if sat not in ordered_catalog:
                    ordered_catalog[sat] = filtered[sat]

            self._api_catalog = ordered_catalog
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
        # Oculta o slider de nuvens para satélites SAR/S3 que não têm eo:cloud_cover
        # Hide cloud slider for SAR/S3 satellites that have no eo:cloud_cover
        sat        = self.combo_satelite.currentText()
        has_cloud  = sat not in NO_CLOUD_SATELLITES
        for attr in ('lbl_nuvens', 'slider_nuvem', 'lbl_nuvem_val'):
            w = getattr(self, attr, None)
            if w:
                w.setVisible(has_cloud)
        if not has_cloud:
            # Força 100 para evitar filtro de nuvens indevido na busca / Force 100 to avoid spurious cloud filter on search
            slider = getattr(self, 'slider_nuvem', None)
            if slider:
                slider.setValue(100)

    def _on_colecao_changed(self, _idx):
        """Atualiza composições disponíveis ao mudar a coleção / Update available compositions when collection changes."""
        collection_id = self.combo_colecao.currentData()
        if not collection_id:
            return
        # Pula a busca de eo:bands para coleções SAR/PAN/single-band — composição é fixa,
        # e a chamada de rede bloquearia a thread principal sem nenhum benefício.
        # Skip eo:bands fetch for SAR/PAN/single-band — composition is fixed,
        # and the network call would block the main thread with no benefit.
        eo_bands = self._get_eo_bands(collection_id) if needs_eo_bands(collection_id) else []
        self.combo_composicao.blockSignals(True)
        self.combo_composicao.clear()
        for label, key in get_compositions(collection_id, eo_bands):
            self.combo_composicao.addItem(label, key)

        # Adiciona "Personalizado" se a coleção tem catálogo de bandas (≥2 bandas) e não é SAR/PAN/single-band
        # Add "Personalizado" if the collection has a band catalog (≥2 bands) and is not SAR/PAN/single-band
        if len(get_band_catalog(collection_id)) >= 2 and needs_eo_bands(collection_id):
            self.combo_composicao.addItem('Personalizado / Custom', 'CUSTOM')

            # Composições salvas com separador visual / Saved compositions with visual separator
            saved = get_custom_compositions(collection_id)
            if saved:
                self.combo_composicao.insertSeparator(self.combo_composicao.count())
                for comp in saved:
                    name = comp.get('name', '?')
                    self.combo_composicao.addItem('★  ' + name, 'CUSTOM:' + name)

        self.combo_composicao.blockSignals(False)
        # Atualiza estado do botão de configurar / Update configure button state
        self._on_composicao_index_changed(self.combo_composicao.currentIndex())

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
        """Resolve a tupla de bandas via eo:bands da API, composição personalizada ou catálogo estático /
        Resolve band tuple via API eo:bands, custom composition, or static catalog.

        Prioridade / Priority:
        1. Composição personalizada ativa (CUSTOM ou CUSTOM:<nome>) / Active custom composition
        2. Metadados da coleção via common_name / Collection metadata via common_name
        3. Catálogo estático como fallback / Static catalog as fallback

        :returns: tuple (ch1, ch2, ch3) ou None / tuple or None
        :rtype: tuple[str, str, str] | None
        """
        # Composição personalizada sem nome — usa o estado em memória / Unsaved custom — use in-memory state
        if composition_key == 'CUSTOM':
            cb = getattr(self, '_custom_bands', None) or {}
            r, g, b = cb.get('r'), cb.get('g'), cb.get('b')
            if r and g and b:
                return (r, g, b)
            return None

        # Composição personalizada salva — carrega do QgsSettings / Saved custom — load from QgsSettings
        if isinstance(composition_key, str) and composition_key.startswith('CUSTOM:'):
            name = composition_key[7:]
            for comp in get_custom_compositions(collection_id):
                if comp.get('name') == name:
                    r, g, b = comp.get('r'), comp.get('g'), comp.get('b')
                    if r and g and b:
                        return (r, g, b)
            return None

        # Padrão: API → catálogo estático / Default: API → static catalog
        eo_bands = self._get_eo_bands(collection_id) if needs_eo_bands(collection_id) else []
        if eo_bands:
            result = get_rgb_from_eo_bands(eo_bands, composition_key)
            if result:
                return result
        return get_band_tuple(collection_id, composition_key)

    def _on_composicao_index_changed(self, _idx):
        """Habilita o botão ⚙ apenas para composições personalizadas / Enable ⚙ button only for custom compositions."""
        if not hasattr(self, 'btn_cfg_composicao'):
            return
        key = self.combo_composicao.currentData() or ''
        is_custom = (key == 'CUSTOM' or (isinstance(key, str) and key.startswith('CUSTOM:')))
        self.btn_cfg_composicao.setEnabled(is_custom)

    def _on_cfg_composicao_clicked(self):
        """Abre o dialog de composição personalizada para criar ou editar / Open custom composition dialog to create or edit."""
        collection_id = self.combo_colecao.currentData()
        if not collection_id:
            return

        key       = self.combo_composicao.currentData() or ''
        edit_name = key[7:] if key.startswith('CUSTOM:') else None

        from .rth_custom_composition_dialog import CustomCompositionDialog
        dlg = CustomCompositionDialog(collection_id, edit_name, self)
        if dlg.exec_() != QDialog.Accepted:
            return

        result = dlg.get_result()

        if result.get('deleted'):
            # Remove do QgsSettings e recarrega o combo / Remove from QgsSettings and reload combo
            delete_custom_composition(collection_id, edit_name)
            self._on_colecao_changed(0)
            # Seleciona a primeira opção / Select first option
            self.combo_composicao.setCurrentIndex(0)
            return

        # Armazena no estado em memória (CUSTOM sem nome usa isso) / Store in memory state
        self._custom_bands = result

        if result.get('saved') and result.get('name'):
            # Salva e recarrega o combo / Save and reload combo
            save_custom_composition(
                collection_id, result['name'],
                result['r'], result['g'], result['b'],
                result.get('extra', []))
            self._on_colecao_changed(0)
            # Seleciona a composição salva recém-criada / Select the newly saved composition
            new_key = 'CUSTOM:' + result['name']
            idx = self.combo_composicao.findData(new_key)
            if idx >= 0:
                self.combo_composicao.setCurrentIndex(idx)
        else:
            # Aplicar sem salvar — garante que "Personalizado" está selecionado /
            # Apply without saving — ensure "Personalizado" is selected
            idx = self.combo_composicao.findData('CUSTOM')
            if idx >= 0:
                self.combo_composicao.setCurrentIndex(idx)

    def _on_slider_changed(self, value):
        """Atualiza o rótulo percentual do slider de nuvens / Update cloud slider percent label."""
        self.lbl_nuvem_val.setText('{}%'.format(value))
