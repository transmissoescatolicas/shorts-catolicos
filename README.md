# Vídeos católicos automáticos — Transmissões Católicas

Este sistema corre sozinho no GitHub e publica **6 vídeos curtos por dia** (hora de Brasília) no canal *Transmissões Católicas*, para o público do **Brasil** (voz e textos em português do Brasil):

| Hora (Brasília) | Formato | O que faz |
|-------|---------|-----------|
| 06:07 | **Evangelho do Dia** | Lê o Evangelho da Missa do dia (Liturgia Diária, tradução oficial da CNBB) e uma reflexão breve |
| 09:07 | **Santo do Dia** | Conta a vida de um santo do dia, com base na Wikipédia |
| 12:07 | **Palavra do Papa / Igreja no Brasil** | Resume uma publicação do Vatican News, CNBB, Canção Nova, Aleteia ou ACI Digital, com as citações exatas e o link da fonte |
| 15:07 | **Música Sacra** | Uma gravação de música sacra (canto gregoriano, Ave Maria, Mozart, Bach…) com arte sacra |
| 18:07 | **Oração** | Hora da Ave-Maria: uma oração tradicional (Angelus, Pai Nosso, Salve Rainha, Consagração a Nossa Senhora…) narrada com legendas |
| 21:07 | **Música Sacra** | Outra obra de música sacra |

Se um formato não tiver conteúdo novo, o sistema usa outro (Salmo/Leitura do dia, oração, música).

Em cada vídeo: texto escrito pelo **Google Gemini** a partir de fontes reais, voz brasileira (pt-BR), legendas palavra a palavra, e **arte sacra em domínio público** do Wikimedia Commons (pinturas, ícones, vitrais), com os créditos na descrição.

## Direitos de autor (importante)

- A música vem **só** de gravações com licença livre (domínio público, CC0, CC BY, CC BY-SA) do Wikimedia Commons. **Não se usam músicas comerciais** (nem de artistas católicos atuais), para evitar reclamações e avisos de direitos de autor que podem fechar o canal.
- Os diretos/gravações de outros canais (Canção Nova, TV Aparecida, Rede Vida, Vatican Media, Santuário de Fátima…) têm direitos de autor: **não são reutilizados**. O YouTube também desmonetiza canais com "conteúdo reutilizado" (cortes de outros canais com pouco comentário), mesmo com autorização. Das organizações católicas usamos só o **texto** das publicações (resumo próprio, citações curtas e link para a fonte).

## Segredos (Settings → Secrets and variables → Actions)

| Nome | O que é |
|---|---|
| `GEMINI_API_KEY` | Chave do Google AI Studio (projeto *shorts-catolicos*) |
| `YT_CLIENT_ID` / `YT_CLIENT_SECRET` | Cliente OAuth do Google Cloud (projeto *shorts-catolicos*) |
| `YT_REFRESH_TOKEN` | Autorização do canal (OAuth Playground, âmbito `youtube.upload`) |

## Ligar, testar e parar

- **Testar sem publicar:** Actions → *Vídeos católicos* → **Run workflow** (deixa "Publicar" desmarcado). Em **Artifacts** descarregas o vídeo; em **Summary** vês o texto e a descrição.
- **Ligar a publicação automática:** **Run workflow** com **Publicar** e **Ligar a publicação automática** marcados.
- **Parar:** em Actions, cancela a execução "Vídeo automático" que estiver a correr e, em *Vídeos católicos* → ⋯ → **Disable workflow** (senão a vigia volta a ligá-la).

## Personalizar (`config.yaml`)

- **agenda.horarios**: horas e formatos (hora de Brasília; o fuso está em `idioma.fuso`).
- **voz**: `pt-BR-AntonioNeural` (masculina) / `pt-BR-FranciscaNeural` (feminina).
- **musica.pesquisas**: obras de música sacra a procurar.
- **papa.fontes**: sites católicos (RSS) usados no vídeo do meio-dia.
- **oracoes.yaml**: lista de orações (podes acrescentar).
- **youtube.modo**: `publico`, `agendado` ou `privado`.

## Notas

- A IA pode errar: convém ver os vídeos nas primeiras semanas.
- O YouTube limita o número de envios por dia; 6 por dia está bem dentro do limite. Se aparecer `uploadLimitExceeded`, reduz os horários.
- Teste local sem internet: `python catolico.py --teste-offline --formato musica`
