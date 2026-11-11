# Coletores do Instagram

Usam só a API oficial da Meta (Graph API, Instagram com login do Facebook), pelo app "Goryx Marketing".
Biblioteca padrão do Python, sem dependências.

| Comando | O que coleta | Para onde vai |
|---|---|---|
| `diagnostico` | Confere token, permissões, conta, Página ligada, cota de publicação e acesso às mensagens. Não grava nada | Só o log (status, sem dados) |
| `conta` | Perfil, últimos 25 posts com métricas (alcance, visualizações, salvos, compartilhamentos...) e métricas da conta em 7 dias | `goryx-marketing/data/instagram/conta/AAAA-MM-DD.json` e `-posts.tsv` |
| `concorrentes` | Perfil e últimos 12 posts públicos de cada conta profissional da lista de alvos (Business Discovery) | `goryx-marketing/data/instagram/concorrentes/AAAA-MM-DD-perfis.tsv` e `-posts.tsv`, com as mesmas colunas das abas Perfis e Posts da base de mineração |

Business Discovery só enxerga contas **profissionais** (comercial ou criador). Conta pessoal ou inexistente vira "falha" na contagem, sem parar a coleta.

## Onde ficam os alvos

Nunca aqui. Ou no segredo `ALVOS_JSON` deste repositório (ex.: `["@conta_a", "@conta_b"]`), ou no arquivo `data/instagram/alvos.json` do repositório privado.

## Rodar

- Agendado: todo dia às 07h17 (Brasília), conta + concorrentes.
- Manual: Actions > "Coletar Instagram" > Run workflow > escolha `diagnostico`, `conta`, `concorrentes` ou `tudo`.
- Testes sem rede: `python3 -m unittest discover -s testes -v`.

## Segredos

`IG_ACCESS_TOKEN`, `MARKETING_REPO_TOKEN` (token do GitHub só com escrita no `goryx-marketing`), opcionais `ALVOS_JSON` e `IG_APP_SECRET`. Os IDs da conta (`17841443090285503`) e da Página (`1377556508781330`) são padrão no workflow e podem ser trocados pelas variáveis `IG_USER_ID` e `IG_PAGE_ID`.

O publicador, a caixa de entrada (comentários e mensagens) e as respostas ficam no repositório privado, porque mexem com conteúdo ainda não publicado e com dados de pessoas.
