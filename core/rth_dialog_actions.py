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
from qgis.PyQt.QtWidgets import (
    QFileDialog, QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QFrame,
)
from qgis.PyQt.QtCore import pyqtSignal, Qt

# Módulos QGIS para camadas e projeto (thread principal) / QGIS modules for layers and project (main thread)
from qgis.core import QgsRasterLayer, QgsProject

# Importa ações de virtualização / Import virtualization actions
from .rth_layer_actions import virtualize_scenes

# Importa thread de download / Import download thread
from .rth_downloader import DownloadThread

# Importa utilitários de camada para carregamento na thread principal / Import layer utils for main-thread loading
from .rth_layer_utils import assign_crs_from_bbox, apply_rgb_renderer, apply_stretch, collapse_layer


# ── Widget de linha de download ────────────────────────────────────────────────
# ==============================================================================
# _DownloadRow — card visual para um download em andamento
#
# O que é:
#   Um QWidget que representa UMA cena na fila de download.
#   Visualmente: cabeçalho azul escuro (nome da cena) + corpo claro
#   com barra de progresso verde e texto de status.
#
# pyqtSignal(object):
#   `row_removed` é um sinal Qt — pense nele como um "evento" que pode
#   ter zero ou mais "ouvintes" (slots) conectados. Quando emitimos
#   row_removed.emit(self), todos os slots conectados são chamados com
#   a instância deste widget como argumento. Isso permite que o diálogo
#   pai saiba quando uma linha foi removida sem criar acoplamento direto.
#
# Integração com DownloadThread:
#   attach_thread() conecta os sinais da thread a slots deste widget.
#   Como a thread roda em background e os sinais Qt são entregues via
#   fila de eventos, todos os slots (_on_msg, _on_count, etc.) executam
#   na thread principal (UI thread), o que é obrigatório para tocar widgets.
# ==============================================================================

