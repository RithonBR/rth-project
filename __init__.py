# -*- coding: utf-8 -*-
"""
RTH PROJECT — Plugin QGIS para Mapeamento Agrícola
RTH PROJECT — QGIS Plugin for Agricultural Mapping

Plugin criado para a comunidade open-source para auxiliar no mapeamento agrícola
de diferentes áreas do mundo. Desenvolvido com Plugin Builder 3 e Claude Agent
como assistente, reunindo ferramentas utilizadas ao longo da vida profissional do autor.

Plugin created for the open-source community to assist in agricultural mapping
of different areas of the world. Developed with Plugin Builder 3 and Claude Agent
as assistant, gathering tools used throughout the author's professional life.

Início do desenvolvimento / Development start: 2025-06-14
Autor / Author: Rithon (lucianoufscagve@gmail.com)

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3

Este script inicializa o plugin, tornando-o visível ao QGIS.
This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Ponto de entrada do QGIS — carrega e instancia a classe principal do plugin / QGIS entry point — loads and instantiates the main plugin class.

    :param iface: Instância da interface do QGIS / QGIS interface instance.
    :type iface: QgsInterface
    """
    # Importa o módulo de carregamento dinâmico de arquivos / Import dynamic file loading module
    import importlib.util
    # Importa o módulo de sistema de arquivos / Import file system module
    import os

    # Obtém o diretório onde este __init__.py está localizado / Get the directory where this __init__.py is located
    plugin_dir = os.path.dirname(__file__)
    # Monta o caminho para o arquivo principal do plugin (nome com espaço) / Build path to main plugin file (name with space)
    module_path = os.path.join(plugin_dir, 'RTH PROJECT.py')
    # Cria a spec do módulo a partir do caminho do arquivo / Create module spec from file path
    spec = importlib.util.spec_from_file_location('rthproject_module', module_path)
    # Instancia o módulo a partir da spec / Instantiate module from spec
    module = importlib.util.module_from_spec(spec)
    # Executa o módulo para carregar suas definições / Execute module to load its definitions
    spec.loader.exec_module(module)
    # Obtém a classe principal do plugin / Get the main plugin class
    rth_cls = getattr(module, 'rthproject')
    # Retorna uma instância da classe do plugin para o QGIS / Return an instance of the plugin class to QGIS
    return rth_cls(iface)
