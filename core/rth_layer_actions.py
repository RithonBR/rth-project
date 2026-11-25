# -*- coding: utf-8 -*-
"""
rth_layer_actions — Fachada de re-exportação: virtualização e download de cenas STAC
rth_layer_actions — Re-export facade: STAC scene virtualization and download

Mantém a compatibilidade dos importadores existentes apontando para os módulos especializados.
Keeps backward compatibility for existing importers pointing to the specialized modules.

  rth_virtualizer  → virtualize_scenes
  rth_downloader   → download_scenes

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Re-exporta a função pública de virtualização / Re-export public virtualization function
from .rth_virtualizer import virtualize_scenes

# Declara os símbolos públicos do módulo — suprime aviso de "importação não usada" nos analisadores
# Declare public module symbols — suppresses "unused import" hint in static analyzers
__all__ = ['virtualize_scenes']