class _DownloadRow(QWidget):
    """Carta de download — cabeçalho colorido, barra de progresso verde, status.
    Download card — colored header, green progress bar, status text."""

    row_removed = pyqtSignal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._thread = None
        self._done   = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Cabeçalho: barra com nome da cena + botão cancelar ────────────────
        # Header bar with scene name and cancel button
        header = QFrame()
        header.setFixedHeight(26)
        header.setStyleSheet('background:#1e4d7a;border-radius:4px 4px 0px 0px;')
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(8, 0, 4, 0)
        h_row.setSpacing(4)

        self._lbl_title = QLabel(title)
        self._lbl_title.setStyleSheet(
            'font-size:10px;font-weight:bold;color:#ddeeff;background:transparent;')
        h_row.addWidget(self._lbl_title, 1)

        self._btn = QPushButton('✕')
        self._btn.setFixedSize(20, 20)
        self._btn.setToolTip('Cancelar / Cancel')
        self._btn.setStyleSheet(
            'QPushButton{border:none;border-radius:2px;background:transparent;'
            'color:#aacfe8;font-size:10px;}'
            'QPushButton:hover{background:#cc2222;color:#fff;}')
        self._btn.clicked.connect(self._on_action)
        h_row.addWidget(self._btn)
        root.addWidget(header)

        # ── Corpo: barra verde + status ───────────────────────────────────────
        # Body: green progress bar + status text
        body = QFrame()
        body.setStyleSheet(
            'background:#f3f7fc;border:1px solid #b8cfe0;'
            'border-top:none;border-radius:0px 0px 4px 4px;')
        b_layout = QVBoxLayout(body)
        b_layout.setContentsMargins(8, 5, 8, 5)
        b_layout.setSpacing(3)

        # Barra verde que cresce conforme o download avança / Green bar grows as download progresses
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(16)
        self._bar.setTextVisible(True)
        self._bar.setFormat('%p%')
        self._bar.setStyleSheet(
            'QProgressBar{border:1px solid #b0c8dc;border-radius:3px;background:#dde8f0;'
            'text-align:center;font-size:9px;color:#334455;}'
            'QProgressBar::chunk{background:#00a848;border-radius:3px;}')
        b_layout.addWidget(self._bar)

        self._lbl_status = QLabel('Na fila... / In queue...')
        self._lbl_status.setStyleSheet('font-size:10px;color:#667788;background:transparent;')
        b_layout.addWidget(self._lbl_status)

        root.addWidget(body)
        self.setFixedHeight(82)

    def attach_thread(self, thread):
        # Conecta os sinais da DownloadThread aos slots deste widget.
        # Qt gerencia a entrega entre threads automaticamente: mesmo que
        # thread.progress_sig.emit() seja chamado em background, _on_msg()
        # é sempre executado na thread principal (UI thread). Isso é feito
        # pela QueuedConnection padrão para sinais cross-thread.
        #
        # warp_pct_sig.connect(self._bar.setValue) conecta diretamente ao
        # slot nativo do Qt (QProgressBar.setValue), sem Python intermediário —
        # é a conexão mais eficiente possível.
        self._thread = thread
        thread.started.connect(self._on_started)
        thread.progress_sig.connect(self._on_msg)
        thread.count_sig.connect(self._on_count)
        thread.warp_pct_sig.connect(self._bar.setValue)
        thread.finished_sig.connect(self._on_finished)

    def _on_started(self):
        self._lbl_status.setStyleSheet('font-size:10px;color:#1a73e8;background:transparent;')
        self._lbl_status.setText('Iniciando download... / Starting download...')

    def _on_msg(self, msg, error):
        color = '#cc0000' if error else '#445566'
        self._lbl_status.setStyleSheet(
            'font-size:10px;color:{};background:transparent;'.format(color))
        self._lbl_status.setText(msg[:110])

    def _on_count(self, current, total):
        if total > 0:
            self._bar.setValue(int(current * 100 / total))

    def _on_finished(self, count):
        self._done   = True
        self._thread = None
        self._bar.setValue(100)
        if count > 0:
            self._lbl_status.setText(
                '{} arquivo(s) salvo(s) ✓ / {} file(s) saved ✓'.format(count, count))
            self._lbl_status.setStyleSheet(
                'font-size:10px;color:#007722;font-weight:bold;background:transparent;')
        else:
            self._bar.setValue(0)
            self._bar.setStyleSheet(
                'QProgressBar{border:1px solid #b0c8dc;border-radius:3px;background:#dde8f0;'
                'text-align:center;font-size:9px;color:#334455;}'
                'QProgressBar::chunk{background:#aaaaaa;border-radius:3px;}')
            self._lbl_status.setText('Cancelado / Cancelled')
            self._lbl_status.setStyleSheet('font-size:10px;color:#888;background:transparent;')
        self._btn.setToolTip('Remover / Remove')

    def _on_action(self):
        # Guarda contra cliques múltiplos em rápida sucessão.
        # Guard against multiple rapid clicks.
        if getattr(self, '_removing', False):
            return
        if self._thread and self._thread.isRunning():
            # Desconecta TODOS os sinais antes de cancelar para evitar crash.
            # Se o usuário fechar o diálogo enquanto a thread ainda roda, a
            # thread tentaria emitir sinais para um widget C++ já deletado →
            # segfault no QGIS. Desconectar aqui garante que a thread limpe
            # o arquivo parcial em background sem tocar nenhum widget.
            # Disconnect ALL signals before cancelling to prevent crash.
            # If the user closes the dialog while the thread is still running,
            # the thread would emit signals to an already-deleted C++ widget →
            # QGIS segfault. Disconnecting here ensures the thread cleans up
            # the partial file in background without touching any widget.
            thread = self._thread
            self._thread = None
            self._done   = True
            # Desconecta APENAS os slots deste widget — disconnect() sem argumento
            # removeria também _on_dl_group_done() e quebraria a fila.
            # Only disconnect THIS widget's own slots — disconnect() with no arg
            # would also remove _on_dl_group_done() and break the queue.
            try:
                thread.started.disconnect(self._on_started)
                thread.progress_sig.disconnect(self._on_msg)
                thread.count_sig.disconnect(self._on_count)
                thread.warp_pct_sig.disconnect(self._bar.setValue)
                thread.finished_sig.disconnect(self._on_finished)
            except Exception:  # nosec B110
                pass
            thread.cancel()
            # Atualiza UI imediatamente para estado cancelado / Update UI immediately to cancelled state
            self._bar.setValue(0)
            self._bar.setStyleSheet(
                'QProgressBar{border:1px solid #b0c8dc;border-radius:3px;background:#dde8f0;'
                'text-align:center;font-size:9px;color:#334455;}'
                'QProgressBar::chunk{background:#aaaaaa;border-radius:3px;}')
            self._lbl_status.setText('Cancelado / Cancelled')
            self._lbl_status.setStyleSheet('font-size:10px;color:#888;background:transparent;')
            self._btn.setToolTip('Remover / Remove')
            # Segundo clique remove a linha / Second click removes the row
        else:
            self._removing = True
            self.row_removed.emit(self)
            self.setParent(None)
            self.deleteLater()

    def is_done(self):
        return self._done

    def set_queue_position(self, pos):
        """Mostra posição na fila de espera / Show waiting queue position."""
        self._lbl_status.setText(
            'Aguardando — {}º na fila / Waiting — #{} in queue'.format(pos, pos))
        self._lbl_status.setStyleSheet('font-size:10px;color:#667788;background:transparent;')

    def show_retry_wait(self, secs, attempt, max_attempts):
        """Mostra mensagem de retry entre tentativas / Show retry message between attempts."""
        self._done = False
        self._bar.setValue(0)
        self._bar.setStyleSheet(
            'QProgressBar{border:1px solid #b0c8dc;border-radius:3px;background:#dde8f0;'
            'text-align:center;font-size:9px;color:#334455;}'
            'QProgressBar::chunk{background:#f5a623;border-radius:3px;}')
        self._lbl_status.setText(
            'Erro de rede — retentar em {}s ({}/{}) / '
            'Network error — retrying in {}s ({}/{})'.format(
                secs, attempt, max_attempts, secs, attempt, max_attempts))
        self._lbl_status.setStyleSheet('font-size:10px;color:#cc7700;background:transparent;')

    def reset_for_retry(self):
        """Reseta o estado do widget para uma nova tentativa de download / Reset widget state for a new download attempt."""
        self._done     = False
        self._removing = False
        self._thread   = None
        self._bar.setValue(0)
        self._bar.setStyleSheet(
            'QProgressBar{border:1px solid #b0c8dc;border-radius:3px;background:#dde8f0;'
            'text-align:center;font-size:9px;color:#334455;}'
            'QProgressBar::chunk{background:#00a848;border-radius:3px;}')
        self._lbl_status.setText('Retentando download... / Retrying download...')
        self._lbl_status.setStyleSheet('font-size:10px;color:#1a73e8;background:transparent;')
        self._btn.setToolTip('Cancelar / Cancel')

    def cancel_if_running(self):
        if self._thread and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(3000)


