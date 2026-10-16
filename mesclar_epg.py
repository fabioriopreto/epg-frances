#!/usr/bin/env python3
"""Une o guia XMLTV Fr completo e o da Pluto TV França, sem dependências."""
import argparse
import gzip
import html
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

TV = 'https://xmltvfr.fr/xmltv/xmltv.xml.gz'
PLUTO = 'https://i.mjh.nz/PlutoTV/fr.xml.gz'


def baixar(url, destino):
    pedido = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 XMLTV-EPG-Merge/1.0'})
    total = 0
    with urllib.request.urlopen(pedido, timeout=90) as resposta, destino.open('wb') as arquivo:
        while bloco := resposta.read(1024 * 1024):
            total += len(bloco)
            if total > 80 * 1024 * 1024:
                raise ValueError('Fonte compactada excede 80 MB: ' + url)
            arquivo.write(bloco)
    with destino.open('rb') as arquivo:
        if total < 100 or arquivo.read(2) != b'\x1f\x8b':
            raise ValueError('A fonte não retornou um XMLTV .gz válido: ' + url)
    print(f'Baixado: {url} ({total / 1048576:.1f} MB)', flush=True)


def elementos(arquivo_gz, tipo):
    """Lê filhos de <tv> em fluxo; descarta itens processados da memória."""
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


def mesclar(fontes, pasta_saida):
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / 'epg.xml.gz'
    temporario = pasta_saida / 'epg.xml.gz.tmp'
    permitidos = [set() for _ in fontes]
    conhecidos = set()
    qt_canais, qt_programas = 0, [0] * len(fontes)
    try:
        with temporario.open('wb') as bruto, gzip.GzipFile(fileobj=bruto, mode='wb', compresslevel=6, mtime=0) as saida:
            saida.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            saida.write(b'<tv generator-info-name="XMLTV Fr + Pluto TV France">\n')
            # Primeiro canais; depois programas. IDs duplicados: prevalece a primeira fonte.
            for i, fonte in enumerate(fontes):
                for item in elementos(fonte, 'channel'):
                    id_canal = item.get('id')
                    if not id_canal or id_canal in conhecidos:
                        continue
                    conhecidos.add(id_canal)
                    permitidos[i].add(id_canal)
                    saida.write(ET.tostring(item, encoding='utf-8') + b'\n')
                    qt_canais += 1
            if any(not ids for ids in permitidos):
                raise ValueError('Uma das fontes não retornou canais exclusivos válidos.')
            for i, fonte in enumerate(fontes):
                for item in elementos(fonte, 'programme'):
                    if item.get('channel') not in permitidos[i]:
                        continue
                    saida.write(ET.tostring(item, encoding='utf-8') + b'\n')
                    qt_programas[i] += 1
            if any(n == 0 for n in qt_programas):
                raise ValueError('Uma das fontes não retornou programação válida.')
            saida.write(b'</tv>\n')
        temporario.replace(destino)
        q = sum(qt_programas)
        momento = datetime.now(timezone.utc).strftime('%d/%m/%Y às %H:%M UTC')
        pagina = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>EPG francês</title>
<style>body{{font:16px system-ui;max-width:700px;margin:3em auto;padding:1em;line-height:1.6}}</style>
</head><body><h1>EPG francês unificado</h1>
<p>Atualizado em: {html.escape(momento)}.</p>
<p>{qt_canais} canais e {q} programas.</p>
<p><a href="epg.xml.gz">EPG XMLTV combinado (.xml.gz)</a></p>
<p>Copie o endereço do link acima para o iPlayTV. A lista M3U não é modificada.</p>
<p>A associação depende da compatibilidade dos identificadores <code>tvg-id</code> e <code>channel id</code>.</p>
</body></html>'''
        (pasta_saida / 'index.html').write_text(pagina, encoding='utf-8')
        print(f'Concluído: {qt_canais} canais; {q} programas; {destino.stat().st_size / 1048576:.1f} MB.', flush=True)
        return qt_canais, q
    finally:
        temporario.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Combina dois EPGs franceses para iPlayTV')
    parser.add_argument('--url-tv', default=TV)
    parser.add_argument('--url-pluto', default=PLUTO)
    parser.add_argument('--output-dir', type=Path, default=Path('site'))
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='epg-') as pasta:
            fontes = [Path(pasta) / 'tv.xml.gz', Path(pasta) / 'pluto.xml.gz']
            baixar(args.url_tv, fontes[0])
            baixar(args.url_pluto, fontes[1])
            mesclar(fontes, args.output_dir)
        return 0
    except (OSError, ValueError, EOFError, ET.ParseError) as erro:
        print('ERRO: ' + str(erro), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
