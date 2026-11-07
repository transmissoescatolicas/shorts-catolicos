"""Vídeos católicos automáticos (YouTube Shorts) para o canal "Transmissões Católicas".

Formatos: evangelho do dia, santo do dia, oração, música sacra, palavra do Papa / notícia
da Igreja e leitura (salmo ou 1.ª leitura) do dia.

Uso:
  python catolico.py                      # cria e publica (formato conforme o horário do config.yaml)
  python catolico.py --formato santo      # força um formato
  python catolico.py --sem-upload         # só cria o vídeo (pasta saida/)
  python catolico.py --teste-offline      # vídeo de demonstração sem internet nem chaves
"""
import argparse
import asyncio
import calendar
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import agenda

# ======================================================================
# UTIL
# ======================================================================
RAIZ = Path(__file__).resolve().parent
FONTES_DIR = RAIZ / "assets" / "fonts"
HISTORICO = RAIZ / "data" / "historico.json"
LISBOA = ZoneInfo("Europe/Lisbon")
FORMATOS = ["evangelho", "santo", "oracao", "musica", "papa", "leitura"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
UA_WIKI = "TransmissoesCatolicasBot/1.0 (https://github.com/transmissoescatolicas/shorts-catolicos)"

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

STOP = set("""
a o as os um uma uns umas de do da dos das em no na nos nas num numa por para pelo pela pelos
pelas com sem sob sobre ao aos à às e ou que se é são foi era ser ter tem têm mais menos como após
the of and in on at to for with by from painting pintura
""".split())


def log(msg: str) -> None:
    print(msg, flush=True)


def agora_lx() -> datetime:
    return datetime.now(LISBOA)


def data_extenso(d: datetime) -> str:
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]}"


def carregar_config() -> dict:
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def carregar_oracoes() -> list:
    with open(RAIZ / "oracoes.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def carregar_historico() -> list:
    try:
        return json.loads(HISTORICO.read_text(encoding="utf-8"))
    except Exception:
        return []


def guardar_historico(hist: list) -> None:
    HISTORICO.parent.mkdir(parents=True, exist_ok=True)
    HISTORICO.write_text(json.dumps(hist[-600:], ensure_ascii=False, indent=1), encoding="utf-8")


def limpar_html(texto: str) -> str:
    texto = re.sub(r"<br\s*/?>", "\n", texto or "", flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    return re.sub(r"[ \t\r\f\v]+", " ", texto).strip()


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", texto)


def tokens(texto: str) -> set:
    return {p[:6] for p in normalizar(texto).split() if len(p) > 2 and p not in STOP}


def duracao_media(caminho) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(caminho)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def correr(cmd: list, cwd=None, timeout=None) -> None:
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(map(str, cmd[:6]))}...\n{r.stderr[-2500:]}")


def resumo_github(texto: str) -> None:
    destino = os.environ.get("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def usados(historico: list, campo: str, n: int = 400) -> set:
    out = set()
    for h in historico[-n:]:
        v = h.get(campo)
        if isinstance(v, list):
            out.update(v)
        elif v:
            out.add(v)
    return out


# ======================================================================
# FONTES (licença OFL, descarregadas na primeira execução)
# ======================================================================
FONTES = {
    "Montserrat-SemiBold.ttf": ("https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-SemiBold.ttf", None),
    "Montserrat-ExtraBold.ttf": ("https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-ExtraBold.ttf", None),
    "Cinzel-Bold.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf", 700),
    "PlayfairDisplay-Bold.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf", 700),
    "PlayfairDisplay-Italic.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf", 500),
}


def garantir_fontes() -> None:
    FONTES_DIR.mkdir(parents=True, exist_ok=True)
    for nome, (url, peso) in FONTES.items():
        destino = FONTES_DIR / nome
        if destino.exists() and destino.stat().st_size > 10000:
            continue
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if peso is None:
            destino.write_bytes(r.content)
            continue
        var = FONTES_DIR / ("var_" + nome)
        var.write_bytes(r.content)
        try:   # fonte variável -> instância estática com o peso pedido (para o ffmpeg/libass e o Pillow)
            from fontTools.ttLib import TTFont
            from fontTools.varLib import instancer
            f = TTFont(str(var))
            instancer.instantiateVariableFont(f, {"wght": peso}, inplace=True)
            # nome de família único (ex.: "TC PlayfairDisplay-Italic"), para o libass não trocar Bold por Italic
            familia = "TC " + nome.rsplit(".", 1)[0]
            tabela = f["name"]
            for rec in list(tabela.names):
                if rec.nameID in (16, 17, 21, 22, 25):
                    tabela.removeNames(nameID=rec.nameID)
            for nid, valor in ((1, familia), (2, "Regular"), (4, familia), (6, familia.replace(" ", "-"))):
                tabela.setName(valor, nid, 3, 1, 0x409)
                tabela.setName(valor, nid, 1, 0, 0)
            if "OS/2" in f:
                f["OS/2"].fsSelection = (f["OS/2"].fsSelection & ~0b1100001) | 0b1000000   # "Regular"
            f.save(str(destino))
        except Exception as e:
            log(f"  Aviso: não consegui fixar o peso de {nome} ({type(e).__name__}); uso a fonte variável")
            shutil.copy(var, destino)
        var.unlink(missing_ok=True)


def _fonte(nome: str, tamanho: int):
    return ImageFont.truetype(str(FONTES_DIR / nome), tamanho)


# ======================================================================
# IA (Google Gemini)
# ======================================================================
URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"


def sistema(cfg: dict) -> str:
    variante = cfg.get("idioma", {}).get("variante", "português de Portugal")
    return (
        f"És o editor do canal católico de YouTube «{cfg['canal']['nome']}» (vídeos curtos). "
        f"Escreves sempre em {variante} correto e natural (em Portugal: 'rezar', 'equipa', 'facto', 'ecrã', "
        "'tu'/'vós', nunca 'você'), com reverência, calor humano e fidelidade à doutrina da Igreja Católica. "
        "Nunca inventas factos, datas, milagres, números nem citações: usas só os textos fornecidos e "
        "conhecimento consolidado da tradição católica. Não fazes política partidária nem polémica, "
        "não fazes promessas de curas ou milagres, e não pedes dinheiro."
    )


def _extrair_json(texto: str):
    texto = texto.strip()
    texto = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        if m:
            return json.loads(m.group(0))
        raise


_MODELOS_EM_FALHA = set()


