#!/usr/bin/env python3
"""EPG unificado + playlist IPTV-org com IDs corrigidos automaticamente.

Preserva as fontes XMLTV/Pluto e gera um M3U derivado com canais e URLs
originais, mas com tvg-id equivalente ao ID primário do EPG.
"""
import argparse
import copy
import gzip
import html
import re
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TV = 'https://xmltvfr.fr/xmltv/xmltv.xml.gz'
PLUTO = 'https://i.mjh.nz/PlutoTV/fr.xml.gz'
PLAYLIST = 'https://iptv-org.github.io/iptv/languages/fra.m3u'

# Equivalências verificadas com o catálogo público do XMLTV Fr.
# Não aproximamos versões com programação potencialmente distinta.
EQUIVALENCIAS = {
    'TV5MondeAfrica.fr': 'TV5MondeAfrique.fr',
    'TV5MondeAsia.fr': 'TV5MondeAsie.fr',
    'TV5MondePacific.fr': 'TV5MondePacifique.fr',
    'TV5MondeLatinAmerica.fr': 'TV5MondeAmeriqueLatine.fr',
    'TV5MondeStyle.fr': 'TV5Style.fr',
}
# Os identificadores regionais de France 3 usam um padrão diferente em IPTV-org.
REGIOES_FRANCE3 = {
    'National': 'France3.fr',
    'ParisIledeFrance': 'France3ParisIdF.fr',
    'Corse': 'France3CorseViaStella.fr',
    'CotedAzur': 'France3CotedAzur.fr',
    'PaysdelaLoire': 'France3PaysDeLaLoire.fr',
    'NordPasdeCalais': 'France3NordPasDeCalais.fr',
    'NouvelleAquitaine': 'France3NouvelleAquitaine.fr',
    'LanguedocRoussillon': 'France3Languedoc.fr',
    'BasseNormandie': 'France3BasseNormandie.fr',
    'HauteNormandie': 'France3HauteNormandie.fr',
}

# Apenas diferenças de qualidade de imagem são equivalentes.
# @Arabic, @English, @French e variantes regionais NÃO são mescladas.
QUALIDADES = {'SD', 'HD', 'FHD', 'UHD', '4K', '8K', '720P', '1080P', '2160P'}
ID_M3U = re.compile(r'(\btvg-id\s*=\s*)(["\'])([^"\']+)(["\'])', re.IGNORECASE)


def abrir_url(url, timeout=90):
    pedido = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 EPG-Frances-Compativel/2.0',
        'Accept': '*/*',
    })
    return urllib.request.urlopen(pedido, timeout=timeout)


def baixar(url, destino):
    total = 0
    with abrir_url(url) as resposta, destino.open('wb') as arquivo:
        while bloco := resposta.read(1024 * 1024):
            total += len(bloco)
            if total > 80 * 1024 * 1024:
                raise ValueError('Fonte compactada excede 80 MB: ' + url)
            arquivo.write(bloco)
    with destino.open('rb') as arquivo:
        if total < 100 or arquivo.read(2) != b'\x1f\x8b':
            raise ValueError('A fonte não retornou um XMLTV .gz válido: ' + url)
    print(f'Baixado: {url} ({total / 1048576:.1f} MB)', flush=True)


def ler_ids_m3u(texto):
    """Lê apenas metadados EXTINF; não baixa nenhum endereço de streaming."""
    if not texto.lstrip('\ufeff\r\n ').startswith('#EXTM3U'):
        raise ValueError('Playlist IPTV-org não começa por #EXTM3U.')
    ids = set()
    for linha in texto.splitlines():
        if linha.startswith('#EXTINF:'):
            encontrado = ID_M3U.search(linha)
            if encontrado:
                ids.add(encontrado.group(3).strip())
    if len(ids) < 10:
        raise ValueError('Playlist IPTV-org devolveu poucos tvg-id; atualização cancelada.')
    return ids


def obter_playlist(url):
    limite = 15 * 1024 * 1024
    with abrir_url(url, timeout=60) as resposta:
        dados = resposta.read(limite + 1)
    if len(dados) > limite:
        raise ValueError('Playlist excede 15 MB.')
    texto = dados.decode('utf-8-sig', errors='replace')
    ids = ler_ids_m3u(texto)
    print(f'Playlist: {len(ids)} identificadores distintos ({url})', flush=True)
    return texto, ids