class _PrebuiltEntry:
    """Grupo de threads já criadas e conectadas — sem criação lazy, sem retry.
    Usado pelo download AOI e pelo download inteligente, que constroem threads
    com signal-routing complexo antes de enfileirar.
    Pre-built and pre-connected thread group — no lazy creation, no retry.
    Used by AOI download and smart download, which build threads with complex
    signal routing before queuing."""
    __slots__ = ('threads', 'row', 'retry_count', 'thread')

    def __init__(self, threads):
        self.threads     = threads
        self.row         = None  # Sem display de posição / No position display
        self.retry_count = 0
        self.thread      = threads[0] if threads else None


class _DlEntry:
    """Contém todos os dados necessários para criar (e recriar, no retry) uma DownloadThread /
    Holds all data needed to create (and recreate, on retry) a DownloadThread."""
    __slots__ = ('features', 'collection_id', 'composition_key', 'output_dir',
                 'band_tuple', 'band_names', 'row', 'retry_count', 'thread')

    def __init__(self, features, collection_id, composition_key, output_dir,
                 band_tuple, band_names, row):
        self.features        = features
        self.collection_id   = collection_id
        self.composition_key = composition_key
        self.output_dir      = output_dir
        self.band_tuple      = band_tuple
        self.band_names      = band_names
        self.row             = row
        self.retry_count     = 0
        self.thread          = None


