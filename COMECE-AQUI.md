# Comece aqui: niche-finder no GitHub Codespaces

Este é um fork do [niche-finder](https://github.com/pandich93/youtube-niche-finder) (licença MIT), com a configuração pronta para rodar no **GitHub Codespaces**: você não precisa instalar nada no computador.

## 1. Coloque a sua chave do YouTube como segredo (uma vez só)

1. Entre em **https://github.com/settings/codespaces**.
2. Em **Codespaces secrets**, clique em **New secret**.
3. Em **Name**, escreva `YOUTUBE_API_KEY`. Em **Value**, cole a sua chave da YouTube Data API v3.
4. Em **Repository access**, escolha este repositório e clique em **Add secret**.

A chave fica guardada no GitHub como segredo: ela não aparece no código nem vai para o repositório.

Sem a chave, o painel abre mesmo assim, só que com **dados de demonstração**.

## 2. Abra o Codespace

1. Na página deste repositório, clique no botão verde **Code**, depois na aba **Codespaces** e em **Create codespace on main**.
2. Na primeira vez, a montagem leva uns **5 a 10 minutos**: ela instala o Docker, baixa o banco de dados e monta o programa. Nas próximas vezes, abre em cerca de 1 minuto.
3. Quando terminar, o painel abre sozinho numa aba nova. Se não abrir, clique na aba **PORTS**, embaixo, e no globo 🌐 da porta **8080**.

## 3. Use

- O painel está em **inglês** (ou russo). Para ler em português, clique com o botão direito na página e escolha **Traduzir para o português**.
- Para começar a coletar dados de verdade, vá em **Data** e colete um nicho ou um canal. Depois as outras telas vão se enchendo.
- Telas mais úteis para o Rétrovisage:
  - **Language gaps**: formatos que estouraram numa língua e ainda não existem em outra;
  - **Outlier channels** e **Viral videos**: canais pequenos que estouraram;
  - **Where to enter**: nota de 0 a 100 para cada nicho;
  - **Idea check**: diz se uma ideia de vídeo está livre ou já foi feita.

## Bom saber

- **O histórico só é gravado enquanto o Codespace está ligado.** O Codespaces desliga sozinho depois de uns 30 minutos sem uso. Os dados ficam salvos, mas as medições param enquanto ele está desligado. Para um histórico contínuo, o programa precisaria rodar num computador que fica sempre ligado.
- **Horas grátis:** o GitHub dá uma cota mensal grátis de Codespaces (cerca de 60 horas nesta máquina de 2 núcleos). Para não gastar à toa, **pare o Codespace** quando terminar: em **https://github.com/codespaces**, clique nos três pontinhos e em **Stop codespace**.
- **Cota do YouTube:** 10.000 unidades por dia. O painel mostra quanto sobra, no canto de baixo à esquerda.
- **Pôs a chave depois de criar o Codespace?** No terminal do Codespace, rode:
  ```bash
  bash .devcontainer/setup.sh && bash .devcontainer/start.sh
  ```

## O que este fork muda

Só acrescenta a pasta `.devcontainer/` (configuração do Codespaces) e este arquivo. O resto é o projeto original, que continua sendo de quem fez. Veja o [LICENSE](LICENSE).
