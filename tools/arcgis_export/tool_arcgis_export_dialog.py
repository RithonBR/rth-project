# -*- coding: utf-8 -*-
"""
Diálogo RTH Exportar para ArcGIS — estilo DEM/PRODES com log em tempo real.
"""
import os

from qgis.PyQt.QtCore import QCoreApplication, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QProgressBar, QFileDialog,
    QFrame, QCheckBox, QTextEdit
)


class ArcGISExportDialog(QDialog):

    export_requested = pyqtSignal(dict)

    def __init__(self, iface, parent=None):
        super(ArcGISExportDialog, self).__init__(parent)
        self.iface = iface
        self.setWindowTitle('RTH Exportar para ArcGIS / Export to ArcGIS')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(520)
        self._build_ui()

    def tr(self, message):
        return QCoreApplication.translate('ArcGISExportDialog', message)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # ── Cabeçalho / Header ─────────────────────────────────────────
        lbl_title = QLabel('RTH Exportar para ArcGIS / Export to ArcGIS')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:13px; font-weight:bold;')
        layout.addWidget(lbl_title)

        lbl_sub = QLabel(
            self.tr(u'Exporta camadas vetoriais para File Geodatabase (.gdb)  ·  '
                    u'Rasters como GeoTIFF  ·  Nomes sanitizados para ArcGIS')
        )
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setStyleSheet('color:#666; font-size:10px;')
        lbl_sub.setWordWrap(True)
        layout.addWidget(lbl_sub)

        self._sep(layout)

        # ── Diretório de saída / Output directory ──────────────────────
        lbl_out = QLabel(self.tr(u'Diretório de Saída / Output Directory'))
        lbl_out.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_out)

        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText(
            self.tr(u'Selecione a pasta de saída / Select output folder...'))
        dir_row.addWidget(self.edit_dir)
        btn_browse = QPushButton('...')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(btn_browse)
        layout.addLayout(dir_row)

        lbl_name = QLabel(self.tr(u'Nome da GDB / GDB Name  (opcional — deixe em branco para usar o nome do projeto)'))
        lbl_name.setStyleSheet('font-size:10px; color:#555;')
        layout.addWidget(lbl_name)

        self.edit_gdb_name = QLineEdit()
        self.edit_gdb_name.setPlaceholderText(
            self.tr(u'Ex: Fazenda_Santa_Rosa  (sem espaços nem acentos)'))
        layout.addWidget(self.edit_gdb_name)

        self._sep(layout)

        # ── Opções / Options ───────────────────────────────────────────
        lbl_opts = QLabel(self.tr(u'Opções / Options'))
        lbl_opts.setStyleSheet('font-weight:bold;')
        layout.addWidget(lbl_opts)

        self.chk_selected = QCheckBox(
            self.tr(u'Exportar apenas camadas selecionadas no painel / Only panel-selected layers'))
        self.chk_raster = QCheckBox(
            self.tr(u'Incluir camadas raster (exportadas como GeoTIFF) / Include raster layers (as GeoTIFF)'))
        self.chk_sld = QCheckBox(
            self.tr(u'Exportar simbologia como SLD / Export symbology as SLD'))
        self.chk_report = QCheckBox(
            self.tr(u'Gerar relatório TXT com instruções / Generate TXT report with instructions'))

        self.chk_raster.setChecked(True)
        self.chk_sld.setChecked(True)
        self.chk_report.setChecked(True)

        layout.addWidget(self.chk_selected)
        layout.addWidget(self.chk_raster)
        layout.addWidget(self.chk_sld)
        layout.addWidget(self.chk_report)

        self._sep(layout)

        # ── Botão Run / Run button ─────────────────────────────────────
        self.btn_run = QPushButton(self.tr(u'▶  Exportar para ArcGIS / Export to ArcGIS'))
        self.btn_run.setMinimumHeight(42)
        self.btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;font-weight:bold;font-size:13px;border-radius:5px;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;}'
        )
        self.btn_run.clicked.connect(self._on_run)
        layout.addWidget(self.btn_run)

        # ── Status + progresso / Status + progress ─────────────────────
        self.lbl_status = QLabel('')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet('font-size:10px; color:#333;')
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        layout.addWidget(self.progress_bar)

        self._sep(layout)

        # ── Log ────────────────────────────────────────────────────────
        lbl_log = QLabel(self.tr(u'Log'))
        lbl_log.setStyleSheet('font-weight:bold; font-size:10px;')
        layout.addWidget(lbl_log)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(180)
        self.txt_log.setStyleSheet(
            'font-family: Consolas, monospace; font-size: 10px; background: #f8f8f8;'
        )
        layout.addWidget(self.txt_log)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr(u'Selecione a pasta de saída / Select output folder'),
            self.edit_dir.text() or os.path.expanduser('~')
        )
        if folder:
            self.edit_dir.setText(folder)

    def _on_run(self):
        params = {
            'out_dir':         self.edit_dir.text().strip(),
            'gdb_name':        self.edit_gdb_name.text().strip(),
            'only_selected':   self.chk_selected.isChecked(),
            'include_raster':  self.chk_raster.isChecked(),
            'export_sld':      self.chk_sld.isChecked(),
            'generate_report': self.chk_report.isChecked(),
        }
        self.txt_log.clear()
        self.set_busy(True)
        self.export_requested.emit(params)

    # ------------------------------------------------------------------
    # API pública / Public API
    # ------------------------------------------------------------------

    def set_busy(self, busy):
        self.btn_run.setEnabled(not busy)
        self.btn_run.setText(
            self.tr(u'Exportando... / Exporting...')
            if busy else
            self.tr(u'▶  Exportar para ArcGIS / Export to ArcGIS')
        )

    def set_progress(self, value, maximum, msg=''):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(True)
        if msg:
            self.lbl_status.setStyleSheet('font-size:10px; color:#333;')
            self.lbl_status.setText(msg)

    def log(self, msg):
        self.txt_log.append('<span style="color:#1a1a1a;">{0}</span>'.format(
            msg.replace('<', '&lt;').replace('>', '&gt;')))
        self._scroll_log()

    def log_warn(self, msg):
        self.txt_log.append('<span style="color:#b87800;">⚠ {0}</span>'.format(
            msg.replace('<', '&lt;').replace('>', '&gt;')))
        self._scroll_log()

    def log_error(self, msg):
        self.txt_log.append('<span style="color:#cc0000;">✗ {0}</span>'.format(
            msg.replace('<', '&lt;').replace('>', '&gt;')))
        self._scroll_log()

    def _scroll_log(self):
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())