def chamar_gemini(prompt: str, cfg: dict, esquema: dict | None = None) -> dict:
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("Falta o segredo GEMINI_API_KEY.")
    modelos = cfg["ia"]["modelos"]
    ultimo_erro = ""
    for modelo in modelos:
        if modelo in _MODELOS_EM_FALHA and modelo != modelos[-1]:
            continue
        usar_esquema = esquema is not None
        for tentativa in range(4):
            corpo = {
                "systemInstruction": {"parts": [{"text": sistema(cfg)}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
            }
            if usar_esquema:
                corpo["generationConfig"]["responseSchema"] = esquema
            try:
                r = requests.post(URL_GEMINI.format(modelo=modelo), json=corpo, timeout=(15, 120),
                                  headers={"x-goog-api-key": chave, "Content-Type": "application/json"})
            except requests.RequestException as e:
                ultimo_erro = f"{modelo}: {type(e).__name__}"
                log(f"  {ultimo_erro} (sem resposta)")
                if tentativa >= 1:
                    _MODELOS_EM_FALHA.add(modelo)
                    break
                time.sleep(5)
                continue
            if r.status_code == 200:
                dados = r.json()
                try:
                    partes = dados["candidates"][0]["content"]["parts"]
                    texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
                    log(f"  IA: {modelo}")
                    return _extrair_json(texto)
                except Exception as e:
                    ultimo_erro = f"resposta inesperada: {e} {str(dados)[:300]}"
                    time.sleep(3)
                    continue
            ultimo_erro = f"{modelo} HTTP {r.status_code}: {r.text[:300]}"
            log(f"  {ultimo_erro}")
            if r.status_code == 400 and usar_esquema:
                usar_esquema = False
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                if tentativa >= 1:
                    _MODELOS_EM_FALHA.add(modelo)
                    break
                time.sleep(10)
                continue
            break
    raise RuntimeError(f"Gemini falhou em todos os modelos. Último erro: {ultimo_erro}")


def _obj(props: dict, obrig: list | None = None) -> dict:
    return {"type": "OBJECT", "properties": props, "required": obrig or list(props)}


S = {"type": "STRING"}
LS = {"type": "ARRAY", "items": {"type": "STRING"}}
I = {"type": "INTEGER"}

REGRAS_COMUNS = """
- "titulo_youtube": título para o YouTube (máx. 90 caracteres), apelativo mas sereno, sem MAIÚSCULAS a gritar e sem emojis.
- "descricao": 2 a 4 frases para a descrição do YouTube (o sistema junta depois as fontes e os créditos).
- "hashtags": 3 a 5 hashtags sem o símbolo # (ex.: "Evangelho", "FéCatólica", "Fátima").
- "tags": 6 a 12 palavras-chave para o YouTube.
- "buscas_imagens": 5 pesquisas EM INGLÊS para encontrar obras de arte sacra (pinturas, ícones, vitrais, estátuas, igrejas) no Wikimedia Commons que ilustrem o tema. Curtas e concretas (ex.: "Parable of the Prodigal Son painting", "Saint Francis of Assisi Giotto", "Fatima sanctuary basilica"). A primeira deve ser a mais específica.
"""

ESQ_COMUM = {"titulo_youtube": S, "descricao": S, "hashtags": LS, "tags": LS, "buscas_imagens": LS}


# ======================================================================
# FONTES DE CONTEÚDO
# ======================================================================
EVANGELIZO = "https://feed.evangelizo.org/v2/reader.php"


def evangelizo(data: datetime, tipo: str, lingua: str, conteudo: str | None = None) -> str:
    params = {"date": data.strftime("%Y%m%d"), "type": tipo, "lang": lingua}
    if conteudo:
        params["content"] = conteudo
    r = requests.get(EVANGELIZO, params=params, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def _limpar_leitura(texto: str) -> str:
    texto = limpar_html(texto)
    # tira a nota de tradução e o convite para a newsletter
    texto = re.split(r"\n\s*(Tradução litúrgica|Para receber todas|©|Copyright)", texto)[0]
    texto = texto.replace("«", "").replace("»", "").replace("“", "").replace("”", "")
    texto = re.sub(r"\s*\n\s*", " ", texto)
    return re.sub(r"\s{2,}", " ", texto).strip()


def leitura_do_dia(data: datetime, lingua: str, conteudo: str) -> dict | None:
    """conteudo: GSP (evangelho), FR (1.ª leitura), PS (salmo), SR (2.ª leitura)."""
    try:
        texto = _limpar_leitura(evangelizo(data, "reading", lingua, conteudo))
        ref = limpar_html(evangelizo(data, "reading_lt", lingua, conteudo)).strip().rstrip(".")
    except Exception as e:
        log(f"  Evangelho Quotidiano ({conteudo}): {type(e).__name__} {str(e)[:80]}")
        return None
    if len(texto.split()) < 15:
        return None
    return {"texto": texto, "ref": ref, "fonte": "Evangelho Quotidiano (evangelhoquotidiano.org)",
            "link": "https://www.evangelhoquotidiano.org"}


def titulo_liturgico(data: datetime, lingua: str) -> str:
    try:
        return limpar_html(evangelizo(data, "liturgic_t", lingua)).strip()
    except Exception:
        return ""


def santos_do_dia(data: datetime, lingua: str) -> str:
    try:
        return limpar_html(evangelizo(data, "saint", lingua))
    except Exception as e:
        log(f"  Santos do dia: {type(e).__name__}")
        return ""


ABREV = {"mateus": "Mt", "marcos": "Mc", "lucas": "Lc", "joão": "Jo", "joao": "Jo"}


def ref_curta(ref: str) -> str:
    """'Evangelho segundo São Lucas 16,9-15' -> 'Lc 16,9-15'."""
    m = re.search(r"S(?:ão|\.)\s+(Mateus|Marcos|Lucas|João|Joao)\s+([\d,.\-–; ab]+)", ref, re.I)
    if m:
        return f"{ABREV[m.group(1).lower()]} {m.group(2).strip()}"
    return ref


def evangelista(ref: str) -> str:
    m = re.search(r"S(?:ão|\.)\s+(Mateus|Marcos|Lucas|João|Joao)", ref, re.I)
    return f"São {m.group(1).capitalize().replace('Joao', 'João')}" if m else ""


def wikipedia(termo: str, lingua: str = "pt", max_chars: int = 4500) -> dict | None:
    api = f"https://{lingua}.wikipedia.org/w/api.php"
    try:
        r = requests.get(api, params={"action": "query", "list": "search", "srsearch": termo, "srlimit": 3,
                                      "format": "json"}, headers={"User-Agent": UA_WIKI}, timeout=20)
        r.raise_for_status()
        res = r.json().get("query", {}).get("search", [])
        if not res:
            return None
        titulo = res[0]["title"]
        r = requests.get(api, params={"action": "query", "prop": "extracts", "explaintext": 1, "titles": titulo,
                                      "format": "json", "redirects": 1}, headers={"User-Agent": UA_WIKI}, timeout=20)
        r.raise_for_status()
        paginas = r.json().get("query", {}).get("pages", {})
        texto = next(iter(paginas.values())).get("extract", "")
    except Exception as e:
        log(f"  Wikipédia '{termo}': {type(e).__name__}")
        return None
    texto = re.split(r"\n==+\s*(Referências|Ligações externas|Bibliografia|Ver também|References|See also)", texto)[0]
    texto = re.sub(r"\n{2,}", "\n", texto).strip()
    if len(texto) < 300:
        return None
    return {"titulo": titulo, "texto": texto[:max_chars],
            "link": f"https://{lingua}.wikipedia.org/wiki/{titulo.replace(' ', '_')}"}


def _data_rss(entry):
    for campo in ("published_parsed", "updated_parsed"):
        st = entry.get(campo)
        if st:
            return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
    return None


def noticias_igreja(fontes: list, horas_max: int) -> list:
    import feedparser
    limite = datetime.now(timezone.utc) - timedelta(hours=horas_max)
    itens = []
    for f in fontes:
        try:
            r = requests.get(f["url"], headers={"User-Agent": UA}, timeout=25)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            log(f"  ✗ {f['nome']}: {type(e).__name__}")
            continue
        n = 0
        for e in feed.entries[:40]:
            d = _data_rss(e)
            if d and d < limite:
                continue
            titulo = limpar_html(e.get("title", ""))
            if not titulo or not e.get("link"):
                continue
            itens.append({"fonte": f["nome"], "titulo": titulo, "link": e["link"],
                          "resumo": limpar_html(e.get("summary", ""))[:500],
                          "data": d.isoformat() if d else ""})
            n += 1
        log(f"  ✓ {f['nome']}: {n}")
    return itens


def texto_artigo(url: str, max_chars: int = 4000) -> str:
    try:
        import trafilatura
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
        return (trafilatura.extract(r.text, include_comments=False, include_tables=False) or "")[:max_chars]
    except Exception:
        return ""


# ======================================================================
# WIKIMEDIA COMMONS (arte sacra e música com licenças livres)
# ======================================================================
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
LICENCAS_LIVRES = re.compile(r"^(cc0( 1\.0)?|public domain|domínio público|pd([ -].*)?|attribution|"
                             r"cc[ -]by(-sa)?([ -][\d.]+)?( [a-z]{2,3})?)$", re.I)
EXCLUIR_IMG = re.compile(r"wiki(media|pedia|data)|logo|coat of arms|brasão|bras[aã]o|flag|bandeira|\bmap\b|mapa|"
                         r"diagram|signature|assinatura|stamp|selo|coin|moeda|banknote|screenshot|poster|cartaz|"
                         r"protest|manifesta|\bnude\b|\bnu\b|naked|execution|tortur|beheading|decapita|"
                         r"\bQR\b|\bchart\b|gráfico|floor plan|planta", re.I)
EXCLUIR_AUDIO = re.compile(r"^File:LL-|Rohdaten|audiobook|audiolivro|audio ?book|podcast|interview|entrevista|"
                           r"spoken|pronunciation|pronúncia|wikipedia|lecture|palestra|news|ringtone|"
                           r"national anthem|hino nacional|\bmidi\b", re.I)


def _meta(meta: dict, campo: str, n: int = 160) -> str:
    return limpar_html((meta.get(campo) or {}).get("value", ""))[:n]


def commons_procurar(q: str, tipo: str = "imagem", limite: int = 25) -> list:
    filetype = "bitmap" if tipo == "imagem" else "audio"
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": limite,
              "gsrsearch": f"{q} filetype:{filetype}", "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata"}
    if tipo == "imagem":
        params["iiurlwidth"] = 1600
    r = requests.get(COMMONS_API, params=params, headers={"User-Agent": UA_WIKI}, timeout=30)
    r.raise_for_status()
    paginas = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    out = []
    for p in paginas:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _meta(meta, "LicenseShortName").strip()
        if not LICENCAS_LIVRES.match(lic) or re.search(r"\b(NC|ND)\b", lic):
            continue
        desc = _meta(meta, "ImageDescription", 300)
        texto = f"{p.get('title', '')} {desc} {_meta(meta, 'ObjectName')}"
        out.append({"titulo": p.get("title", ""), "info": info, "lic": lic, "desc": desc, "texto": texto,
                    "autor": re.sub(r"\s+", " ", _meta(meta, "Artist", 80)) or "autor desconhecido",
                    "url": info.get("descriptionurl", "")})
    return out


ESQ_IMAGENS = _obj({"indices": {"type": "ARRAY", "items": I}})


def obter_imagens(buscas: list, quantidade: int, pasta, historico: list, tema: str, cfg: dict,
                  usar_ia: bool = True) -> list:
    """Arte sacra (domínio público / licenças livres) do Wikimedia Commons para ilustrar o vídeo."""
    ja = usados(historico, "imagens", 300)
    cands, vistos = [], set()
    for q in buscas or []:
        try:
            res = commons_procurar(q, "imagem")
        except Exception as e:
            log(f"  Commons '{q}': {type(e).__name__}")
            continue
        por_busca = 0
        for c in res:
            info = c["info"]
            if c["titulo"] in vistos or c["titulo"] in ja:
                continue
            if info.get("mime") not in ("image/jpeg", "image/png", "image/tiff", "image/webp"):
                continue
            if min(info.get("width", 0), info.get("height", 0)) < 650:
                continue
            if EXCLUIR_IMG.search(c["texto"]):
                continue
            if not (tokens(q) & tokens(c["texto"])):
                continue
            vistos.add(c["titulo"])
            cands.append(c)
            por_busca += 1
            if por_busca >= 6:
                break
    log(f"  Imagens candidatas (Wikimedia Commons): {len(cands)}")
    if not cands:
        return []
    escolhidos = cands[:quantidade]
    if usar_ia and len(cands) > quantidade:
        lista = "\n".join(f"[{i}] {c['titulo'][5:]} — {c['desc'][:140]}" for i, c in enumerate(cands[:40]))
        try:
            res = chamar_gemini(
                f"Vou ilustrar um vídeo católico sobre: {tema}\n\nEscolhe as {quantidade} imagens MAIS adequadas "
                "(arte sacra bonita e reverente, diretamente ligada ao tema; evita fotografias banais, documentos, "
                "pormenores ilegíveis, imagens violentas ou impróprias, e imagens repetidas do mesmo quadro). "
                f"Devolve JSON {{\"indices\": [...]}} pela ordem em que devem aparecer.\n\n{lista}",
                cfg, ESQ_IMAGENS)
            idx = [i for i in res.get("indices", []) if isinstance(i, int) and 0 <= i < len(cands)]
            idx = list(dict.fromkeys(idx))
            if idx:
                escolhidos = [cands[i] for i in idx[:quantidade]]
                if len(escolhidos) < quantidade:
                    escolhidos += [c for c in cands if c not in escolhidos][:quantidade - len(escolhidos)]
        except Exception as e:
            log(f"  Seleção de imagens pela IA falhou ({type(e).__name__}); uso as primeiras")
    fotos = []
    for c in escolhidos:
        try:
            img = requests.get(c["info"].get("thumburl") or c["info"]["url"], headers={"User-Agent": UA_WIKI}, timeout=60)
            img.raise_for_status()
            destino = pasta / f"img_{len(fotos)}.jpg"
            Image.open(__import__("io").BytesIO(img.content)).convert("RGB").save(destino, quality=93)
        except Exception as e:
            log(f"  Não consegui descarregar {c['titulo'][:60]}: {type(e).__name__}")
            continue
        fotos.append({"caminho": destino, "id": c["titulo"], "autor": c["autor"], "licenca": c["lic"],
                      "fonte": "Wikimedia Commons", "url": c["url"]})
    log(f"  Imagens escolhidas: {len(fotos)}")
    return fotos


def _volume_medio(caminho) -> float:
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(caminho), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -99.0


def descarregar_audio(c: dict, destino, max_seg: float) -> float:
    """Descarrega (e corta) uma gravação do Commons para WAV; devolve a duração útil."""
    bruto = destino.with_suffix(".bruto.wav")
    correr(["ffmpeg", "-y", "-v", "error", "-user_agent", UA_WIKI, "-i", c["info"]["url"], "-vn",
            "-t", f"{max_seg + 8:.1f}", "-ac", "2", "-ar", "48000", str(bruto)], timeout=240)
    # tira o silêncio do início
    correr(["ffmpeg", "-y", "-v", "error", "-i", str(bruto), "-af",
            "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.25",
            "-t", f"{max_seg:.1f}", str(destino)], timeout=120)
    bruto.unlink(missing_ok=True)
    return duracao_media(destino)


def candidatos_musica(q: str, cfg: dict, ja: set) -> list:
    mcfg = cfg["musica"]
    try:
        res = commons_procurar(q, "audio", 40)
    except Exception as e:
        log(f"  Commons áudio '{q}': {type(e).__name__}")
        return []
    out = []
    for c in res:
        info = c["info"]
        dur = float(info.get("duration") or 0)
        if c["titulo"] in ja or "midi" in (info.get("mime") or ""):
            continue
        if not (float(mcfg.get("duracao_min_peca", 50)) <= dur <= 1500):
            continue
        if EXCLUIR_AUDIO.search(c["texto"]):
            continue
        if not (tokens(q) & tokens(c["texto"])):
            continue
        c["dur"] = dur
        out.append(c)
    return out


# ======================================================================
# VOZ
# ======================================================================
async def _edge(texto: str, voz: str, velocidade: str, saida):
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=velocidade, boundary="WordBoundary")
    marcas = []
    with open(saida, "wb") as f:
        async for c in com.stream():
            if c["type"] == "audio":
                f.write(c["data"])
            elif c["type"] == "WordBoundary":
                ini = c["offset"] / 1e7
                marcas.append({"texto": c["text"], "ini": ini, "fim": ini + c["duration"] / 1e7})
    return marcas


def _estimar_tempos(texto: str, duracao: float) -> list:
    partes = texto.split()
    pesos = []
    for p in partes:
        w = len(p) + 2
        if re.search(r"[.!?]$", p):
            w += 7
        elif re.search(r"[,;:]$", p):
            w += 3
        pesos.append(w)
    total = sum(pesos) or 1
    escala = (duracao - 0.3) / total
    t, out = 0.15, []
    for p, w in zip(partes, pesos):
        fala = (len(p) + 2) * escala
        out.append({"texto": p, "ini": t, "fim": t + fala})
        t += w * escala
    return out


def alinhar(texto: str, marcas: list) -> list:
    """Passa os tempos da voz (palavra a palavra) para as palavras do texto original, com a pontuação."""
    spans = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", texto)]
    baixo, cursor, pos = texto.lower(), 0, []
    for w in marcas:
        k = baixo.find(w["texto"].lower(), cursor)
        if k == -1 or k - cursor > 120:
            continue
        pos.append((k, w["ini"], w["fim"]))
        cursor = k + len(w["texto"])
    out = []
    for a, b, tok in spans:
        dentro = [p for p in pos if a <= p[0] < b]
        out.append({"texto": tok, "ini": dentro[0][1] if dentro else None, "fim": dentro[-1][2] if dentro else None})
    # preenche as palavras sem tempo com os vizinhos
    for i, w in enumerate(out):
        if w["ini"] is None:
            ant = next((out[j]["fim"] for j in range(i - 1, -1, -1) if out[j]["fim"] is not None), 0.1)
            prox = next((out[j]["ini"] for j in range(i + 1, len(out)) if out[j]["ini"] is not None), ant + 0.4)
            w["ini"], w["fim"] = ant, max(ant + 0.05, prox)
    return out


def sintetizar(texto: str, voz: str, cfg: dict, pasta, nome: str = "narracao", offline: bool = False) -> tuple:
    mp3 = pasta / f"{nome}.mp3"
    vel = cfg["voz"].get("velocidade", "+0%")
    if not offline:
        for tentativa in range(3):
            try:
                marcas = asyncio.run(_edge(texto, voz, vel, mp3))
                dur = duracao_media(mp3)
                if dur > 3:
                    palavras = alinhar(texto, marcas) if len(marcas) >= len(texto.split()) * 0.5 \
                        else _estimar_tempos(texto, dur)
                    log(f"  Voz: {voz} ({dur:.1f}s)")
                    return mp3, palavras, dur
            except Exception as e:
                log(f"  Voz Edge falhou ({type(e).__name__}: {str(e)[:100]}), tentativa {tentativa + 1}")
                time.sleep(3)
        try:
            from gtts import gTTS
            tld = "com.br" if voz.startswith("pt-BR") else "pt"
            gTTS(texto, lang="pt", tld=tld).save(str(mp3))
            rapida = pasta / f"{nome}_r.mp3"
            correr(["ffmpeg", "-y", "-v", "error", "-i", mp3, "-filter:a", "atempo=1.1", rapida])
            dur = duracao_media(rapida)
            log(f"  Voz: gTTS ({dur:.1f}s)")
            return rapida, _estimar_tempos(texto, dur), dur
        except Exception as e:
            log(f"  gTTS falhou ({type(e).__name__})")
    if shutil.which("espeak-ng"):
        wav = pasta / f"{nome}.wav"
        correr(["espeak-ng", "-v", "pt", "-s", "150", "-w", wav, texto])
        dur = duracao_media(wav)
        log(f"  Voz: espeak-ng local ({dur:.1f}s) — só para teste")
        return wav, _estimar_tempos(texto, dur), dur
    if offline:   # sem voz nenhuma: tom suave, só para testar a montagem
        dur = max(6.0, len(texto.split()) * 0.42)
        wav = pasta / f"{nome}.wav"
        correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={dur:.2f}",
                "-af", "volume=0.05", wav])
        return wav, _estimar_tempos(texto, dur), dur
    raise RuntimeError("Não foi possível gerar a narração.")


