"""Constantes e utilidades da linha do tempo da apuração (compartilhadas).

Todos os horários são em minutos desde 00:00 do dia da eleição, no horário
de Brasília. Valores acima de 1440 representam a madrugada do dia seguinte.

A apuração é agregada em "baldes" de BALDE_MIN minutos a partir de INICIO_MIN
(17:00, quando a votação termina e a divulgação começa). O balde k contém os
boletins com horário em [INICIO + k*BALDE, INICIO + (k+1)*BALDE). Boletins
anteriores ao início caem no balde 0; posteriores ao fim, no último (N_BALDES).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")

INICIO_MIN = 17 * 60  # 17:00
FIM_MIN = 26 * 60  # 02:00 do dia seguinte
BALDE_MIN = 10
N_BALDES = (FIM_MIN - INICIO_MIN) // BALDE_MIN  # índice do balde "final"

NUM_LULA = "13"
NUM_BOLSONARO = "22"


def balde_de_minuto(minuto: float) -> int:
    """Balde em que cai um boletim emitido no minuto informado."""
    if minuto < INICIO_MIN:
        return 0
    if minuto >= FIM_MIN:
        return N_BALDES
    return int((minuto - INICIO_MIN) // BALDE_MIN)


def ultimo_balde_completo(minuto: float) -> int:
    """Último balde totalmente apurado até o minuto informado (-1 = nenhum)."""
    if minuto >= FIM_MIN + BALDE_MIN:
        return N_BALDES
    k = int((minuto - INICIO_MIN) // BALDE_MIN) - 1
    return max(-1, min(k, N_BALDES - 1))


def fim_do_balde(k: int) -> int:
    """Minuto em que o balde k fica completo (para rotular gráficos)."""
    return INICIO_MIN + (k + 1) * BALDE_MIN


def minuto_para_hhmm(minuto: int) -> str:
    h, m = divmod(int(minuto), 60)
    return f"{h % 24:02d}:{m:02d}"


def minuto_para_epoch(dia: date, minuto: float) -> float:
    base = datetime(dia.year, dia.month, dia.day, tzinfo=BRT)
    return (base + timedelta(minutes=minuto)).timestamp()


def epoch_para_minuto(dia: date, epoch: float) -> float:
    base = datetime(dia.year, dia.month, dia.day, tzinfo=BRT)
    return (epoch - base.timestamp()) / 60.0
