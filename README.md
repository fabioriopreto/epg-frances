# EPG francês unificado — iPlayTV (Apple TV)

Combine automaticamente os dois guias XMLTV em um único arquivo compactado, hospedado gratuitamente no GitHub Pages.

**Fontes escolhidas:**

- TV francesa — guia completo: `https://xmltvfr.fr/xmltv/xmltv.xml.gz`
- Pluto TV França: `https://i.mjh.nz/PlutoTV/fr.xml.gz`

## Instalação pelo navegador, sem programar

1. Entre em [github.com](https://github.com/) e crie uma conta gratuita, caso ainda não tenha.
2. Clique no sinal **+** no alto da página → **New repository**. Use o nome exato `epg-frances`, marque **Public** e clique em **Create repository**. Deixe desmarcada a opção de criar README automaticamente.
3. Descompacte este ZIP. Na página do repositório vazio, clique em **uploading an existing file** (ou **Add file → Upload files**). Envie `mesclar_epg.py` e `README.md` (não envie o ZIP fechado). Clique em **Commit changes**.
4. Abra **Settings → Pages** e selecione **GitHub Actions** em **Build and deployment → Source**.
5. Volte a **Code → Add file → Create new file**. No nome do arquivo, digite `.github/workflows/atualizar-epg.yml`. Abra esse mesmo arquivo da pasta descompactada em um editor de texto, copie todo seu conteúdo e cole no editor do GitHub. Escolha **Commit changes** na branch `main`.
6. Abra **Actions → Atualizar EPG francês** e espere a execução ficar com um sinal verde. Se não iniciar, clique em **Run workflow** para executar manualmente.
7. Seu endereço definitivo será:

   `https://SEU-USUARIO.github.io/epg-frances/epg.xml.gz`

   Troque `SEU-USUARIO` pelo login real do GitHub (sem @). Para confirmar a última atualização, abra `https://SEU-USUARIO.github.io/epg-frances/`. A primeira publicação pode demorar alguns minutos.
8. No iPlayTV da Apple TV, configure o campo de EPG XMLTV da sua playlist existente com esse endereço. Sua lista M3U continua a mesma.

## Se preferir usar o m3u4u

Na tela **EPG Settings**, escolha **EPG URL** e cole o **endereço combinado do GitHub Pages**. Não insira os dois endereços originais: o campo do m3u4u aceita apenas um link e não faz a mesclagem.

## Como funciona

- Atualização diária, aproximadamente às **07:17 UTC / 04:17 de Brasília**. GitHub pode atrasar tarefas agendadas.
- O Python lê os EPGs em fluxo, sem carregar ~130 MB de XML descompactado de uma vez.
- Canais da Pluto são acrescentados aos canais do XMLTV Fr, e todos os programas correspondentes são reunidos no mesmo arquivo.
- Em caso de **IDs exatamente iguais** entre as fontes, prevalece a primeira (XMLTV Fr); a grade duplicada da segunda é descartada para evitar conflitos.
- Se ocorrer erro de download ou XML inválido, o processamento falha: a última versão publicada no GitHub Pages é preservada.

### Canal sem programação?

A mesclagem preserva os identificadores originais. O `tvg-id` de cada canal da sua playlist M3U precisa corresponder ao `id` desse canal no XMLTV. Se não corresponder, pode ser necessário ajustar o mapeamento na playlist, no próprio player ou em um editor de M3U. Ter ambos os guias num arquivo não garante, por si só, o mapeamento automático.

### Erros comuns

- **404 na URL**: confira `Settings → Pages → Source: GitHub Actions`, a execução verde e o endereço completo com seu usuário e o nome correto do repositório.
- **Falha na execução**: abra **Actions**, clique na execução vermelha e consulte a etapa com erro. Pode ter sido uma indisponibilidade temporária de alguma fonte; execute novamente mais tarde.
- **Sem atualização após muito tempo**: em repositórios públicos sem atividade, o GitHub pode suspender workflows agendados após 60 dias de inatividade. Reative-os na aba **Actions**.

A conta GitHub Free oferece GitHub Pages em repositórios públicos. Não publique sua lista M3U privada, senhas ou dados pessoais no repositório.

## Conteúdo do pacote

- `mesclar_epg.py`: programa responsável pela combinação.
- `.github/workflows/atualizar-epg.yml`: atualização diária e hospedagem automática.
- `tests/test_mesclar_epg.py`: testes locais opcionais (`python -m unittest discover -s tests -v`).

Não é necessário instalar Python nem deixar o computador ligado se você utilizar o GitHub Actions.