# ======================================================================
# LEGENDAS (ASS, palavra a palavra)
# ======================================================================
DOURADO = (214, 175, 72, 255)
DOURADO_ESCURO = (150, 112, 30, 255)
ASS_DOURADO = r"&H48AFD6&"     # #D6AF48 em BGR
ASS_BRANCO = r"&HFFFFFF&"
L, A, FPS = 1080, 1920, 30
CAIXA = (40, 520, 1040, 1560)  # zona da imagem (x0, y0, x1, y1)
Y_LEGENDA = 1712

CABECALHO = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Leg,TC PlayfairDisplay-Bold,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,5,2,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

LIGACOES = {"e", "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no", "na", "que",
            "um", "uma", "por", "para", "com", "ao", "à", "se", "nos", "nas", "pelo", "pela", "vos", "nós"}


def _t(seg: float) -> str:
    seg = max(0.0, seg)
    return f"{int(seg // 3600)}:{int(seg % 3600 // 60):02d}:{seg % 60:05.2f}"


def _blocos(palavras: list) -> list:
    blocos, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(w)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        letras = sum(len(x["texto"]) + 1 for x in atual)
        pausa = prox is not None and prox["ini"] - w["fim"] > 0.35
        fim_frase = bool(re.search(r"[.!?;:]$", w["texto"]))
        virgula = bool(re.search(r",$", w["texto"])) and letras >= 14
        if pausa or fim_frase or virgula or prox is None:
            blocos.append(atual)
            atual = []
        elif len(atual) >= 6 or letras >= 30:
            if len(atual) > 1 and atual[-1]["texto"].lower() in LIGACOES:
                blocos.append(atual[:-1])
                atual = [atual[-1]]
            else:
                blocos.append(atual)
                atual = []
    return [b for b in blocos if b]


def _limpo(p: str) -> str:
    return p.replace("\\", "").replace("{", "(").replace("}", ")")


