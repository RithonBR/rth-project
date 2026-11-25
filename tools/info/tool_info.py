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
    QLabel, QFrame, QSizePolicy, QTabWidget, QWidget, QTextEdit
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
        self.setMinimumWidth(680)
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
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 20, 20, 20)

        tabs = QTabWidget()
        tabs.addTab(self._build_info_tab(), self.tr(u'Informações / Info'))
        tabs.addTab(self._build_docs_tab(), self.tr(u'Docs do Plugin / Plugin Docs'))
        tabs.addTab(self._build_cite_tab(), self.tr(u'Como citar? / How to cite?'))
        tabs.addTab(self._build_donate_tab(), self.tr(u'Doar / Donate'))
        root.addWidget(tabs)

        btn_close = QPushButton(self.tr(u'Fechar / Close'))
        btn_close.setMinimumHeight(36)
        btn_close.setStyleSheet(
            'QPushButton{background:#eee;color:#333;font-weight:bold;border-radius:5px;}'
            'QPushButton:hover{background:#ddd;}'
        )
        btn_close.clicked.connect(self.close)
        root.addWidget(btn_close)

    def _build_info_tab(self):
        widget = QWidget()
        widget.setAutoFillBackground(True)
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 14, 10, 10)
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
                pixmap.scaled(420, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
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
        lbl_sub.setStyleSheet('font-size:10px; color:#555;')
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
            self.tr(u'Tem sugestões de melhorias? / Have suggestions for improvement?\nEntre em contato! / Get in touch!')
        )
        lbl_msg.setAlignment(Qt.AlignCenter)
        lbl_msg.setStyleSheet(
            'font-size:12px; color:#333; padding:6px;'
            'background:#f0f4ff; border-radius:6px;'
        )
        lbl_msg.setWordWrap(True)
        layout.addWidget(lbl_msg)

        return widget

    def _build_docs_tab(self):
        widget = QWidget()
        widget.setAutoFillBackground(True)
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setAlignment(Qt.AlignTop)

        lbl_title = QLabel(self.tr(u'Documentação do Plugin / Plugin Documentation'))
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:14px; font-weight:bold; color:#1a73e8;')
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            self.tr(
                u'A documentação completa do RTH PROJECT — tutoriais, guias de uso '
                u'e referência de cada ferramenta — está disponível no site oficial.\n\n'
                u'The complete RTH PROJECT documentation — tutorials, usage guides '
                u'and reference for each tool — is available on the official website.'
            )
        )
        lbl_desc.setAlignment(Qt.AlignCenter)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            'font-size:11px; color:#333; padding:10px;'
            'background:#f0f4ff; border-radius:6px;'
        )
        layout.addWidget(lbl_desc)

        btn_docs = self._social_btn(
            u'🌐  Acessar Documentação / Open Documentation',
            '#1a73e8',
            'https://rithon.com.br/pages/rth-project/'
        )
        layout.addWidget(btn_docs)

        layout.addStretch()
        return widget

    def _build_cite_tab(self):
        widget = QWidget()
        widget.setAutoFillBackground(True)
        layout = QVBoxLayout(widget)
        layout.setSpacing(14)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setAlignment(Qt.AlignTop)

        lbl_title = QLabel(self.tr(u'Como citar este plugin / How to cite this plugin'))
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:14px; font-weight:bold; color:#1a73e8;')
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        lbl_intro = QLabel(self.tr(
            u'Se você usou o RTH PROJECT em pesquisas, trabalhos acadêmicos ou relatórios, '
            u'por favor cite o plugin usando um dos formatos abaixo.\n\n'
            u'If you used RTH PROJECT in research, academic work or reports, '
            u'please cite the plugin using one of the formats below.'
        ))
        lbl_intro.setAlignment(Qt.AlignCenter)
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet('font-size:10px; color:#555; padding:4px;')
        layout.addWidget(lbl_intro)

        self._sep(layout)

        _cite_style = (
            'font-size:10px; color:#222; background:#f4f6fb; border-radius:6px; '
            'padding:10px 12px; border:1px solid #dde3ef;'
        )
        _label_style = 'font-size:11px; font-weight:bold; color:#1a73e8; padding-top:4px;'

        # ── ABNT ─────────────────────────────────────────────────────────
        lbl_abnt = QLabel('ABNT')
        lbl_abnt.setStyleSheet(_label_style)
        layout.addWidget(lbl_abnt)

        abnt_text = (
            u'CARDOSO JUNIOR, Luciano dos Santos. '
            u'RTH Project QGIS Agriculture Mapping & ESG Plugin. '
            u'2026. Disponível em: https://github.com/RithonBR/rth-project. '
            u'Acesso em: [data de acesso].'
        )
        txt_abnt = QTextEdit()
        txt_abnt.setReadOnly(True)
        txt_abnt.setPlainText(abnt_text)
        txt_abnt.setFixedHeight(72)
        txt_abnt.setStyleSheet(_cite_style)
        layout.addWidget(txt_abnt)

        # ── APA ───────────────────────────────────────────────────────────
        lbl_apa = QLabel('APA')
        lbl_apa.setStyleSheet(_label_style)
        layout.addWidget(lbl_apa)

        apa_text = (
            u'Cardoso Junior, L. S. (2026). '
            u'RTH Project QGIS Agriculture Mapping & ESG Plugin '
            u'[QGIS Plugin]. GitHub. https://github.com/RithonBR/rth-project'
        )
        txt_apa = QTextEdit()
        txt_apa.setReadOnly(True)
        txt_apa.setPlainText(apa_text)
        txt_apa.setFixedHeight(62)
        txt_apa.setStyleSheet(_cite_style)
        layout.addWidget(txt_apa)

        # ── BibTeX ────────────────────────────────────────────────────────
        lbl_bib = QLabel('BibTeX')
        lbl_bib.setStyleSheet(_label_style)
        layout.addWidget(lbl_bib)

        bibtex_text = (
            u'@software{rthproject2026,\n'
            u'  author  = {Cardoso Junior, Luciano dos Santos},\n'
            u'  title   = {RTH Project QGIS Agriculture Mapping \\& ESG Plugin},\n'
            u'  year    = {2026},\n'
            u'  month   = {2},\n'
            u'  url     = {https://github.com/RithonBR/rth-project}\n'
            u'}'
        )
        txt_bib = QTextEdit()
        txt_bib.setReadOnly(True)
        txt_bib.setPlainText(bibtex_text)
        txt_bib.setFixedHeight(110)
        txt_bib.setStyleSheet(
            'font-size:10px; color:#222; background:#f4f6fb; border-radius:6px; '
            'padding:6px 10px; border:1px solid #dde3ef; font-family:Courier,monospace;'
        )
        layout.addWidget(txt_bib)

        self._sep(layout)

        # ── Botão GitHub ──────────────────────────────────────────────────
        btn_gh = self._social_btn(
            u'⬢  Repositório no GitHub / GitHub Repository',
            '#24292e',
            'https://github.com/RithonBR/rth-project'
        )
        layout.addWidget(btn_gh)

        layout.addStretch()
        return widget

    def _build_donate_tab(self):
        widget = QWidget()
        widget.setAutoFillBackground(True)
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setAlignment(Qt.AlignTop)

        # ── Logo Pix centralizado / Centered Pix logo ────────────────
        pix_path = self._icon_path('Pix.png')
        if os.path.exists(pix_path):
            pix_pixmap = QPixmap(pix_path)
            if not pix_pixmap.isNull():
                lbl_pix_img = QLabel()
                lbl_pix_img.setAlignment(Qt.AlignCenter)
                lbl_pix_img.setPixmap(
                    pix_pixmap.scaled(400, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                layout.addWidget(lbl_pix_img)

        lbl_pix_msg = QLabel(u'é brasileiro? manda um pix pra pagar um café ☕')
        lbl_pix_msg.setAlignment(Qt.AlignCenter)
        lbl_pix_msg.setStyleSheet('font-size:12px; font-weight:bold; color:#32BCAD;')
        layout.addWidget(lbl_pix_msg)

        line_pix = QFrame()
        line_pix.setFrameShape(QFrame.HLine)
        line_pix.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line_pix)

        # ── Título ────────────────────────────────────────────────────
        lbl_title = QLabel(self.tr(u'Apoie o Projeto / Support the Project'))
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet('font-size:15px; font-weight:bold; color:#c0392b;')
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            self.tr(
                u'Este plugin é gratuito e de código aberto.\n'
                u'Se ele te ajudou, considere fazer uma doação\n'
                u'para manter o desenvolvimento ativo!\n\n'
                u'This plugin is free and open-source.\n'
                u'If it helped you, consider donating\n'
                u'to keep development going!'
            )
        )
        lbl_desc.setAlignment(Qt.AlignCenter)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(
            'font-size:11px; color:#333; padding:8px;'
            'background:#fff5f5; border-radius:6px;'
        )
        layout.addWidget(lbl_desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        btn_donate = self._social_btn(
            u'☕  Buy Me a Coffee — buymeacoffee.com/rthproject',
            '#FFDD00',
            'https://buymeacoffee.com/rthproject',
            text_color='#1a1a1a'
        )
        layout.addWidget(btn_donate)

        layout.addStretch()
        return widget

    def _social_btn(self, label, color, url, text_color='white'):
        btn = QPushButton(label)
        btn.setMinimumHeight(36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            'QPushButton{{background:{c};color:{t};font-weight:bold;'
            'font-size:12px;border-radius:5px;}}'
            'QPushButton:hover{{background:{ch};}}'.format(
                c=color,
                t=text_color,
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
        self._dlg.update()
