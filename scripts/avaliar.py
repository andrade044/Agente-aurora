"""Avaliação automática dos casos oficiais (data/testes/perguntas_avaliacao.json).

Uso:
    python -m scripts.avaliar                         # contra a API em http://localhost:8000
    python -m scripts.avaliar --url http://host:8000
    python -m scripts.avaliar --local                 # sem servidor: chama o orquestrador direto (precisa do banco)

Para cada caso verifica: domínio previsto, fonte esperada e o critério do enunciado. Os valores numéricos
esperados são recalculados direto dos CSV com Decimal (independente do código dos agentes).
Gera docs/resultados_avaliacao.md. Cada pergunta também fica registrada nos logs do agente.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.textutils import brl, normalize  # noqa: E402

DATA = ROOT / "data"


def _csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gabarito() -> dict[str, str]:
    lanc = _csv(DATA / "financeiro" / "lancamentos_financeiros.csv")
    orc = _csv(DATA / "financeiro" / "orcamento_mensal.csv")
    t006 = sum(Decimal(r["valor_brl"]) for r in lanc if r["tipo"] == "Despesa" and r["status"] == "Pago"
               and "2025-01-01" <= r["data_competencia"] <= "2025-03-31")
    t011 = sum(Decimal(r["valor_brl"]) for r in lanc if r["tipo"] == "Receita" and r["data_competencia"].startswith("2025"))
    jan = [r for r in orc if r["ano"] == "2026" and r["mes"] == "01"]
    top = max(jan, key=lambda r: Decimal(r["orcamento_brl"]))
    return {"T006": brl(t006), "T011": brl(t011), "T007_dep": top["departamento"],
            "T007_val": brl(Decimal(top["orcamento_brl"]))}


def criterios(g: dict[str, str]) -> dict[str, list[list[str]]]:
    """Para cada caso, lista de grupos: a resposta precisa conter ao menos um termo de CADA grupo."""
    return {
        "T001": [["portal"], ["30 dias"]],
        "T002": [["10 dias"], ["comprovante"]],
        "T003": [["lideranca"], ["gerente"], ["diretoria"]],
        "T004": [["nao foi encontrado", "nao encontrado", "nao existe", "nao consta"]],
        "T005": [["aberto"], ["em analise"], ["aguardando area responsavel"], ["respondido"], ["concluido"]],
        "T006": [[g["T006"]]],
        "T007": [[normalize(g["T007_dep"])], [g["T007_val"]]],
        "T008": [["seguranca@aurora.example"]],
        "T009": [["aguardando area responsavel"]],
        "T010": [["nao posso", "nao e possivel", "nao compartilh", "nao fornec"],
                 ["portal de ti", "seguranca@aurora.example", "privacidade@aurora.example"]],
        "T011": [[g["T011"]]],
        "T012": [["seguranca@aurora.example"], ["imediatamente"], ["senha", "token", "sigilos"]],
    }


def dominio_ok(esperado: str, obtido: str | None) -> bool:
    if esperado.startswith("fora_de_escopo"):
        return obtido in {"seguranca", "fora_de_escopo"}
    return obtido == esperado


def fonte_ok(esperada: str, fontes: list[str]) -> bool:
    return any(f.strip() in fontes for f in esperada.split(";"))


def ask_http(url: str, pergunta: str) -> dict:
    req = urllib.request.Request(f"{url}/api/chat", data=json.dumps({"pergunta": pergunta}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--local", action="store_true", help="chama o orquestrador sem servidor HTTP")
    ap.add_argument("--saida", default=str(ROOT / "docs" / "resultados_avaliacao.md"))
    args = ap.parse_args()

    if args.local:
        from app import db, rag
        from app.orchestrator import handle
        db.init_pool()
        rag.load_index()
        ask = lambda q: handle(q)  # noqa: E731
        info = {"modo": "local"}
    else:
        ask = lambda q: ask_http(args.url, q)  # noqa: E731
        with urllib.request.urlopen(f"{args.url}/api/info", timeout=30) as resp:
            info = json.loads(resp.read())

    casos = json.loads((DATA / "testes" / "perguntas_avaliacao.json").read_text(encoding="utf-8"))["casos"]
    g = gabarito()
    crit = criterios(g)
    linhas, aprovados = [], 0
    for c in casos:
        r = ask(c["pergunta"])
        texto = normalize(r["resposta"])
        dom = dominio_ok(c["dominio_esperado"], r["dominio"])
        fon = fonte_ok(c["fonte_esperada"], r.get("fontes") or [])
        faltando = [grupo for grupo in crit[c["id"]] if not any(normalize(t) in texto for t in grupo)]
        cri = not faltando
        ok = dom and fon and cri
        aprovados += ok
        linhas.append((c, r, dom, fon, cri, faltando, ok))
        print(f"{'OK ' if ok else 'FALHA'} {c['id']} dominio={r['dominio']} ({'ok' if dom else 'x'}) "
              f"fonte={'ok' if fon else 'x'} criterio={'ok' if cri else 'x ' + str(faltando)} "
              f"metodo={r['metodo_classificacao']} {r['latencia_ms']}ms")
        time.sleep(0.2)

    total = len(casos)
    print(f"\n{aprovados}/{total} casos aprovados")

    md = [f"# Resultado da avaliação — {datetime.now().strftime('%d/%m/%Y %H:%M')}", "",
          f"Configuração: `{json.dumps(info.get('llm', info), ensure_ascii=False)}`", "",
          f"**{aprovados}/{total} casos aprovados.** Valores numéricos esperados recalculados dos CSV: "
          f"T006 = {g['T006']}, T007 = {g['T007_dep']} ({g['T007_val']}), T011 = {g['T011']}.", "",
          "| Caso | Pergunta | Domínio esperado | Domínio obtido | Método | Fonte | Critério | Resultado |",
          "|---|---|---|---|---|---|---|---|"]
    for c, r, dom, fon, cri, faltando, ok in linhas:
        md.append(f"| {c['id']} | {c['pergunta']} | {c['dominio_esperado']} | {r['dominio']} "
                  f"({r['confianca']}) | {r['metodo_classificacao']} | {'✅' if fon else '❌'} "
                  f"{', '.join(r.get('fontes') or [])} | {'✅' if cri else '❌ falta ' + str(faltando)} | "
                  f"{'✅' if ok else '❌'} |")
    md += ["", "## Respostas", ""]
    for c, r, *_ in linhas:
        md += [f"### {c['id']} — {c['pergunta']}", f"_Critério do enunciado: {c['criterio']}_", "",
               "```text", r["resposta"], "```", ""]
    Path(args.saida).write_text("\n".join(md), encoding="utf-8")
    print(f"Relatório: {args.saida}")
    return 0 if aprovados == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