def elementos(arquivo_gz, tipo):
    """Lê os filhos de <tv> por streaming para limitar o consumo de memória."""
    with gzip.open(arquivo_gz, 'rb') as arquivo:
        raiz, nivel = None, 0
        for evento, item in ET.iterparse(arquivo, events=('start', 'end')):
            if evento == 'start':
                nivel += 1
                if nivel == 1:
                    raiz = item
                    if item.tag != 'tv':
                        raise ValueError('Raiz XMLTV inválida: ' + str(arquivo_gz))
            else:
                if nivel == 2:
                    if item.tag == tipo:
                        yield item
                    raiz.clear()
                nivel -= 1


def identificar_equivalente(id_m3u, ids_existentes):
    """Encontra correspondência unívoca e segura com um ID XMLTV existente."""
    if id_m3u in ids_existentes:
        return None  # Já casa exatamente; não criar alias.
    principal, separador, variante = id_m3u.partition('@')
    if principal == 'France3.fr' and separador:
        if variante.upper() in QUALIDADES and 'France3.fr' in ids_existentes:
            return 'France3.fr'
        nome = REGIOES_FRANCE3.get(variante, 'France3' + variante + '.fr')
        if nome in ids_existentes:
            return nome
        return None
    if separador and variante.upper() not in QUALIDADES:
        return None  # Não misturar idiomas, países ou regiões.
    nome = EQUIVALENCIAS.get(principal, principal)
    if nome in ids_existentes:
        return nome
    # Aceitar diferença de maiúsculas/minúsculas somente se não houver ambiguidade.
    candidatos = [canal for canal in ids_existentes if canal.casefold() == nome.casefold()]
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def preparar_playlist(texto_m3u, ids_existentes, destino):
    """Gera playlist com os mesmos streams, substituindo SOMENTE tvg-id seguro.

    NÃO modifica urls, diretivas de cabeçalho ou opções de reprodução.
    Nunca cria correspondências por semelhança aproximada de nomes.
    """
    if not texto_m3u.lstrip('\ufeff\r\n ').startswith('#EXTM3U'):
        raise ValueError('Playlist recebida não é M3U válida.')
    linhas = []
    ajustados = {}
    matches = set()
    presentes = 0
    for linha in texto_m3u.splitlines(keepends=True):
        if linha.startswith('#EXTINF:'):
            resultado = ID_M3U.search(linha)
            if resultado:
                id_antigo = resultado.group(3)
                presentes += 1
                alvo = id_antigo if id_antigo in ids_existentes else identificar_equivalente(id_antigo, ids_existentes)
                if alvo:
                    matches.add(alvo)
                    if alvo != id_antigo:
                        ajustados[id_antigo] = alvo
                        linha = linha[:resultado.start(3)] + alvo + linha[resultado.end(3):]
        linhas.append(linha)
    if presentes < 10:
        raise ValueError('Playlist recebida tem menos de 10 canais com tvg-id.')
    temporario = destino.with_suffix('.m3u.tmp')
    temporario.write_text(''.join(linhas), encoding='utf-8')
    temporario.replace(destino)
    return ajustados, presentes, len(matches)


def copiar_com_atributo(item, atributo, valor):
    copia = copy.deepcopy(item)
    copia.set(atributo, valor)
    return copia


