"""Processo em segundo plano: consulta as caixas em ciclo.

De propósito sem fila de tarefas. Consultar vinte e cinco caixas uma vez
por minuto não é carga que justifique montar broker, agendador e mais um
conjunto de jeitos de quebrar. Aqui há um único laço, que sobrevive a
qualquer erro e volta em um minuto.

Repetir após uma falha não precisa de mecanismo próprio: a próxima volta
já é a repetição, e o cursor da caixa não anda enquanto os e-mails não
forem baixados.
"""

import asyncio
import logging
import time

from app.brief import morning
from app.db import SessionFactory
from app.worker.tasks import classification_paused, classify_pending, sync_all

INTERVAL_SECONDS = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("worker")


async def main() -> None:
    log.info("worker iniciado, consulta a cada %s segundos", INTERVAL_SECONDS)
    while True:
        started = time.monotonic()
        try:
            results = await sync_all(SessionFactory)
            fetched = sum(count for count in results.values() if count > 0)
            broken = [box for box, count in results.items() if count < 0]
            was_paused = classification_paused()
            late = await classify_pending(SessionFactory)
            if classification_paused() and not was_paused:
                log.warning("triagem de e-mails pausada: acabou a cota diária de requisições")
            log.info(
                "caixas: %s, e-mails novos: %s, com erro: %s, triados desde a última volta: %s",
                len(results),
                fetched,
                broken,
                late,
            )
        except Exception:
            log.exception("a volta de sincronização falhou por inteiro")

        # Separado do e-mail: uma falha na coleta não pode deixar a manhã sem resumo.
        try:
            await morning(SessionFactory)
        except Exception:
            log.exception("não foi possível montar o resumo da manhã")

        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    asyncio.run(main())
