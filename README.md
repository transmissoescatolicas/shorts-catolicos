# Vídeos católicos automáticos — Transmissões Católicas

Este sistema corre sozinho no GitHub e publica **6 vídeos curtos por dia** (hora de Lisboa) no canal *Transmissões Católicas*:

| Hora  | Formato | O que faz |
|-------|---------|-----------|
| 07:07 | **Evangelho do Dia** | Lê o Evangelho da Missa do dia (tradução litúrgica) e uma reflexão breve |
| 10:07 | **Santo do Dia** | Conta a vida de um santo do dia, com base na Wikipédia |
| 13:07 | **Palavra do Papa / Igreja Hoje** | Resume uma notícia do Vatican News, Agência Ecclesia ou Santuário de Fátima, com as citações exatas |
| 16:07 | **Música Sacra** | Uma gravação de música sacra (canto gregoriano, Ave Maria, Mozart, Bach…) com arte sacra |
| 19:07 | **Oração** | Uma oração tradicional (Pai Nosso, Salve Rainha, orações de Fátima, Angelus…) narrada com legendas para rezar junto |
| 22:07 | **Música Sacra** | Outra obra de música sacra |

Se um formato não tiver conteúdo novo, o sistema usa outro (Salmo/Leitura do dia, oração, música).

Em cada vídeo: texto escrito pelo **Google Gemini** a partir de fontes reais, voz portuguesa (pt-PT), legendas palavra a palavra, e **arte sacra em domínio público** do Wikimedia Commons (pinturas, ícones, vitrais), com os créditos na descrição.

## Direitos de autor (importante)

- A música vem **só** de gravações com licença livre (domínio público, CC0, CC BY, CC BY-SA) do Wikimedia Commons. **Não se usam músicas comerciais** (nem de artistas católicos atuais), para evitar reclamações e avisos de direitos de autor que podem fechar o canal.
- Os diretos/gravações de outros canais (por exemplo, missas do Santuário de Fátima) também têm direitos: não são reutilizados.

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

- **agenda.horarios**: horas e formatos (hora de Lisboa).
- **voz**: `pt-PT-DuarteNeural` (masculina) / `pt-PT-RaquelNeural` (feminina).
- **musica.pesquisas**: obras de música sacra a procurar.
- **oracoes.yaml**: lista de orações (podes acrescentar).
- **youtube.modo**: `publico`, `agendado` ou `privado`.

## Notas

- A IA pode errar: convém ver os vídeos nas primeiras semanas.
- O YouTube limita o número de envios por dia; 6 por dia está bem dentro do limite. Se aparecer `uploadLimitExceeded`, reduz os horários.
- Teste local sem internet: `python catolico.py --teste-offline --formato musica`
