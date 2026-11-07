"""Horários da publicação automática (secção "agenda" do config.yaml, no fuso horário do canal).

  python agenda.py            -> segundos até ao próximo horário
  python agenda.py formato    -> formato do horário mais próximo de agora

Usa só a biblioteca padrão do Python, para correr sem instalar nada.
"""
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

def _ler_config() -> str:
    return (Path(__file__).resolve().parent / "config.yaml").read_text(encoding="utf-8")


def fuso() -> str:
    """Fuso horário do canal (idioma.fuso no config.yaml); por omissão, Brasília."""
    m = re.search(r'^\s*fuso:\s*"?([A-Za-z_]+/[A-Za-z_]+)"?', _ler_config(), re.M)
    return m.group(1) if m else "America/Sao_Paulo"


FUSO = ZoneInfo(fuso())


def horarios(texto: str | None = None) -> list:
    """[(hora, minuto, formato), ...] lidos do config.yaml."""
    if texto is None:
        texto = _ler_config()
    out = []
    for m in re.finditer(r'hora:\s*"?(\d{1,2}):(\d{2})"?\s*,\s*formato:\s*"?([a-z]+)"?', texto):
        out.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return sorted(out) or [(9, 7, "evangelho"), (18, 7, "musica")]


def segundos_ate_proximo(agora: datetime | None = None) -> int:
    agora = agora or datetime.now(FUSO)
    candidatos = []
    for dia in (0, 1, 2):
        base = (agora + timedelta(days=dia)).date()
        for h, m, _ in horarios():
            t = datetime(base.year, base.month, base.day, h, m, tzinfo=FUSO)
            if t > agora + timedelta(seconds=20):
                candidatos.append(t)
    proximo = min(candidatos)
    return int((proximo - agora).total_seconds())


def formato_atual(agora: datetime | None = None, tolerancia_min: int = 100) -> str | None:
    """Formato do horário mais próximo (antes ou depois) de agora, se estiver perto."""
    agora = agora or datetime.now(FUSO)
    melhor, dist = None, None
    for dia in (-1, 0, 1):
        base = (agora + timedelta(days=dia)).date()
        for h, m, formato in horarios():
            t = datetime(base.year, base.month, base.day, h, m, tzinfo=FUSO)
            d = abs((t - agora).total_seconds())
            if dist is None or d < dist:
                melhor, dist = formato, d
    return melhor if dist is not None and dist <= tolerancia_min * 60 else None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "formato":
        print(formato_atual() or "")
    else:
        print(segundos_ate_proximo())
