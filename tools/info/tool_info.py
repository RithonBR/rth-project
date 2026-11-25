# -*- coding: utf-8 -*-
"""
RTH Informações — diálogo "Sobre" com imagem, redes sociais e contato.
RTH Info — "About" dialog with image, social links and contact.
"""
import os

from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl, QSize
from qgis.PyQt.QtGui import QIcon, QPixmap, QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QSizePolicy
)


class InfoDialog(QDialog):

    def __init__(self, plugin_dir, parent=None):
        super(InfoDialog, self).__init__(parent)
        self.plugin_dir = plugin_dir
        self.setWindowTitle('RTH PROJECT — Informações / Info')
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint |
            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setMinimumWidth(380)
        self.setMaximumWidth(420)
        self._build_ui()

    def tr(self, message):
        return QCoreApplication.translate('InfoDialog', message)

    def _icon_path(self, name):
        return os.path.join(self.plugin_dir, 'icons', name)

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignHCenter)

        # ── Imagem central / Central image ────────────────────────────
        lbl_img = QLabel()
        lbl_img.setAlignment(Qt.AlignCenter)
        img_candidates = ['rth_banner.jpg', 'rth_banner.jpeg', 'rth_banner.png', 'icon.png']
        pixmap = None
        for candidate in img_candidates:
            path = self._icon_path(candidate)
            if os.path.exists(path):
                pixmap = QPixmap(path)
                break
        if pixmap and not pixmap.isNull():
            lbl_img.setPixmap(
                pixmap.scaled(340, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(lbl_img)

        # ── Título / Title ────────────────────────────────────────────
        lbl_title = QLabel('RTH PROJECT')
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:18px; font-weight:bold; color:#1a73e8;')
        layout.addWidget(lbl_title)

        lbl_sub = QLabel('Este plugin nasce como um ideal acadêmico e colaborativo: incentivar a comunidade open source a olhar com mais atenção para a área de sensoriamento remoto. A proposta é democratizar o acesso a ferramentas de qualidade, reduzindo a dependência de soluções proprietárias e de plugins pagos. Ao fortalecer uma base aberta e acessível, buscamos fomentar a inovação, a transparência científica e o desenvolvimento coletivo dentro da geotecnologia.\nThis plugin was conceived as an academic and collaborative initiative aimed at encouraging the open-source community to pay closer attention to the field of remote sensing. Its goal is to democratize access to high-quality tools, reducing reliance on proprietary solutions and paid plugins. By strengthening an open and accessible ecosystem, we aim to foster innovation, scientific transparency, and collective development within geospatial technologies.')
        lbl_sub.setAlignment(Qt.AlignCenter)
        lbl_sub.setWordWrap(True)
        lbl_sub.setStyleSheet('font-size:8px; color:#555;')
        layout.addWidget(lbl_sub)

        lbl_author = QLabel('Luciano dos Santos Cardoso Junior')
        lbl_author.setAlignment(Qt.AlignCenter)
        lbl_author.setStyleSheet('font-size:11px; color:#333; font-style:italic;')
        layout.addWidget(lbl_author)

        self._sep(layout)

        # ── Redes sociais / Social links ──────────────────────────────
        lbl_social = QLabel(self.tr(u'Redes Sociais / Social'))
        lbl_social.setAlignment(Qt.AlignCenter)
        lbl_social.setStyleSheet('font-weight:bold; font-size:11px;')
        layout.addWidget(lbl_social)

        btn_site = self._social_btn(
            u'🌐  rithon.com.br',
            '#1a73e8',
            'https://rithon.com.br/'
        )
        layout.addWidget(btn_site)

        btn_linkedin = self._social_btn(
            u'in  LinkedIn',
            '#0077B5',
            'https://www.linkedin.com/in/luciano-dos-santos-cardoso-junior/'
        )
        layout.addWidget(btn_linkedin)

        btn_instagram = self._social_btn(
            u'◈  Instagram',
            '#C13584',
            'https://www.instagram.com/luciano.scjr/'
        )
        layout.addWidget(btn_instagram)

        self._sep(layout)

        # ── Mensagem de sugestões / Suggestions message ───────────────
        lbl_msg = QLabel(
            self.tr(u'Tem sugestões de melhorias?\nEntre em contato!')
        )
        lbl_msg.setAlignment(Qt.AlignCenter)
        lbl_msg.setStyleSheet(
            'font-size:12px; color:#333; padding:6px;'
            'background:#f0f4ff; border-radius:6px;'
        )
        lbl_msg.setWordWrap(True)
        layout.addWidget(lbl_msg)

        # ── Fechar / Close ────────────────────────────────────────────
        btn_close = QPushButton(self.tr(u'Fechar / Close'))
        btn_close.setMinimumHeight(36)
        btn_close.setStyleSheet(
            'QPushButton{background:#eee;color:#333;font-weight:bold;border-radius:5px;}'
            'QPushButton:hover{background:#ddd;}'
        )
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

    def _social_btn(self, label, color, url):
        btn = QPushButton(label)
        btn.setMinimumHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            'QPushButton{{background:{c};color:white;font-weight:bold;'
            'font-size:12px;border-radius:5px;}}'
            'QPushButton:hover{{background:{ch};}}'.format(
                c=color,
                ch=self._darken(color)
            )
        )
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return btn

    @staticmethod
    def _darken(hex_color):
        """Escurece levemente a cor hex para o estado hover / Slightly darken hex color for hover state."""
        h = hex_color.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        factor = 0.80
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
        return '#{:02x}{:02x}{:02x}'.format(r, g, b)


class InfoTool:
    """Exibe o diálogo de informações do plugin / Displays the plugin info dialog."""

    def __init__(self, iface, plugin_dir):
        self.iface = iface
        self.plugin_dir = plugin_dir
        self._dlg = None

    def run(self):
        if self._dlg is None:
            self._dlg = InfoDialog(self.plugin_dir, self.iface.mainWindow())
        self._dlg.show()
        self._dlg.raise_()
        self._dlg.activateWindow()