def gerar_ass(palavras: list, caminho, duracao_total: float) -> None:
    palavras = [w for w in palavras if w["texto"].strip()]
    blocos = _blocos(palavras)
    linhas = [CABECALHO]
    for bi, bloco in enumerate(blocos):
        prox_ini = blocos[bi + 1][0]["ini"] if bi + 1 < len(blocos) else duracao_total
        fim_bloco = min(bloco[-1]["fim"] + 0.5, prox_ini)
        textos = [_limpo(x["texto"]) for x in bloco]
        # quebra de linha a meio do bloco (se for comprido)
        quebra = None
        if sum(len(t) + 1 for t in textos) > 19 and len(textos) > 1:
            total, acum, melhor = sum(len(t) + 1 for t in textos), 0, None
            for k, t in enumerate(textos[:-1]):
                acum += len(t) + 1
                d = abs(acum - total / 2)
                if melhor is None or d < melhor[0]:
                    melhor = (d, k)
            quebra = melhor[1]
        for wi, w in enumerate(bloco):
            ini = w["ini"] if wi else max(0.0, w["ini"] - 0.05)
            fim = bloco[wi + 1]["ini"] if wi + 1 < len(bloco) else fim_bloco
            if fim <= ini:
                fim = ini + 0.05
            partes = []
            for k, txt in enumerate(textos):
                partes.append(f"{{\\c{ASS_DOURADO}}}{txt}{{\\c{ASS_BRANCO}}}" if k == wi else txt)
                if k == quebra:
                    partes.append("\\N")
            corpo = " ".join(partes).replace(" \\N ", "\\N")
            anim = r"{\fad(120,0)}" if wi == 0 else ""
            linhas.append(f"Dialogue: 0,{_t(ini)},{_t(fim)},Leg,,0,0,0,,{{\\pos(540,{Y_LEGENDA})}}{anim}{corpo}\n")
    with open(caminho, "w", encoding="utf-8") as f:
        f.writelines(linhas)


# ======================================================================
# GRAFISMO
# ======================================================================
def _quebrar(texto: str, fonte, largura: int, draw) -> list:
    linhas, atual = [], ""
    for p in texto.split():
        teste = f"{atual} {p}".strip()
        if draw.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def _sombra_texto(img, xy, texto, fonte, cor, anchor="la", raio=6):
    s = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(s).text((xy[0] + 2, xy[1] + 4), texto, font=fonte, fill=(0, 0, 0, 220), anchor=anchor)
    img.alpha_composite(s.filter(ImageFilter.GaussianBlur(raio)))
    ImageDraw.Draw(img).text(xy, texto, font=fonte, fill=cor, anchor=anchor)


