# goryx-coleta

Coletores de dados **públicos** do motor de marketing da Goryx. Este repositório é público: aqui fica só código.

## Regras (não negociáveis)

1. **Nenhum dado coletado entra aqui.** Os coletores gravam direto no destino privado (planilha "Goryx — Base de mineração" no Drive ou o repositório privado `goryx-marketing`).
2. **Nenhuma lista de alvos, concorrente ou estratégia no código.** Os alvos vêm de um segredo (`ALVOS_JSON`) ou do repositório privado.
3. **Log limpo:** os coletores imprimem só contagens e status, nunca o conteúdo coletado.
4. **Disparo só por agendamento ou manual.** Nunca por pull request de terceiros.
5. **Chaves só nos segredos do GitHub** (Settings > Secrets and variables > Actions).
6. **Só fontes e meios legítimos:** API oficial ou página pública, volume baixo, nada que imite login (skill `construir-ferramenta-propria`).
7. **Este repositório é o próprio projeto de coleta:** cada workflow roda um coletor deste repositório, com volume baixo.

## Coletores

| Coletor | Fonte | Status |
|---|---|---|
| `instagram_business_discovery` | API oficial do Instagram (Meta) | Aguardando conta profissional da Goryx e app da Meta (fila F03) |
