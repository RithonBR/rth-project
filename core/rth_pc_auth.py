# -*- coding: utf-8 -*-
"""
rth_pc_auth — Assinatura de URLs do Planetary Computer via SAS token
rth_pc_auth — Planetary Computer URL signing via SAS token

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

# Biblioteca padrão para requisições HTTP / Standard library for HTTP requests
import urllib.request
# Biblioteca padrão para codificação de parâmetros de URL / Standard library for URL parameter encoding
import urllib.parse
# Biblioteca padrão para leitura de JSON / Standard library for JSON parsing
import json

# Endpoint público de assinatura do Planetary Computer / Planetary Computer public signing endpoint
_PC_SIGN_URL = 'https://planetarycomputer.microsoft.com/api/sas/v1/sign'
# Domínio Azure que indica asset hospedado no Planetary Computer / Azure domain indicating PC-hosted asset
_PC_BLOB_DOMAIN = 'blob.core.windows.net'


def is_pc_href(href):
    """Verifica se a URL é um asset hospedado no Azure do Planetary Computer / Check if URL is an Azure-hosted Planetary Computer asset.

    :param href: URL do asset / asset URL
    :returns: True se for do PC, False caso contrário / True if PC, False otherwise
    :rtype: bool
    """
    # Assets do PC ficam em *.blob.core.windows.net / PC assets are at *.blob.core.windows.net
    return _PC_BLOB_DOMAIN in href


def sign_pc_href(href):
    """Solicita uma URL assinada (SAS token) para um asset do Planetary Computer / Request a signed URL (SAS token) for a Planetary Computer asset.

    :param href: URL original do asset / original asset URL
    :returns: URL assinada pronta para uso, ou a original em caso de falha / signed URL ready to use, or original on failure
    :rtype: str
    """
    try:
        # Codifica a URL do asset como parâmetro de query / Encode asset URL as query parameter
        params = urllib.parse.urlencode({'href': href})
        # Monta a requisição GET ao endpoint de assinatura / Build GET request to signing endpoint
        req = urllib.request.Request(
            '{}?{}'.format(_PC_SIGN_URL, params),
            headers={'Accept': 'application/json'},
        )
        # Valida o esquema da URL antes de abrir / Validate URL scheme before opening
        if not req.full_url.startswith(('https://', 'http://')):
            raise ValueError('URL scheme not permitted: {}'.format(req.full_url))
        # Timeout curto — o serviço de assinatura é rápido / Short timeout — signing service is fast
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            # Resposta: {"href": "url_assinada", "msft:expiry": "..."} / Response: {"href": "signed_url", "msft:expiry": "..."}
            signed = json.loads(resp.read().decode('utf-8'))
            return signed.get('href', href)
    except Exception:
        # Em caso de falha retorna a URL original / On failure return the original URL
        return href


# Mapeamento bucket → região AWS para evitar redirect 301 que quebra byte-range do vsicurl
# Bucket → AWS region mapping to avoid 301 redirect that breaks vsicurl byte-range requests
_S3_BUCKET_REGIONS = {
    'usgs-landsat':   'us-west-2',   # USGS Landsat Collection 2 / USGS Landsat Collection 2
    'sentinel-cogs':  'us-west-2',   # Sentinel-2 COGs / Sentinel-2 COGs
    'cop-dem-glo-30': 'eu-central-1',# Copernicus DEM 30m / Copernicus DEM 30m
    'naip-analytic':  'us-west-2',   # NAIP imagery / NAIP imagery
}


def resolve_s3_href(href):
    """Converte URL s3:// para HTTPS pública acessível via vsicurl / Convert s3:// URL to public HTTPS accessible via vsicurl.

    Usa endpoint regional quando o bucket é conhecido para evitar redirect 301 que quebra
    as requisições byte-range necessárias para leitura de COGs via GDAL vsicurl.
    Uses regional endpoint when bucket is known to avoid 301 redirect that breaks
    byte-range requests required for COG reading via GDAL vsicurl.

    Exemplo / Example:
      s3://usgs-landsat/collection02/... → https://usgs-landsat.s3.us-west-2.amazonaws.com/collection02/...

    :param href: URL no formato s3:// / URL in s3:// format
    :returns: URL HTTPS equivalente com endpoint regional / equivalent HTTPS URL with regional endpoint
    :rtype: str
    """
    # Remove o prefixo 's3://' e separa bucket do caminho / Strip 's3://' prefix and split bucket from path
    without_prefix = href[len('s3://'):]
    slash_idx      = without_prefix.find('/')
    if slash_idx == -1:
        # Apenas o bucket sem caminho / Bucket only without path
        return 'https://{}.s3.amazonaws.com/'.format(without_prefix)
    bucket = without_prefix[:slash_idx]
    key    = without_prefix[slash_idx + 1:]
    # Usa endpoint regional se o bucket for conhecido / Use regional endpoint if bucket is known
    region = _S3_BUCKET_REGIONS.get(bucket)
    if region:
        return 'https://{}.s3.{}.amazonaws.com/{}'.format(bucket, region, key)
    # Fallback: endpoint global (pode causar redirect) / Fallback: global endpoint (may cause redirect)
    return 'https://{}.s3.amazonaws.com/{}'.format(bucket, key)


def resolve_href(href):
    """Retorna a URL pronta para uso: assina se for do PC, converte S3, ou retorna diretamente / Return ready-to-use URL: sign if PC, convert S3, or return as-is.

    :param href: URL do asset / asset URL
    :returns: URL resolvida / resolved URL
    :rtype: str
    """
    # Assina automaticamente se detectar domínio Azure do PC / Auto-sign if PC Azure domain detected
    if is_pc_href(href):
        return sign_pc_href(href)
    # Converte URL s3:// para HTTPS público (Element84 Landsat) / Convert s3:// to public HTTPS (Element84 Landsat)
    if href.startswith('s3://'):
        return resolve_s3_href(href)
    return href