def _cruz(d, cx, cy, h, cor):
    w = max(2, h // 7)
    d.rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=cor)
    d.rectangle([cx - h // 3, cy - h // 2 + h // 4 - w // 2, cx + h // 3, cy - h // 2 + h // 4 + w // 2], fill=cor)


def camada_grafica(caminho, peca: dict, cfg: dict) -> None:
    """Topo (etiqueta, data, título) e base (rodapé) do vídeo — fica por cima das imagens."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    alfa = Image.new("L", (L, A), 0)
    da = ImageDraw.Draw(alfa)
    for y in range(0, 600):                      # escurece o topo
        da.line([(0, y), (L, y)], fill=int(235 * (1 - y / 600) ** 1.3))
    for y in range(1330, A):                     # escurece a base (legendas)
        da.line([(0, y), (L, y)], fill=int(240 * ((y - 1330) / (A - 1330)) ** 0.9))
    preto = Image.new("RGBA", (L, A), (8, 6, 4, 255))
    preto.putalpha(alfa)
    img.alpha_composite(preto)
    d = ImageDraw.Draw(img)

    # etiqueta dourada + data
    f_tag = _fonte("Cinzel-Bold.ttf", 34)
    etiqueta = (peca.get("etiqueta") or "").upper()[:28]
    tw = d.textlength(etiqueta, font=f_tag)
    x0, y0 = 60, 92
    d.rounded_rectangle([x0, y0, x0 + tw + 92, y0 + 60], radius=30, fill=DOURADO)
    _cruz(d, x0 + 34, y0 + 30, 30, (40, 28, 8, 255))
    d.text((x0 + 60, y0 + 31), etiqueta, font=f_tag, fill=(40, 28, 8, 255), anchor="lm")
    data = peca.get("data_texto") or data_extenso(agora_lx())
    f_data = _fonte("Montserrat-SemiBold.ttf", 28)
    if x0 + tw + 112 + d.textlength(data, font=f_data) < L - 50:
        d.text((x0 + tw + 112, y0 + 31), data, font=f_data, fill=(240, 236, 228, 235), anchor="lm")

    # linha de contexto (ex.: "Lc 16,9-15") + título grande
    y = 186
    topo = (peca.get("titulo_topo") or "").strip()
    if topo:
        for tam_topo in (36, 33, 30, 27, 24):
            f_topo = _fonte("Montserrat-SemiBold.ttf", tam_topo)
            if d.textlength(topo, font=f_topo) <= L - 120:
                break
        while d.textlength(topo, font=f_topo) > L - 120 and len(topo) > 10:
            topo = topo[:-2].rstrip() + "…"
        _sombra_texto(img, (62, y), topo, f_topo, DOURADO)
        y += 56
    titulo = (peca.get("titulo") or "").strip().upper()
    larg = L - 120
    for tam in (78, 72, 66, 60, 54, 48, 44):
        f_tit = _fonte("Cinzel-Bold.ttf", tam)
        linhas = _quebrar(titulo, f_tit, larg, d)
        if len(linhas) <= 3 and y + len(linhas) * int(tam * 1.18) <= CAIXA[1] - 24:
            break
    for linha in linhas[:3]:
        _sombra_texto(img, (60, y), linha, f_tit, (255, 255, 255, 255))
        y += int(tam * 1.18)

    # rodapé
    d = ImageDraw.Draw(img)
    rodape = peca.get("rodape") or f"{cfg['canal']['nome']} · Narração com voz sintética · Arte sacra de domínio público"
    f_rod = _fonte("Montserrat-SemiBold.ttf", 22)
    while d.textlength(rodape, font=f_rod) > L - 80 and len(rodape) > 20:
        rodape = rodape[:-4] + "…"
    d.text((L // 2, A - 58), rodape, font=f_rod, fill=(205, 200, 190, 255), anchor="mm")

    # texto fixo (vídeos de música, sem legendas)
    fixo = (peca.get("texto_ecra") or "").strip()
    if fixo:
        f_fixo = _fonte("PlayfairDisplay-Italic.ttf", 46)
        linhas = _quebrar(fixo, f_fixo, L - 140, d)[:4]
        yy = 1700 - (len(linhas) - 1) * 30
        for linha in linhas:
            _sombra_texto(img, (L // 2, yy), linha, f_fixo, (255, 252, 244, 255), anchor="mm")
            yy += 60
    img.save(caminho)


def _caixa_imagem(caminho_img) -> tuple:
    """Tamanho e posição da imagem dentro da CAIXA (sem cortar a obra)."""
    with Image.open(caminho_img) as im:
        w, h = im.size
    cw, ch = CAIXA[2] - CAIXA[0], CAIXA[3] - CAIXA[1]
    esc = min(cw / w, ch / h)
    fw, fh = int(w * esc) // 2 * 2, int(h * esc) // 2 * 2
    return fw, fh, CAIXA[0] + (cw - fw) // 2, CAIXA[1] + (ch - fh) // 2


def _png_moldura(item: dict, destino, caixa: tuple) -> None:
    """Moldura dourada fina à volta da obra + crédito por baixo."""
    fw, fh, fx, fy = caixa
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    s = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    ImageDraw.Draw(s).rectangle([fx - 6, fy - 2, fx + fw + 6, fy + fh + 12], fill=(0, 0, 0, 150))
    img.alpha_composite(s.filter(ImageFilter.GaussianBlur(14)))
    img.paste((0, 0, 0, 0), (fx, fy, fx + fw, fy + fh))       # a sombra não fica por cima da obra
    d = ImageDraw.Draw(img)
    d.rectangle([fx - 3, fy - 3, fx + fw + 2, fy + fh + 2], outline=DOURADO, width=3)
    if item.get("autor"):
        credito = f"{item['autor']} · {item.get('licenca', '')} · {item.get('fonte', '')}"
        f = _fonte("Montserrat-SemiBold.ttf", 20)
        while d.textlength(credito, font=f) > L - 80 and len(credito) > 20:
            credito = credito[:-4] + "…"
        y = min(fy + fh + 14, CAIXA[3] + 8)
        d.text((L - 38, y + 2), credito, font=f, fill=(0, 0, 0, 200), anchor="ra")
        d.text((L - 40, y), credito, font=f, fill=(225, 220, 210, 255), anchor="ra")
    img.save(destino)


def _fundo_desfocado(caminho_img, destino) -> None:
    im = Image.open(caminho_img).convert("RGB")
    bg = ImageOps.fit(im, (L, A), centering=(0.5, 0.4)).filter(ImageFilter.GaussianBlur(42))
    bg = ImageEnhance.Brightness(bg).enhance(0.38)
    ImageEnhance.Color(bg).enhance(0.8).save(destino, quality=92)


_MOVIMENTOS = [
    ("1+0.07*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),            # aproximar
    ("1.07-0.07*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # afastar
    ("1.07", "(iw-iw/zoom)*on/{n}", "ih/2-(ih/zoom/2)"),                  # esquerda -> direita
    ("1.07", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{n})"),              # baixo -> cima
]
_ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _segmento(item: dict, saida, dur: float, mov: int, pasta, i: int) -> None:
    n = max(2, int(round(dur * FPS)))
    caixa = _caixa_imagem(item["caminho"])
    fw, fh, fx, fy = caixa
    moldura = pasta / f"moldura_{i}.png"
    _png_moldura(item, moldura, caixa)
    base = pasta / f"base_{i}.jpg"
    _fundo_desfocado(item["caminho"], base)
    z, x, y = (s.format(n=n) for s in _MOVIMENTOS[mov % len(_MOVIMENTOS)])
    filtro = (f"[1:v]scale={fw * 2}:{fh * 2}:force_original_aspect_ratio=increase,crop={fw * 2}:{fh * 2},setsar=1,"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={fw}x{fh}:fps={FPS}[fg];"
              f"[0:v][fg]overlay={fx}:{fy}:shortest=1[v0];[v0][2:v]overlay=0:0,format=yuv420p[v]")
    correr(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", base,
            "-i", item["caminho"], "-loop", "1", "-i", moldura, "-filter_complex", filtro,
            "-map", "[v]", "-frames:v", str(n), *_ENC, saida], timeout=900)


def fundo(itens: list, total: float, pasta) -> Path:
    T = 0.7
    # cada imagem fica pelo menos ~5 s no ecrã
    max_itens = max(1, int(total // 5))
    itens = itens[:max_itens]
    durs = [total / len(itens)] * len(itens)
    segs = []
    inicio = random.randint(0, 3)
    for i, (item, d) in enumerate(zip(itens, durs)):
        s = pasta / f"seg_{i}.mp4"
        _segmento(item, s, d + T, inicio + i, pasta, i)
        segs.append(s)
    saida = pasta / "fundo.mp4"
    if len(segs) == 1:
        shutil.copy(segs[0], saida)
        return saida
    entradas, filtros, ant, off = [], [], "[0:v]", 0.0
    for s in segs:
        entradas += ["-i", s]
    for i in range(1, len(segs)):
        off += durs[i - 1]
        rot = f"[x{i}]"
        filtros.append(f"{ant}[{i}:v]xfade=transition=fade:duration={T}:offset={off:.3f}{rot}")
        ant = rot
    correr(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
            "-map", ant, *_ENC, saida], timeout=1200)
    return saida


def fundos_gerados(quantidade: int, pasta) -> list:
    """Fundos (dourado/azul escuro com luz suave) quando não há imagens — também usado no teste offline."""
    paletas = [((18, 14, 40), (120, 86, 30)), ((10, 22, 48), (60, 90, 140)), ((30, 10, 16), (150, 60, 40))]
    out = []
    for i in range(quantidade):
        a, b = paletas[i % len(paletas)]
        w, h = (1200, 1600) if i % 2 == 0 else (1600, 1100)
        img = Image.new("RGB", (w, h))
        px = ImageDraw.Draw(img)
        for y in range(0, h, 4):
            t = y / h
            px.rectangle([0, y, w, y + 4], fill=tuple(int(a[k] * (1 - t) + b[k] * t) for k in range(3)))
        luz = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(luz)
        dl.ellipse([w * 0.25, h * 0.1, w * 0.75, h * 0.6], fill=(255, 230, 170, 70))
        luz = luz.filter(ImageFilter.GaussianBlur(80))
        img = Image.alpha_composite(img.convert("RGBA"), luz).convert("RGB")
        _cruz(ImageDraw.Draw(img), w // 2, int(h * 0.38), int(h * 0.3), (255, 236, 190))
        destino = pasta / f"gerado_{i}.jpg"
        img.save(destino, quality=92)
        out.append({"caminho": destino, "id": None, "autor": None})
    return out


def montar(itens: list, audio, ass, grafico, dur_audio: float, pasta, saida, fundo_musical=None) -> None:
    total = dur_audio + 1.4
    log(f"  A montar vídeo de {total:.1f}s com {len(itens)} imagens")
    bg = fundo(itens, total, pasta)
    fontes_local = pasta / "fonts"
    fontes_local.mkdir(exist_ok=True)
    for f in FONTES_DIR.glob("*.ttf"):
        shutil.copy(f, fontes_local / f.name)
    video = "[0:v][1:v]overlay=0:0" + (f",subtitles={ass.name}:fontsdir=fonts" if ass else "") + ",format=yuv420p[v]"
    entradas = ["-i", bg.name, "-i", grafico.name, "-i", str(audio)]
    if fundo_musical:
        entradas += ["-stream_loop", "-1", "-i", str(fundo_musical)]
        som = (f"[2:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000,apad[voz];"
               f"[3:a]loudnorm=I=-33:TP=-10,aresample=48000,afade=t=in:d=1.5,"
               f"afade=t=out:st={max(0.5, total - 2.5):.2f}:d=2.5[mus];"
               f"[voz][mus]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        som = (f"[2:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,"
               f"afade=t=out:st={max(0.5, total - 3):.2f}:d=3,apad[a]")
    correr(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", video + ";" + som,
            "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(Path(saida).resolve())],
           cwd=pasta, timeout=1500)


# ======================================================================
# FORMATOS
# ======================================================================
def dividir_frases(texto: str) -> list:
    partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ0-9«“\"(])", texto.strip())
    return [p.strip() for p in partes if p.strip()]


def _trecho(frases: list, ini, fim) -> tuple:
    n = len(frases)
    try:
        ini, fim = max(0, int(ini)), min(n - 1, int(fim))
    except (TypeError, ValueError):
        ini, fim = 0, n - 1
    if fim < ini:
        ini, fim = 0, n - 1
    # garante o limite de palavras mesmo que a IA se engane
    while fim > ini and len(" ".join(frases[ini:fim + 1]).split()) > 300:
        fim -= 1
    return " ".join(frases[ini:fim + 1]), not (ini == 0 and fim == n - 1)


def _ja_feito(historico: list, chave: str) -> bool:
    return any(h.get("chave") == chave for h in historico[-80:])


def _completar(peca: dict, res: dict, buscas_extra: list) -> dict:
    for campo in ("descricao", "hashtags", "tags"):
        peca.setdefault(campo, res.get(campo) or ([] if campo != "descricao" else ""))
    peca["buscas_imagens"] = list(dict.fromkeys((res.get("buscas_imagens") or []) + buscas_extra))
    return peca


ESQ_EVANGELHO = _obj({"titulo": S, "inicio": I, "fim": I, "reflexao": S, **ESQ_COMUM})


def formato_evangelho(cfg: dict, historico: list, pasta) -> dict | None:
    hoje = agora_lx()
    chave = f"evangelho:{hoje:%Y-%m-%d}"
    if _ja_feito(historico, chave):
        log("  O Evangelho de hoje já foi publicado.")
        return None
    lingua = cfg["idioma"]["liturgia"]
    ev = leitura_do_dia(hoje, lingua, "GSP")
    if not ev:
        return None
    dia_lit = titulo_liturgico(hoje, lingua)
    frases = dividir_frases(ev["texto"])
    lista = "\n".join(f"[{i}] {f}" for i, f in enumerate(frases))
    res = chamar_gemini(f"""Hoje é {data_extenso(hoje)} ({dia_lit}).
Evangelho do dia — {ev['ref']} — com {len(ev['texto'].split())} palavras, em frases numeradas:
{lista}

Vamos fazer o vídeo «Evangelho do Dia». Devolve JSON com:
- "titulo": frase curta e marcante (máx. 8 palavras) tirada do próprio Evangelho, sem aspas.
- "inicio" e "fim": índices das frases a ler (inclusive). Se o Evangelho tiver até 300 palavras, lê-o todo (0 a {len(frases) - 1}); se for mais longo, escolhe um trecho seguido com no máximo 280 palavras que contenha o essencial.
- "reflexao": reflexão breve (45 a 65 palavras) para viver esta Palavra hoje — calorosa, concreta e fiel ao texto — que termina com uma pequena oração. Não repitas o Evangelho.
{REGRAS_COMUNS}""", cfg, ESQ_EVANGELHO)
    trecho, parcial = _trecho(frases, res.get("inicio"), res.get("fim"))
    evg = evangelista(ev["ref"]) or "São Mateus"
    narr = (f"Evangelho de hoje, {data_extenso(hoje)}. "
            f"{'Do ' if parcial else ''}Evangelho de Nosso Senhor Jesus Cristo segundo {evg}. "
            f"{trecho} Palavra da salvação. {res['reflexao'].strip()}")
    rc = ref_curta(ev["ref"])
    peca = {
        "formato": "evangelho", "chave": chave, "etiqueta": "Evangelho do Dia",
        "titulo_topo": rc + (f" · {dia_lit}" if dia_lit and len(dia_lit) < 42 else ""),
        "titulo": res["titulo"], "narracao": narr,
        "titulo_youtube": f"Evangelho do Dia {hoje:%d/%m} | {res['titulo']} ({rc})",
        "fontes": [{"nome": f"{ev['ref']} — Tradução litúrgica da Bíblia, via {ev['fonte']}", "link": ev["link"]}],
        "rodape": "Tradução litúrgica da Bíblia · evangelhoquotidiano.org · Voz sintética",
        "texto_resumo": trecho,
    }
    return _completar(peca, res, ["Jesus Christ teaching disciples painting", "Christ Pantocrator icon"])


ESQ_LEITURA = _obj({"titulo": S, "inicio": I, "fim": I, "reflexao": S, **ESQ_COMUM})


def _nome_livro(ref: str) -> str:
    nome = re.sub(r"\s+\d.*$", "", ref).strip()
    if re.match(r"(Carta|Primeira|Segunda|Terceira|Profecia|Epístola|Sabedoria)", nome, re.I):
        return f"Leitura da {nome}"
    if re.match(r"Atos", nome, re.I):
        return f"Leitura dos {nome}"
    return f"Leitura do {nome}"


def formato_leitura(cfg: dict, historico: list, pasta) -> dict | None:
    hoje = agora_lx()
    chave = f"leitura:{hoje:%Y-%m-%d}"
    if _ja_feito(historico, chave):
        log("  A leitura de hoje já foi publicada.")
        return None
    lingua = cfg["idioma"]["liturgia"]
    ordem = ["PS", "FR"] if hoje.toordinal() % 2 == 0 else ["FR", "PS"]
    lt, tipo = None, None
    for t in ordem:
        lt = leitura_do_dia(hoje, lingua, t)
        if lt:
            tipo = t
            break
    if not lt:
        return None
    salmo = tipo == "PS"
    frases = dividir_frases(lt["texto"])
    lista = "\n".join(f"[{i}] {f}" for i, f in enumerate(frases))
    res = chamar_gemini(f"""Hoje é {data_extenso(hoje)}.
{'Salmo responsorial' if salmo else 'Primeira leitura'} da Missa de hoje — {lt['ref']} — em frases numeradas:
{lista}

Vamos fazer o vídeo «{'Salmo do Dia' if salmo else 'Leitura do Dia'}». Devolve JSON com:
- "titulo": frase curta e marcante (máx. 8 palavras) tirada do próprio texto, sem aspas.
- "inicio" e "fim": índices das frases a ler (inclusive), no máximo 230 palavras seguidas com o essencial (o texto todo, se couber).
- "reflexao": reflexão breve (40 a 60 palavras) que ajuda a rezar este texto hoje e termina com uma pequena oração.
{REGRAS_COMUNS}""", cfg, ESQ_LEITURA)
    trecho, _ = _trecho(frases, res.get("inicio"), res.get("fim"))
    intro = "Salmo responsorial." if salmo else f"{_nome_livro(lt['ref'])}."
    fecho = "" if salmo else " Palavra do Senhor."
    narr = f"{'Salmo' if salmo else 'Leitura'} do dia, {data_extenso(hoje)}. {intro} {trecho}{fecho} {res['reflexao'].strip()}"
    peca = {
        "formato": "leitura", "chave": chave, "etiqueta": "Salmo do Dia" if salmo else "Leitura do Dia",
        "titulo_topo": lt["ref"][:48], "titulo": res["titulo"], "narracao": narr,
        "titulo_youtube": f"{'Salmo' if salmo else 'Leitura'} do Dia {hoje:%d/%m} | {res['titulo']}",
        "fontes": [{"nome": f"{lt['ref']} — Tradução litúrgica da Bíblia, via {lt['fonte']}", "link": lt["link"]}],
        "rodape": "Tradução litúrgica da Bíblia · evangelhoquotidiano.org · Voz sintética",
        "texto_resumo": trecho,
    }
    return _completar(peca, res, ["Psalms King David harp painting" if salmo else "Old Testament prophet painting",
                                  "Bible manuscript illuminated"])


ESQ_SANTO_ESCOLHA = _obj({"nome": S, "pesquisa_pt": S, "pesquisa_en": S})
ESQ_SANTO = _obj({"titulo": S, "narracao": S, **ESQ_COMUM})


def formato_santo(cfg: dict, historico: list, pasta) -> dict | None:
    hoje = agora_lx()
    chave = f"santo:{hoje:%Y-%m-%d}"
    if _ja_feito(historico, chave):
        log("  O santo de hoje já foi publicado.")
        return None
    lingua = cfg["idioma"]["liturgia"]
    lista = santos_do_dia(hoje, lingua)
    if not lista:
        return None
    recentes = ", ".join(sorted(usados(historico, "santo", 120)))
    escolha = chamar_gemini(f"""Santos e beatos que a Igreja recorda hoje, {data_extenso(hoje)} (lista seguida, separa tu os nomes):
{lista}

Escolhe UM para o vídeo «Santo do Dia»: de preferência um santo (não beato) conhecido e inspirador para o público português, com história documentada. Evita títulos de Nossa Senhora se houver um santo, e evita estes já usados: {recentes or 'nenhum'}.
Devolve JSON: "nome" (como é conhecido em Portugal, ex.: "São Vilibrordo"), "pesquisa_pt" (termo para encontrar o artigo na Wikipédia em português), "pesquisa_en" (o nome em inglês, ex.: "Saint Willibrord").""",
                            cfg, ESQ_SANTO_ESCOLHA)
    wiki = None
    for termo, ling in ((escolha.get("pesquisa_pt"), cfg["idioma"].get("wikipedia", "pt")), (escolha.get("pesquisa_en"), "en")):
        if termo:
            w = wikipedia(termo, ling)
            if w and tokens(w["titulo"]) & tokens(f"{escolha['nome']} {termo}"):
                wiki = w
                break
    if not wiki:
        log(f"  Sem artigo fiável sobre {escolha.get('nome')}; salto o santo do dia.")
        return None
    res = chamar_gemini(f"""Hoje, {data_extenso(hoje)}, a Igreja recorda {escolha['nome']}.
Texto de referência (Wikipédia, «{wiki['titulo']}»):
{wiki['texto']}

Escreve o vídeo «Santo do Dia». Devolve JSON com:
- "narracao": 120 a 160 palavras para ser lidas em voz alta. Começa por "Hoje a Igreja recorda {escolha['nome']}." Conta quem foi, o essencial da sua vida e porque é exemplo para nós hoje. Usa SÓ factos que estão no texto de referência (não inventes milagres, datas nem frases). Termina com "{escolha['nome']}, rogai por nós."
- "titulo": subtítulo curto (máx. 7 palavras) que resume quem foi (ex.: "O apóstolo dos Países Baixos").
{REGRAS_COMUNS}""", cfg, ESQ_SANTO)
    peca = {
        "formato": "santo", "chave": chave, "santo": escolha["nome"], "etiqueta": "Santo do Dia",
        "titulo_topo": escolha["nome"], "titulo": res["titulo"], "narracao": res["narracao"].strip(),
        "titulo_youtube": f"Santo do Dia {hoje:%d/%m} | {escolha['nome']} — {res['titulo']}",
        "fontes": [{"nome": f"Wikipédia — {wiki['titulo']} (CC BY-SA)", "link": wiki["link"]},
                   {"nome": "Santos do dia: Evangelho Quotidiano", "link": "https://www.evangelhoquotidiano.org"}],
    }
    en = escolha.get("pesquisa_en") or escolha["nome"]
    return _completar(peca, res, [f"{en} painting", f"{en} icon", f"{en} statue"])


ESQ_ORACAO = _obj({"introducao": S, **ESQ_COMUM})


def formato_oracao(cfg: dict, historico: list, pasta) -> dict | None:
    oracoes = carregar_oracoes()
    if not oracoes:
        return None
    ultimo = {}
    for i, h in enumerate(historico):
        if h.get("oracao"):
            ultimo[h["oracao"]] = i
    hora = agora_lx().hour
    # ao fim do dia prefere orações da noite / de Fátima; ao meio-dia o Angelus
    def prioridade(o):
        bonus = 0
        if 11 <= hora <= 13 and o["id"] == "angelus":
            bonus = -1000
        return (ultimo.get(o["id"], -1) + bonus, random.random())
    o = sorted(oracoes, key=prioridade)[0]
    texto = re.sub(r"\s+", " ", o["texto"]).strip()
    try:
        res = chamar_gemini(f"""Vamos publicar um vídeo para rezar a oração «{o['titulo']}». Texto da oração:
{texto}

Devolve JSON com:
- "introducao": 25 a 45 palavras ditas antes da oração: contexto breve e verdadeiro (origem, sentido ou quando se reza) e um convite caloroso para rezarmos juntos. Não repitas a oração.
{REGRAS_COMUNS}""", cfg, ESQ_ORACAO)
    except Exception as e:
        log(f"  IA falhou na introdução ({type(e).__name__}); uso uma introdução simples")
        res = {"introducao": f"Rezemos juntos a oração {o['titulo']}.", "descricao": f"Reza connosco: {o['titulo']}.",
               "hashtags": ["Oração", "FéCatólica"], "tags": ["oração", o["titulo"], "católico"], "buscas_imagens": []}
    narr = f"{res['introducao'].strip()} {texto}"
    if len(texto.split()) < 40 and o["id"] != "gloria":
        narr += " Glória ao Pai, ao Filho e ao Espírito Santo. Como era no princípio, agora e sempre. Ámen."
    peca = {
        "formato": "oracao", "oracao": o["id"], "etiqueta": "Oração", "titulo_topo": "Reza connosco",
        "titulo": o["titulo"], "narracao": narr, "voz": cfg["voz"].get("nome_oracao") or cfg["voz"]["nome"],
        "titulo_youtube": f"{o['titulo']} | Reza connosco",
        "fontes": [],
    }
    return _completar(peca, res, list(o.get("imagens", [])))


ESQ_MUSICA = _obj({"indice": I, "titulo": S, "subtitulo": S, "texto_ecra": S, **ESQ_COMUM})


def formato_musica(cfg: dict, historico: list, pasta) -> dict | None:
    mcfg = cfg["musica"]
    ja = usados(historico, "musica", 600)
    ultimo = {}
    for i, h in enumerate(historico):
        if h.get("busca_musica"):
            ultimo[h["busca_musica"]] = i
    pesquisas = sorted(mcfg["pesquisas"], key=lambda p: (ultimo.get(p["q"], -1), random.random()))
    for p in pesquisas[:8]:
        cands = candidatos_musica(p["q"], cfg, ja)
        log(f"  Música '{p['q']}': {len(cands)} gravações livres")
        if not cands:
            continue
        lista = "\n".join(f"[{i}] {c['titulo'][5:]} — {int(c['dur'])} s — {c['lic']} — {c['autor'][:50]} — {c['desc'][:160]}"
                          for i, c in enumerate(cands[:15]))
        res = chamar_gemini(f"""Procuro uma gravação de música sacra católica para um vídeo curto (pesquisa: «{p['q']}»).
Gravações disponíveis (licenças livres, Wikimedia Commons):
{lista}

Escolhe a MELHOR: música sacra ou de inspiração cristã, interpretação completa (coro, órgão, orquestra ou solista), sem fala nem ruído, e que não seja um excerto de poucos segundos nem um ficheiro MIDI. Se nenhuma servir, "indice" = -1.
Devolve JSON com:
- "indice": número da gravação escolhida.
- "titulo": nome da obra e compositor (ex.: "Ave Verum Corpus — W. A. Mozart").
- "subtitulo": máx. 6 palavras (ex.: "Coro e órgão · Música sacra").
- "texto_ecra": 1 ou 2 frases curtas (máx. 22 palavras) sobre o sentido da obra ou do seu texto, para mostrar no ecrã. Sem inventar datas.
{REGRAS_COMUNS}""", cfg, ESQ_MUSICA)
        i = res.get("indice", -1)
        if not isinstance(i, int) or not (0 <= i < len(cands[:15])):
            log("  A IA não achou nenhuma gravação adequada; próxima pesquisa.")
            continue
        c = cands[i]
        destino = pasta / "musica.wav"
        try:
            dur = descarregar_audio(c, destino, float(mcfg.get("duracao_max", 150)))
        except Exception as e:
            log(f"  Não consegui descarregar a gravação: {type(e).__name__} {str(e)[:150]}")
            continue
        vol = _volume_medio(destino)
        if dur < 30 or vol < -42:
            log(f"  Gravação rejeitada (duração {dur:.0f}s, volume {vol:.0f} dB)")
            continue
        log(f"  Música: {c['titulo']} ({dur:.0f}s, {c['lic']})")
        peca = {
            "formato": "musica", "musica": c["titulo"], "busca_musica": p["q"], "etiqueta": "Música Sacra",
            "titulo_topo": res.get("subtitulo", ""), "titulo": res["titulo"], "texto_ecra": res.get("texto_ecra", ""),
            "audio_musica": destino, "dur_musica": dur, "categoria": "10",
            "titulo_youtube": f"{res['titulo']} | Música Sacra",
            "rodape": f"Gravação: {c['autor'][:50]} · {c['lic']} · Wikimedia Commons",
            "credito_musica": {"id": c["titulo"], "autor": c["autor"], "licenca": c["lic"], "url": c["url"]},
            "fontes": [],
        }
        return _completar(peca, res, [p["tema"], "cathedral interior painting", "angels musicians painting"])
    return None


ESQ_PAPA_ESCOLHA = _obj({"id": I, "motivo": S})
ESQ_PAPA = _obj({"etiqueta": S, "titulo": S, "titulo_topo": S, "narracao": S, **ESQ_COMUM})


def formato_papa(cfg: dict, historico: list, pasta) -> dict | None:
    pcfg = cfg.get("papa", {})
    itens = noticias_igreja(pcfg.get("fontes", []), int(pcfg.get("horas_max", 72)))
    ja = usados(historico, "link", 800)
    itens = [i for i in itens if i["link"] not in ja][:45]
    if not itens:
        log("  Sem notícias novas da Igreja.")
        return None
    recentes = [h.get("titulo", "") for h in historico[-15:] if h.get("formato") == "papa"]
    lista = "\n".join(f"[{i}] ({x['fonte']}) {x['titulo']} — {x['resumo'][:200]}" for i, x in enumerate(itens))
    esc = chamar_gemini(f"""Notícias recentes da Igreja Católica:
{lista}

Escolhe a melhor para o vídeo «Palavra do Papa / Igreja Hoje»: dá prioridade a palavras do Papa (Angelus, audiência geral, homilia, mensagem), depois a Fátima e à Igreja em Portugal, depois a grandes acontecimentos da Igreja. Evita escândalos, processos judiciais, polémicas e política partidária, e temas já tratados: {recentes or 'nenhum'}.
Se nenhuma servir, "id" = -1. Devolve JSON: "id", "motivo".""", cfg, ESQ_PAPA_ESCOLHA)
    i = esc.get("id", -1)
    if not isinstance(i, int) or not (0 <= i < len(itens)):
        return None
    item = itens[i]
    texto = texto_artigo(item["link"]) or item["resumo"]
    if len(texto.split()) < 60:
        log("  Texto da notícia demasiado curto.")
        return None
    res = chamar_gemini(f"""Notícia ({item['fonte']}): {item['titulo']}
Texto:
{texto}

Escreve o vídeo curto. Devolve JSON com:
- "narracao": 110 a 150 palavras para ler em voz alta, claras e serenas. Se o Papa (ou outra pessoa) for citado, usa as palavras EXATAMENTE como estão no texto e diz quem as disse. Não inventes nada que não esteja no texto. Termina com uma frase curta que convida à oração.
- "etiqueta": uma de "Palavra do Papa", "Igreja Hoje", "Fátima".
- "titulo_topo": contexto em máx. 5 palavras (ex.: "Angelus de domingo", "Audiência geral").
- "titulo": a ideia principal em máx. 9 palavras.
{REGRAS_COMUNS}""", cfg, ESQ_PAPA)
    peca = {
        "formato": "papa", "link": item["link"], "etiqueta": res.get("etiqueta") or "Igreja Hoje",
        "titulo_topo": res.get("titulo_topo", ""), "titulo": res["titulo"], "narracao": res["narracao"].strip(),
        "titulo_youtube": res.get("titulo_youtube") or res["titulo"],
        "fontes": [{"nome": item["fonte"], "link": item["link"]}],
        "rodape": f"Fonte: {item['fonte']} · Narração com voz sintética",
    }
    return _completar(peca, res, ["Pope Leo XIV", "Saint Peter's Basilica", "Vatican City"])


FUNCOES = {"evangelho": formato_evangelho, "santo": formato_santo, "oracao": formato_oracao,
           "musica": formato_musica, "papa": formato_papa, "leitura": formato_leitura}


# ======================================================================
# TESTE OFFLINE (sem internet nem chaves)
# ======================================================================
def peca_teste(formato: str, pasta) -> dict:
    base = {"descricao": "Vídeo de teste.", "hashtags": ["Teste"], "tags": ["teste"], "buscas_imagens": [], "fontes": []}
    if formato == "musica":
        wav = pasta / "musica.wav"
        correr(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=262:duration=40", "-f", "lavfi",
                "-i", "sine=frequency=330:duration=40", "-f", "lavfi", "-i", "sine=frequency=392:duration=40",
                "-filter_complex", "amix=inputs=3,volume=0.6,afade=t=in:d=2", wav])
        return {**base, "formato": "musica", "etiqueta": "Música Sacra", "titulo_topo": "Coro e órgão · Música sacra",
                "titulo": "Ave Verum Corpus — W. A. Mozart", "texto_ecra": "Avé, verdadeiro Corpo nascido da Virgem Maria: "
                "um hino de adoração a Jesus na Eucaristia.", "audio_musica": wav, "dur_musica": 40.0,
                "titulo_youtube": "Teste de música", "rodape": "Gravação: Teste · CC0 · Wikimedia Commons"}
    texto = ("Evangelho de hoje, sábado, 7 de novembro. Evangelho de Nosso Senhor Jesus Cristo segundo São Lucas. "
             "Naquele tempo, disse Jesus aos seus discípulos: Quem é fiel nas coisas pequenas também é fiel nas grandes. "
             "Nenhum servo pode servir a dois senhores. Não podeis servir a Deus e ao dinheiro. Palavra da salvação. "
             "Hoje, Jesus convida-nos a escolher o essencial. Senhor, dá-nos um coração livre e fiel.")
    return {**base, "formato": formato, "etiqueta": "Evangelho do Dia", "titulo_topo": "Lc 16,9-15",
            "titulo": "Não podeis servir a Deus e ao dinheiro", "narracao": texto, "titulo_youtube": "Teste",
            "rodape": "Tradução litúrgica da Bíblia · evangelhoquotidiano.org · Voz sintética"}


# ======================================================================
# MÚSICA DE FUNDO (narrações)
# ======================================================================
def musica_de_fundo(cfg: dict, pasta) -> tuple:
    if not cfg["musica"].get("musica_de_fundo", True):
        return None, None
    buscas = list(cfg["musica"].get("fundo") or [])
    random.shuffle(buscas)
    for q in buscas[:3]:
        cands = [c for c in candidatos_musica(q, cfg, set()) if c["dur"] >= 60]
        if not cands:
            continue
        c = random.choice(cands[:5])
        destino = pasta / "fundo_musical.wav"
        try:
            descarregar_audio(c, destino, 200)
            if _volume_medio(destino) < -45:
                continue
        except Exception as e:
            log(f"  Música de fundo falhou: {type(e).__name__}")
            continue
        log(f"  Música de fundo: {c['titulo']} ({c['lic']})")
        return destino, {"id": c["titulo"], "autor": c["autor"], "licenca": c["lic"], "url": c["url"]}
    return None, None


# ======================================================================
# YOUTUBE
# ======================================================================
ESCOPO = ["https://www.googleapis.com/auth/youtube.upload"]


def _credenciais():
    from google.oauth2.credentials import Credentials
    faltam = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if faltam:
        raise RuntimeError(f"Faltam os segredos do YouTube: {', '.join(faltam)}")
    return Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                       client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"], scopes=ESCOPO)


def enviar(video, titulo: str, descricao: str, tags: list, cfg: dict, categoria: str | None = None) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt_cfg = cfg["youtube"]
    modo = os.environ.get("MODO_YT") or yt_cfg.get("modo", "publico")
    if modo == "config":
        modo = yt_cfg.get("modo", "publico")
    status = {"selfDeclaredMadeForKids": False, "embeddable": True, "license": "youtube",
              "containsSyntheticMedia": bool(yt_cfg.get("marcar_conteudo_sintetico", False))}
    publicar_em = None
    if modo == "publico":
        status["privacyStatus"] = "public"
    elif modo == "privado":
        status["privacyStatus"] = "private"
    else:
        status["privacyStatus"] = "private"
        publicar_em = datetime.now(timezone.utc) + timedelta(hours=float(yt_cfg.get("horas_revisao", 1)))
        status["publishAt"] = publicar_em.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    titulo = re.sub(r"\s+", " ", titulo.replace("<", "").replace(">", "")).strip()
    if len(titulo) > 100:
        titulo = titulo[:99].rsplit(" ", 1)[0] + "…"
    descricao = descricao.replace("<", "").replace(">", "")
    tags_ok, soma = [], 0
    for t in tags:
        t = t.replace("<", "").replace(">", "").replace(",", " ").strip()[:60]
        if t and soma + len(t) + 3 <= 480:
            tags_ok.append(t)
            soma += len(t) + 3
    corpo = {"snippet": {"title": titulo, "description": descricao[:4900], "tags": tags_ok,
                         "categoryId": str(categoria or yt_cfg.get("categoria", "22")),
                         "defaultLanguage": yt_cfg.get("idioma", "pt-PT"),
                         "defaultAudioLanguage": yt_cfg.get("idioma", "pt-PT")},
             "status": status}
    yt = build("youtube", "v3", credentials=_credenciais(), cache_discovery=False)
    pedido = yt.videos().insert(part="snippet,status", body=corpo,
                                notifySubscribers=bool(yt_cfg.get("notificar_inscritos", False)),
                                media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=-1, resumable=True))
    resposta = None
    while resposta is None:
        _, resposta = pedido.next_chunk()
    vid = resposta["id"]
    log(f"  ✓ Enviado: https://youtube.com/shorts/{vid} ({status['privacyStatus']})")
    return {"id": vid, "privacidade": status["privacyStatus"]}


# ======================================================================
# MAIN
# ======================================================================
HASHTAGS_BASE = ["Católico", "FéCatólica", "Jesus"]


def descricao_completa(peca: dict, imagens: list, cfg: dict, cred_fundo: dict | None) -> str:
    partes = [(peca.get("descricao") or "").strip(), ""]
    if peca.get("fontes"):
        partes.append("Fontes:")
        partes += [f"• {f['nome']}: {f['link']}" for f in peca["fontes"]]
        partes.append("")
    cm = peca.get("credito_musica")
    if cm:
        partes += [f"Gravação: {cm['id'].replace('File:', '')} — {cm['autor']} ({cm['licenca']}), via Wikimedia Commons: {cm['url']}", ""]
    if cred_fundo:
        partes += [f"Música de fundo: {cred_fundo['id'].replace('File:', '')} — {cred_fundo['autor']} "
                   f"({cred_fundo['licenca']}), via Wikimedia Commons: {cred_fundo['url']}", ""]
    creditos = [i for i in imagens if i.get("autor")]
    if creditos:
        partes.append("Imagens (domínio público / licenças livres, via Wikimedia Commons):")
        partes += [f"• {i['id'].replace('File:', '')} — {i['autor']} ({i.get('licenca', '')}): {i.get('url', '')}" for i in creditos]
        partes.append("")
    if peca.get("narracao"):
        partes.append("Narração com voz sintética; texto preparado com ajuda de inteligência artificial.")
    partes.append(cfg["canal"].get("chamada_final", ""))
    vistos, hashtags = set(), []
    for t in HASHTAGS_BASE + [h.lstrip("#").replace(" ", "") for h in peca.get("hashtags", [])]:
        if t and t.lower() not in vistos:
            vistos.add(t.lower())
            hashtags.append("#" + t)
    partes += ["", " ".join(hashtags[:7])]
    return "\n".join(partes)


def escolher_formato(pedido: str, cfg: dict) -> list:
    reserva = [f for f in cfg["agenda"].get("reserva", []) if f in FORMATOS]
    if pedido in FORMATOS:
        primeiro = pedido
    else:
        primeiro = agenda.formato_atual() or (reserva[0] if reserva else "oracao")
    ordem = [primeiro] + [f for f in reserva if f != primeiro]
    return list(dict.fromkeys(ordem))


def produzir(ordem: list, cfg: dict, historico: list, pasta) -> dict | None:
    for formato in ordem:
        log(f"1) Formato: {formato}")
        try:
            peca = FUNCOES[formato](cfg, historico, pasta)
        except Exception as e:
            log(f"  ✗ {formato} falhou: {type(e).__name__}: {str(e)[:300]}")
            peca = None
        if peca:
            return peca
        log("  Sem conteúdo para este formato; a tentar o seguinte.")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-upload", action="store_true", help="não envia para o YouTube")
    ap.add_argument("--teste-offline", action="store_true", help="vídeo de demonstração sem internet")
    ap.add_argument("--formato", default=os.environ.get("FORMATO") or "auto", help="auto, " + ", ".join(FORMATOS))
    args = ap.parse_args()
    garantir_fontes()
    cfg = carregar_config()
    historico = carregar_historico()
    saida_dir = RAIZ / "saida"
    saida_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        if args.teste_offline:
            args.sem_upload = True
            peca = peca_teste(args.formato if args.formato in FORMATOS else "evangelho", pasta)
        else:
            ordem = escolher_formato(args.formato, cfg)
            log(f"Ordem de formatos: {', '.join(ordem)}")
            peca = produzir(ordem, cfg, historico, pasta)
            if not peca:
                log("Nada para publicar agora. Até à próxima execução!")
                resumo_github("Nada publicado nesta execução (sem conteúdo novo em nenhum formato).")
                return 0
        log(f"   Título: {peca['titulo_youtube']}")

        log("2) Áudio...")
        fundo_mus, cred_fundo, ass = None, None, None
        if peca.get("narracao"):
            voz = peca.get("voz") or cfg["voz"]["nome"]
            audio, palavras, dur = sintetizar(peca["narracao"], voz, cfg, pasta, offline=args.teste_offline)
            if dur > 176:   # Shorts até 3 minutos
                fator = min(1.25, dur / 174)
                rapido = pasta / "narracao_rapida.wav"
                correr(["ffmpeg", "-y", "-v", "error", "-i", audio, "-filter:a", f"atempo={fator:.3f}", rapido])
                audio, dur = rapido, duracao_media(rapido)
                for w in palavras:
                    w["ini"] /= fator
                    w["fim"] /= fator
                log(f"  Narração acelerada x{fator:.2f} para caber em 3 minutos ({dur:.1f}s)")
            ass = pasta / "legendas.ass"
            gerar_ass(palavras, ass, dur + 1.4)
            if not args.teste_offline:
                fundo_mus, cred_fundo = musica_de_fundo(cfg, pasta)
        else:
            audio, dur = peca["audio_musica"], float(peca["dur_musica"])

        log("3) Imagens...")
        n = int(cfg["imagens"]["quantidade_musica" if peca["formato"] == "musica" else "quantidade"])
        if args.teste_offline:
            imagens = fundos_gerados(min(n, 3), pasta)
        else:
            tema = f"{peca.get('etiqueta')}: {peca.get('titulo_topo', '')} — {peca.get('titulo', '')}"
            imagens = obter_imagens(peca.get("buscas_imagens", []), n, pasta, historico, tema, cfg)
            if len(imagens) < 2:
                imagens += fundos_gerados(2, pasta)
        grafico = pasta / "grafico.png"
        camada_grafica(grafico, peca, cfg)

        log("4) A montar o vídeo...")
        carimbo = agora_lx().strftime("%Y%m%d_%H%M")
        video = saida_dir / f"{peca['formato']}_{carimbo}.mp4"
        montar(imagens, audio, ass, grafico, dur, pasta, video, fundo_mus)
        log(f"   Vídeo: {video} ({video.stat().st_size / 1e6:.1f} MB)")

    descricao = descricao_completa(peca, imagens, cfg, cred_fundo)
    tags = list(dict.fromkeys((peca.get("tags") or []) + ["católico", "fé católica", "Transmissões Católicas"]))
    (saida_dir / "ultimo.json").write_text(json.dumps(
        {"titulo": peca["titulo_youtube"], "descricao": descricao, "tags": tags, "narracao": peca.get("narracao"),
         "video": video.name}, ensure_ascii=False, indent=2), encoding="utf-8")
    resumo = [f"## {peca['titulo_youtube']}", "", f"**Formato:** {peca['formato']}", "",
              peca.get("narracao") or peca.get("texto_ecra", ""), "", "**Descrição:**", "", "~~~", descricao, "~~~"]

    if args.sem_upload:
        log("Modo sem upload: vídeo criado mas não enviado.")
        resumo.append("\n_Modo de teste: não foi publicado._")
        resumo_github("\n".join(resumo))
        return 0

    log("5) A enviar para o YouTube...")
    res = enviar(video, peca["titulo_youtube"], descricao, tags, cfg, peca.get("categoria"))
    resumo.append(f"\n**YouTube:** https://youtube.com/shorts/{res['id']} ({res['privacidade']})")
    resumo_github("\n".join(resumo))
    historico.append({
        "data": datetime.now(timezone.utc).isoformat(), "formato": peca["formato"], "chave": peca.get("chave"),
        "titulo": peca["titulo_youtube"], "video_id": res["id"],
        "imagens": [i["id"] for i in imagens if i.get("id")], "musica": peca.get("musica"),
        "busca_musica": peca.get("busca_musica"), "oracao": peca.get("oracao"), "santo": peca.get("santo"),
        "link": peca.get("link"),
    })
    guardar_historico(historico)
    return 0


if __name__ == "__main__":
    sys.exit(main())