def mesclar(fontes, pasta_saida, ids_playlist=None, texto_playlist=None):
    """Combina os XMLTVs e adiciona os IDs usados pela playlist, quando seguros."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / 'epg.xml.gz'
    temporario = pasta_saida / 'epg.xml.gz.tmp'
    permitidos = [set() for _ in fontes]
    origens = {}
    canais = []
    qt_programas_originais = [0] * len(fontes)
    qt_programas_alias = 0
    ids_playlist = ids_playlist or set()
    try:
        with temporario.open('wb') as bruto, gzip.GzipFile(fileobj=bruto, mode='wb', compresslevel=6, mtime=0) as saida:
            saida.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            saida.write(b'<tv generator-info-name="XMLTV Fr + Pluto TV / IPTV-org">\n')
            # 1: canais originais; a primeira fonte prevalece em IDs duplicados.
            for i, fonte in enumerate(fontes):
                for item in elementos(fonte, 'channel'):
                    id_canal = item.get('id')
                    if not id_canal or id_canal in origens:
                        continue
                    origens[id_canal] = i
                    permitidos[i].add(id_canal)
                    canais.append((id_canal, ET.tostring(item, encoding='utf-8')))
            if any(not ids for ids in permitidos):
                raise ValueError('Uma das fontes não retornou canais exclusivos válidos.')

            # 2: localizar diferenças de IDs M3U, sem substituir os originais.
            alias_por_original = defaultdict(list)
            for id_m3u in sorted(ids_playlist):
                original = identificar_equivalente(id_m3u, origens)
                if original:
                    alias_por_original[original].append(id_m3u)
            # Construir playlist com os IDs CANÔNICOS, não os alias, para o iPlayTV.
            ajustes = {}
            quantidade_m3u = 0
            correspondencias = 0
            if texto_playlist is not None:
                ajustes, quantidade_m3u, correspondencias = preparar_playlist(
                    texto_playlist, set(origens), pasta_saida / 'playlist.m3u')
            for id_canal, xml_bytes in canais:
                saida.write(xml_bytes + b'\n')
                for alias in alias_por_original.get(id_canal, ()):
                    item = ET.fromstring(xml_bytes)
                    saida.write(ET.tostring(copiar_com_atributo(item, 'id', alias), encoding='utf-8') + b'\n')

            # 3: programas originais + uma cópia para cada alias correspondente.
            for i, fonte in enumerate(fontes):
                for item in elementos(fonte, 'programme'):
                    original = item.get('channel')
                    if original not in permitidos[i]:
                        continue
                    saida.write(ET.tostring(item, encoding='utf-8') + b'\n')
                    qt_programas_originais[i] += 1
                    for alias in alias_por_original.get(original, ()):
                        copia = copiar_com_atributo(item, 'channel', alias)
                        saida.write(ET.tostring(copia, encoding='utf-8') + b'\n')
                        qt_programas_alias += 1
            if any(n == 0 for n in qt_programas_originais):
                raise ValueError('Uma das fontes não retornou programação válida.')
            saida.write(b'</tv>\n')
        temporario.replace(destino)
        total = sum(qt_programas_originais) + qt_programas_alias
        momento = datetime.now(timezone.utc).strftime('%d/%m/%Y às %H:%M UTC')
        pagina = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EPG francês</title>
<style>body{{font:16px system-ui;max-width:700px;margin:3em auto;padding:1em;line-height:1.6}}</style>
</head><body><h1>EPG francês unificado</h1>
<p>Atualizado em: {html.escape(momento)}.</p>
<p>{len(canais)} canais originais, {sum(map(len, alias_por_original.values()))} identificadores adicionais e {total} programas.</p>
<p><a href="epg.xml.gz">EPG XMLTV combinado (.xml.gz)</a></p>
<p><a href="playlist.m3u">Playlist com IDs corrigidos (.m3u)</a></p>
<p>{len(ajustes)} identificadores diferentes corrigidos na playlist, {quantidade_m3u} entradas M3U com tvg-id analisadas.</p>
<p>Playlist de origem: <code>{html.escape(PLAYLIST)}</code>. Os endereços de transmissão são preservados.</p>
<p>As variantes linguísticas e regionais não são confundidas com outros canais.</p>
</body></html>'''
        (pasta_saida / 'index.html').write_text(pagina, encoding='utf-8')
        print(f'Playlist corrigida: {len(ajustes)} tvg-id distintos alterados; {quantidade_m3u} entradas analisadas; {correspondencias} canais XMLTV únicos correspondentes.', flush=True)
        for id_antigo, id_novo in sorted(ajustes.items()):
            if id_antigo.startswith(('TV5MondeEurope.', 'TV5MondeAfrica.', 'France3.fr@Lorraine', 'France3.fr@CotedAzur')):
                print(f'  M3U corrigido: {id_antigo} -> {id_novo}', flush=True)
        print(f'Concluído: {len(canais)} canais originais; '
              f'{sum(map(len, alias_por_original.values()))} aliases; '
              f'{total} programas; arquivo {destino.stat().st_size / 1048576:.1f} MB.', flush=True)
        # Mostra exemplos para depuração no registro do GitHub Actions.
        for original, aliases in sorted(alias_por_original.items()):
            if original.startswith(('France2.', 'TF1.', 'TV5Monde')):
                print(f'  {original} -> {", ".join(aliases)}', flush=True)
        return len(canais) + sum(map(len, alias_por_original.values())), total
    finally:
        temporario.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Combina XMLTV Fr e Pluto TV com IDs de iptv-org')
    parser.add_argument('--url-tv', default=TV)
    parser.add_argument('--url-pluto', default=PLUTO)
    parser.add_argument('--url-playlist', default=PLAYLIST)
    parser.add_argument('--output-dir', type=Path, default=Path('site'))
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='epg-') as pasta:
            fontes = [Path(pasta) / 'tv.xml.gz', Path(pasta) / 'pluto.xml.gz']
            baixar(args.url_tv, fontes[0])
            baixar(args.url_pluto, fontes[1])
            texto_playlist, ids_playlist = obter_playlist(args.url_playlist)
            mesclar(fontes, args.output_dir, ids_playlist, texto_playlist)
        return 0
    except (OSError, ValueError, EOFError, ET.ParseError, UnicodeError) as erro:
        print('ERRO: ' + str(erro), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