class _DlQueue:
    """Fila FIFO universal de downloads — um item por vez, com retry automático em falha de rede.
    Universal FIFO download queue — one item at a time, with auto-retry on network failure.

    Ciclo de vida de um _DlEntry:
      1. enqueue(entry)  → entra na fila de espera; row.set_queue_position() atualiza o label
      2. _start_next()   → tira da fila e chama _launch_entry()
      3. _launch_entry() → cria a DownloadThread, conecta sinais, chama thread.start()
      4. _on_done()      → se sucesso → avança para o próximo
                         → se falha + retry disponível → row.show_retry_wait() + QTimer → _retry()
                         → se falha + sem retry → avança
    """

    # Tentativas extras da fila (além das 3 do GDAL interno) /
    # Extra queue-level attempts (on top of GDAL's internal 3 retries)
    MAX_RETRIES  = 2
    RETRY_DELAYS = (15_000, 45_000)  # ms: 15s depois 45s / 15s then 45s

    def __init__(self, on_layer_ready, on_tab_update):
        self._entries   = []     # list[_DlEntry] — itens aguardando / waiting items
        self._active    = None   # _DlEntry | None — item em execução / running item
        self._on_layer  = on_layer_ready
        self._on_update = on_tab_update

    # ── API pública ───────────────────────────────────────────────────────────

    def enqueue(self, entry):
        """Adiciona ao final da fila e inicia se ociosa / Add to end and start if idle."""
        self._entries.append(entry)
        self._refresh_positions()
        if self._active is None:
            self._start_next()

    def remove_waiting_by_row(self, row):
        """Remove da fila um item ainda não iniciado pelo seu widget /
        Remove a not-yet-started item from the queue by its widget."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.row is not row]
        if len(self._entries) < before:
            self._refresh_positions()

    # ── Internos ──────────────────────────────────────────────────────────────

    def enqueue_prebuilt_group(self, threads, row=None):
        """Enfileira grupo de threads já criadas e conectadas (AOI, download inteligente).
        `row` é a _DownloadRow líder do grupo — exibe posição na fila quando fornecida.
        Queue a group of already-created and connected threads (AOI, smart download).
        `row` is the leading _DownloadRow — shows queue position when provided."""
        entry = _PrebuiltEntry(threads)
        entry.row = row
        self._entries.append(entry)
        self._refresh_positions()
        if self._active is None:
            self._start_next()

    def _start_next(self):
        if not self._entries:
            self._active = None
            return
        entry = self._entries.pop(0)
        self._active = entry
        self._refresh_positions()
        if isinstance(entry, _PrebuiltEntry):
            self._launch_prebuilt(entry)
        else:
            self._launch_entry(entry, is_retry=False)

    def _launch_prebuilt(self, entry):
        """Inicia threads pré-criadas; avança fila quando a 1ª termina /
        Start pre-built threads; advance queue when the 1st thread finishes."""
        entry.threads[0].finished_sig.connect(
            lambda count, _e=entry: self._on_prebuilt_done(count, _e))
        for t in entry.threads:
            t.start()

    def _on_prebuilt_done(self, count, entry):
        """Avança a fila quando o grupo pré-criado termina (sem retry) /
        Advance the queue when the pre-built group finishes (no retry)."""
        self._active = None
        self._start_next()

    def _launch_entry(self, entry, is_retry):
        """Cria uma nova DownloadThread (QThread não pode ser reiniciada, então sempre criamos uma nova) /
        Creates a new DownloadThread (QThread cannot be restarted, so we always create a fresh one)."""
        if is_retry:
            try:
                entry.row.reset_for_retry()
            except RuntimeError:
                # Widget C++ já deletado (usuário removeu durante espera de retry) /
                # C++ widget already deleted (user removed during retry wait)
                self._active = None
                self._start_next()
                return

        thread = DownloadThread(
            entry.features, entry.collection_id, entry.composition_key,
            entry.output_dir, band_tuple=entry.band_tuple, band_names=entry.band_names)
        entry.thread = thread

        thread.layer_ready.connect(self._on_layer)
        thread.finished_sig.connect(self._on_update)
        # Captura entry por valor default para evitar closure sobre variável mutável /
        # Capture entry by default value to avoid closure over mutable variable
        thread.finished_sig.connect(lambda count, _e=entry: self._on_done(count, _e))
        entry.row.attach_thread(thread)
        thread.start()

    def _on_done(self, count, entry):
        """Chamado quando a thread termina (sucesso ou falha) / Called when thread finishes (success or failure)."""
        # Verifica se foi cancelamento pelo usuário (não gera retry) vs falha de rede (gera retry).
        # O _cancelled_ref[0] é True quando o usuário clicou em cancelar; False em falha de rede.
        # Check if this was a user cancellation (no retry) vs network error (retry).
        # _cancelled_ref[0] is True when the user clicked cancel; False on network failure.
        thread = entry.thread
        was_cancelled = bool(
            thread._cancelled_ref[0] if thread is not None else True)

        if count == 0 and not was_cancelled and entry.retry_count < self.MAX_RETRIES:
            # Falha de rede: agenda retry com atraso crescente /
            # Network failure: schedule retry with increasing delay
            delay_ms = self.RETRY_DELAYS[entry.retry_count]
            entry.retry_count += 1
            try:
                entry.row.show_retry_wait(
                    delay_ms // 1000, entry.retry_count, self.MAX_RETRIES)
            except RuntimeError:
                # Row deletada enquanto a thread rodava — avança sem retry /
                # Row deleted while thread was running — advance without retry
                self._active = None
                self._start_next()
                return
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(delay_ms, lambda _e=entry: self._retry(_e))
        else:
            # Sucesso, cancelado pelo usuário, ou esgotou retries: avança /
            # Success, user-cancelled, or retries exhausted: advance
            self._active = None
            self._start_next()

    def _retry(self, entry):
        """Recria a thread e tenta de novo / Recreate the thread and try again."""
        # Verifica se o widget ainda está vivo antes de retentar /
        # Check if the widget is still alive before retrying
        try:
            entry.row.isVisible()
        except RuntimeError:
            # Row deletada durante a espera do retry — avança para o próximo /
            # Row deleted during retry wait — advance to next
            self._active = None
            self._start_next()
            return
        self._launch_entry(entry, is_retry=True)

    def _refresh_positions(self):
        """Atualiza o label de posição de todos os itens em espera /
        Update position label for all waiting items."""
        for i, e in enumerate(self._entries, 1):
            if e.row:
                try:
                    e.row.set_queue_position(i)
                except RuntimeError:  # nosec B110
                    pass  # Widget deletado entre ciclos do event loop / Widget deleted between event loop cycles


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

        # Composição personalizada sem bandas configuradas / Custom composition without configured bands
        if composition_key == 'CUSTOM' and not bt:
            self._set_progress(
                'Configure as bandas R, G, B antes de virtualizar. Clique em ⚙ / '
                'Configure R, G, B bands before virtualizing. Click ⚙', error=True)
            return

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

    # ── Ação: Baixar (fila assíncrona) ───────────────────────────────────────

    def _on_baixar_clicked(self):
        """Enfileira o download das cenas selecionadas e muda para a aba Downloads / Queue download of selected scenes and switch to Downloads tab."""
        features = self._get_checked_features()
        if not features:
            self._set_progress('Selecione ou marque ao menos uma cena / Select or check at least one scene', error=True)
            return

        output_dir = self.edit_pasta.text().strip()
        if not output_dir:
            self._set_progress('Defina a pasta de destino / Set output folder', error=True)
            return
        if not os.path.isdir(output_dir):
            self._set_progress('Pasta não encontrada / Folder not found: {}'.format(output_dir), error=True)
            return

        collection_id   = self.combo_colecao.currentData()
        composition_key = self.combo_composicao.currentData() or 'RGB'
        bt = self._get_band_tuple(collection_id, composition_key)

        # Composição personalizada sem bandas configuradas / Custom composition without configured bands
        if composition_key == 'CUSTOM' and not bt:
            self._set_progress(
                'Configure as bandas R, G, B antes de baixar. Clique em ⚙ / '
                'Configure R, G, B bands before downloading. Click ⚙', error=True)
            return

        # Resolve bandas extras (igual para todas as cenas) / Resolve extra bands (same for all scenes)
        extra_keys = []
        if composition_key == 'CUSTOM':
            extra_keys = (getattr(self, '_custom_bands', None) or {}).get('extra', [])
        elif isinstance(composition_key, str) and composition_key.startswith('CUSTOM:'):
            from .rth_catalog import get_custom_compositions
            _cname = composition_key[7:]
            for comp in get_custom_compositions(collection_id):
                if comp.get('name') == _cname:
                    extra_keys = comp.get('extra', [])
                    break

        # Ordena por data — direção controlada pelo checkbox "Mais Recente Primeiro" /
        # Sort by date — direction controlled by the "Newest First" checkbox
        def _date_key(f):
            return (f.get('properties') or {}).get('datetime') or ''
        _chk_nf = getattr(self, '_chk_newest_first', None)
        _newest_first = _chk_nf is not None and _chk_nf.isChecked()
        features_sorted = sorted(features, key=_date_key, reverse=_newest_first)

        coll_label = (collection_id or '').upper()
        use_parallel = getattr(self, '_chk_parallel', None)
        use_parallel = (use_parallel is not None and use_parallel.isChecked())

        self._dl_empty.setVisible(False)

        # Inicializa a fila universal FIFO se ainda não existe /
        # Initialize universal FIFO queue if it doesn't exist yet
        if not hasattr(self, '_dl_queue'):
            self._dl_queue = _DlQueue(
                on_layer_ready=self._on_layer_ready,
                on_tab_update=self._update_dl_tab_label)

        entries = []

        for feature in features_sorted:
            scene_id = str(feature.get('id') or '')[:30]

            if extra_keys:
                # Composição personalizada com bandas extras: empilha tudo em 1 GeoTIFF
                # multi-banda. Custom composition with extra bands: stack into 1 multi-band GeoTIFF.
                stack_bands = tuple(list(bt) + list(extra_keys))
                title = '{}  ·  {}  ·  STACK{}'.format(coll_label, scene_id, len(stack_bands))
                entry = _DlEntry(
                    features=[feature], collection_id=collection_id,
                    composition_key=composition_key, output_dir=output_dir,
                    band_tuple=stack_bands, band_names=list(bt) + list(extra_keys),
                    row=None)
            else:
                title = '{}  ·  {}  ·  {}'.format(coll_label, scene_id, composition_key)
                entry = _DlEntry(
                    features=[feature], collection_id=collection_id,
                    composition_key=composition_key, output_dir=output_dir,
                    band_tuple=bt, band_names=None, row=None)

            row = _DownloadRow(title, self._dl_inner)
            row.row_removed.connect(self._on_dl_row_removed)
            self._dl_layout.insertWidget(0, row)
            self._download_rows.append(row)
            entry.row = row
            entries.append(entry)

        n = len(features_sorted)

        if use_parallel:
            # Modo paralelo: cria e inicia todas as threads imediatamente /
            # Parallel mode: create and start all threads immediately
            for entry in entries:
                thread = DownloadThread(
                    entry.features, entry.collection_id, entry.composition_key,
                    entry.output_dir, band_tuple=entry.band_tuple, band_names=entry.band_names)
                thread.layer_ready.connect(self._on_layer_ready)
                thread.finished_sig.connect(lambda _: self._update_dl_tab_label())
                entry.row.attach_thread(thread)
                thread.start()
        else:
            # Modo sequencial FIFO: enfileira / Sequential FIFO mode: enqueue
            for entry in entries:
                self._dl_queue.enqueue(entry)

        self._update_dl_tab_label()

        # Muda para aba Downloads para o usuário acompanhar / Switch to Downloads tab so user can follow
        self._tab_widget.setCurrentIndex(3)
        self._set_progress(
            '{} cena(s) adicionada(s) à fila. Acompanhe na aba Downloads. / '
            '{} scene(s) added to queue. Follow in the Downloads tab.'.format(n, n))

    def _on_layer_ready(self, path, name, feature):
        """Carrega camada no QGIS — executado na thread principal via sinal Qt / Load layer in QGIS — executed on main thread via Qt signal."""
        # Se já existe camada com o mesmo arquivo no projeto, só recarrega os dados
        # em vez de adicionar duplicata. Acontece em re-downloads do mesmo arquivo.
        # If a layer with the same source already exists in the project, just reload
        # its data instead of adding a duplicate. Happens when re-downloading.
        existing = [
            lyr for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsRasterLayer) and lyr.source() == path
        ]
        if existing:
            for lyr in existing:
                lyr.reload()
            return

        layer = QgsRasterLayer(path, name)
        if layer.isValid():
            assign_crs_from_bbox(layer, feature)
            apply_rgb_renderer(layer)
            QgsProject.instance().addMapLayer(layer)
            collapse_layer(layer)

    def _enqueue_prebuilt_groups(self, groups):
        """Enfileira grupos de DownloadThreads já configuradas (AOI, download inteligente).
        Substitui o antigo _enqueue_dl_groups removido na reescrita da fila.
        Cada item em `groups` pode ser uma lista de threads ou uma tupla (threads, row_líder).
        Queue groups of already-configured DownloadThreads (AOI, smart download).
        Replaces the old _enqueue_dl_groups removed in the queue rewrite.
        Each item in `groups` can be a thread list or a (threads, leader_row) tuple."""
        if not hasattr(self, '_dl_queue'):
            self._dl_queue = _DlQueue(
                on_layer_ready=self._on_layer_ready,
                on_tab_update=self._update_dl_tab_label)
        for item in groups:
            if isinstance(item, tuple):
                threads, row = item
            else:
                threads, row = item, None
            self._dl_queue.enqueue_prebuilt_group(threads, row)

    def _on_dl_row_removed(self, row):
        """Remove a linha da lista interna e da fila de espera (se ainda não iniciou) /
        Remove row from internal list and from wait queue (if not yet started)."""
        if row in self._download_rows:
            self._download_rows.remove(row)
        # Se o item ainda estava aguardando na fila, remove-o /
        # If the item was still waiting in the queue, remove it
        if hasattr(self, '_dl_queue'):
            self._dl_queue.remove_waiting_by_row(row)
        self._update_dl_tab_label()
        if not self._download_rows:
            self._dl_empty.setVisible(True)

    def _update_dl_tab_label(self):
        """Atualiza o texto da aba Downloads com contagem de itens ativos / Update Downloads tab text with active item count."""
        if getattr(self, '_dialog_closing', False):
            return
        active = sum(1 for r in self._download_rows if not r.is_done())
        total  = len(self._download_rows)
        if active:
            label = 'Downloads ● ({})'.format(active)
        elif total:
            label = 'Downloads ({})'.format(total)
        else:
            label = 'Downloads'
        self._tab_widget.setTabText(3, label)

    def _clear_completed_downloads(self):
        """Remove todas as linhas concluídas ou canceladas / Remove all completed or cancelled rows."""
        done = [r for r in self._download_rows if r.is_done()]
        for row in done:
            self._download_rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        self._update_dl_tab_label()
        if not self._download_rows:
            self._dl_empty.setVisible(True)

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
