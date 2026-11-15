# FitFix: naprawa części do druku 3D, która nie pasuje do złożenia

Środowisko RL dla agentów: obudowa elektroniki ma przesunięte wycięcie pod wtyk USB-C (wada D1). Agent przez narzędzia MCP
mierzy, diagnozuje i edytuje obudowę, aż całe złożenie pasuje. Grader liczy nagrodę z geometrii.

## Szybki start

```bash
pip install -r requirements.txt
python -m fitfix.generator --seeds 0-9 --out tasks     # 10 zadań (parts/ jawne, hidden/ tylko dla gradera)
python run_eval.py --agent all --seeds 0-9            # do_nothing, stop_early, oracle, solver
python tests/test_exploits.py                         # red team: każdy skrót < 0.4
python harbor/build_tasks.py                          # zadania w formacie Harbora -> harbor_tasks/
```

Wyniki na seedach 0–9 (ta wersja): do_nothing 0.0, stop_early 0.0, oracle 1.0, solver 1.0. Najlepszy exploit 0.35.

Harbor (na maszynie z Dockerem):

```bash
harbor run -p harbor_tasks/fitfix-enc-0000 -a oracle                    # reference = solution/solve.sh (solver)
harbor run -p harbor_tasks/fitfix-enc-0000 -a opencode -m <model>       # frontier agent
```

Dokładne flagi `harbor run` sprawdźcie z `harbor run --help` albo ze starter kitem organizatorów.

## Struktura

| Plik | Co robi |
| --- | --- |
| `fitfix/geom.py` | wspólna geometria: prymitywy, operacje boolowskie, kolizje, luz, przekroje, grubość ścianek. Współrzędne przyciągane do 0,001 mm |
| `fitfix/generator.py` | proceduralne złożenie (obudowa, PCB z USB-C, wtyk, pokrywa) + wstrzyknięcie wady D1 |
| `fitfix/grader.py` | bramka funkcjonalna, pasowanie, drukowalność, minimalność zmian, końcowa nagroda |
| `fitfix/env.py` | stan epizodu i implementacja narzędzi, log JSONL, limit wywołań, budżet `test_fit` |
| `fitfix/server.py` | serwer MCP (stdio, FastMCP) wystawiający narzędzia agentowi |
| `fitfix/agents.py` | do_nothing, stop_early, oracle (czyta hidden/), solver (tylko narzędzia) |
| `fitfix/render.py` | podglądy 3D i przekroje do demo |
| `harbor/` | instrukcja dla agenta i budowanie zadań Harbora |
| `tests/test_exploits.py` | lista exploitów z oczekiwanym wynikiem |

## Nagroda

```
R = bramka × wynik
bramka = 0, gdy: objętość zmieniona > 15%, obrys zewnętrzny przesunięty > 1 mm, brak tulejki lub otworu pilotowego,
         kolizja z PCB lub pokrywą, plik niepoprawny
wynik  = 0.5 + 0.3·drukowalność + 0.2·minimalność   gdy wtyk przechodzi z luzem 0.15–0.5 mm z każdej strony
       = 0.25 + 0.1·drukowalność                    gdy wtyk przechodzi, ale luz poza przedziałem
       = 0.2 · (usunięta część pierwotnej kolizji)  w pozostałych przypadkach
```

## Podział jawne / ukryte

- Kontener agenta: `parts/` (STL), `task.json`, `check_spec.json` (fakty mierzalne z części). Agent ma też shell, więc może je czytać.
- Weryfikator (`tests/`): własna kopia kodu gradera, nienaruszone części, `hidden/` (model poprawny, wielkość wady). Podmiana gradera lub części w kontenerze nic nie daje (sprawdzone).

## Następne kroki (v1 → v3 z planu)

1. Pierwszy przebieg frontier modelu przez Harbora na 1 seedzie, potem ×3 na 10.
2. Jeśli frontier rozwiązuje D1 prawie zawsze: wada D4 (kaskada: poprawne wycięcie ścienia ściankę) i mniejszy `test_fit_budget`.
3. Ścieżka wsuwania pokrywy, wady D2 (rozstaw tulejek) i D3 (luz kołnierza).
