# -*- coding: utf-8 -*-
"""
rth_dialog_actions — Mixin de ações de virtualização, download e controles de UI do diálogo RTH
rth_dialog_actions — RTH dialog mixin for virtualization, download actions and UI controls

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para caminhos / Standard library for paths
import os

# Módulos Qt para widgets e aplicação / Qt modules for widgets and application
from qgis.PyQt.QtWidgets import QFileDialog, QApplication

# Módulos QGIS para camadas e projeto (thread principal) / QGIS modules for layers and project (main thread)
from qgis.core import QgsRasterLayer, QgsProject

# Importa ações de virtualização / Import virtualization actions
from rth_layer_actions import virtualize_scenes

# Importa thread de download / Import download thread
from rth_downloader import DownloadThread

# Importa utilitários de camada para carregamento na thread principal / Import layer utils for main-thread loading
from rth_layer_utils import assign_crs_from_bbox, apply_rgb_renderer, apply_stretch


class ActionsMixin:
    """Virtualização, download assíncrono, barra de progresso e helpers de UI / Virtualization, async download, progress bar and UI helpers."""

    # ── Ação: Virtualizar ────────────────────────────────────────────────────

    def _on_virtualizar_clicked(self):
        """Virtualiza cenas marcadas/selecionadas como composição no QGIS / Virtualize checked/selected scenes as composite in QGIS."""
        features = self._get_checked_features()
        if not features:
            self._set_progress('Selecione ou marque ao menos uma cena / Select or check at least one scene', error=True)
            return

        collection_id   = self.combo_colecao.currentData()
        composition_key = self.combo_composicao.currentData() or 'RGB'
        # Resolve as bandas via eo:bands da API ou catálogo estático / Resolve bands via API eo:bands or static catalog
        bt = self._get_band_tuple(collection_id, composition_key)

        self._set_progress('Carregando {} cena(s)... / Loading {} scene(s)...'.format(
            len(features), len(features)))
        QApplication.processEvents()

        loaded = virtualize_scenes(
            features, collection_id, composition_key,
            progress_cb=self._set_progress,
            band_tuple=bt)

        if loaded > 0:
            self._set_progress('{} camada(s) carregada(s) / {} layer(s) loaded'.format(loaded, loaded))
        else:
            self._set_progress('Nenhuma camada válida. Veja o log acima / No valid layer. See log above', error=True)

    # ── Ação: Baixar (assíncrono) ─────────────────────────────────────────────

    def _on_baixar_clicked(self):
        """Inicia ou cancela o download das cenas em thread de background / Start or cancel scene download in background thread.

        Primeira chamada: inicia o download e muda o botão para 'Cancelar'.
        Segunda chamada (enquanto baixando): cancela o download em andamento.
        First call: starts download and changes button to 'Cancel'.
        Second call (while downloading): cancels in-progress download.
        """
        # Se já há download em andamento, cancela / If download is already running, cancel it
        if hasattr(self, '_download_thread') and self._download_thread is not None:
            if self._download_thread.isRunning():
                self._download_thread.cancel()
                self.btn_baixar.setText('Baixar / Download')
                self._set_progress('Cancelando... / Cancelling...')
                return

        # Validações de entrada / Input validations
        features = self._get_checked_features()
        if not features:
            self._set_progress('Selecione ou marque ao menos uma cena / Select or check at least one scene', error=True)
            return

        output_dir = self.edit_pasta.text().strip()
        if not output_dir:
            self._set_progress('Defina a pasta de destino / Set output folder', error=True)
            return
        if not os.path.isdir(output_dir):
            self._set_progress('Pasta não encontrada: {} / Folder not found: {}'.format(
                output_dir, output_dir), error=True)
            return

        collection_id   = self.combo_colecao.currentData()
        composition_key = self.combo_composicao.currentData() or 'RGB'
        # Resolve bandas / Resolve bands
        bt = self._get_band_tuple(collection_id, composition_key)

        # Inicializa barra de progresso — 1 arquivo por cena / Initialize progress bar — 1 file per scene
        self._show_progress(len(features))
        self._set_progress('Iniciando download... / Starting download...')

        # Cria e configura a thread de download / Create and configure download thread
        self._download_thread = DownloadThread(
            features, collection_id, composition_key, output_dir,
            band_tuple=bt)

        # Conecta sinais — layer_ready e finished_sig chegam na thread principal via AutoConnection
        # Connect signals — layer_ready and finished_sig arrive on main thread via AutoConnection
        self._download_thread.progress_sig.connect(self._set_progress)
        self._download_thread.count_sig.connect(self._update_progress)
        self._download_thread.layer_ready.connect(self._on_layer_ready)
        self._download_thread.finished_sig.connect(self._on_download_finished)

        # Muda botão para Cancelar durante o download / Change button to Cancel during download
        self.btn_baixar.setText('Cancelar / Cancel')
        self._download_thread.start()

    def _on_layer_ready(self, path, name, feature):
        """Carrega uma camada no QGIS — executado na thread principal via sinal Qt / Load a layer in QGIS — executed on main thread via Qt signal.

        Chamado automaticamente pela thread de download para cada arquivo concluído.
        Called automatically by the download thread for each completed file.

        :param path: caminho do arquivo GeoTIFF no disco / GeoTIFF file path on disk
        :param name: nome da camada no QGIS / layer name in QGIS
        :param feature: feature GeoJSON da cena (para atribuição de CRS) / scene GeoJSON feature (for CRS assignment)
        """
        layer = QgsRasterLayer(path, name)
        if layer.isValid():
            # CRS e renderização devem ser feitos na thread principal / CRS and rendering must be done on main thread
            assign_crs_from_bbox(layer, feature)
            apply_rgb_renderer(layer)
            QgsProject.instance().addMapLayer(layer)
            self._set_progress('{}: carregado / loaded — {}'.format(name, os.path.basename(path)))

    def _on_download_finished(self, count):
        """Chamado quando a thread de download termina (com sucesso ou cancelado) / Called when download thread finishes (success or cancelled).

        :param count: número de arquivos criados com sucesso / number of successfully created files
        """
        self._hide_progress()
        # Restaura texto do botão / Restore button text
        self.btn_baixar.setText('Baixar / Download')
        output_dir = self.edit_pasta.text().strip()
        if count > 0:
            self._set_progress('{} arquivo(s) em: {} / {} file(s) in: {}'.format(
                count, output_dir, count, output_dir))
        else:
            self._set_progress('Nenhum arquivo baixado. Veja o log acima / No file downloaded. See log above', error=True)
        # Libera referência à thread finalizada / Release reference to finished thread
        self._download_thread = None

    def _on_browse_clicked(self):
        """Abre o seletor de pasta nativa / Open native folder selector."""
        folder = QFileDialog.getExistingDirectory(
            self,
            'Selecione a pasta de destino / Select output folder',
            self.edit_pasta.text() or os.path.expanduser('~'))
        if folder:
            self.edit_pasta.setText(folder)

    # ── Barra de progresso ───────────────────────────────────────────────────

    def _show_progress(self, total):
        """Exibe e inicializa a barra de progresso / Show and initialize progress bar."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

    def _update_progress(self, current, total):
        """Atualiza o valor da barra de progresso / Update progress bar value."""
        self.progress_bar.setValue(current)
        QApplication.processEvents()

    def _hide_progress(self):
        """Esconde a barra de progresso / Hide progress bar."""
        self.progress_bar.setVisible(False)

    # ── Helpers de UI ────────────────────────────────────────────────────────

    def _set_status(self, msg, error=False):
        """Atualiza o rótulo de status da busca / Update search status label."""
        color = '#cc0000' if error else '#444'
        self.lbl_status.setStyleSheet('color: {}; font-style: italic;'.format(color))
        self.lbl_status.setText(msg)

    def _set_progress(self, msg, error=False):
        """Atualiza o rótulo de progresso / Update progress label."""
        color = '#cc0000' if error else '#0055aa'
        self.lbl_progresso.setStyleSheet('color: {};'.format(color))
        self.lbl_progresso.setText(msg)
        QApplication.processEvents()
