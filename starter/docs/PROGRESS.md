# PROGRESS

## PODSUMOWANIE zadań 4-7 (2026-11-15, praca autonomiczna w nocy)

Bez STOP: spec 0.7 jest wykonalna w całości. Liczby nie były dostrajane pod kryteria akceptacji.

**Co działa**
- Ogólne checki G1-G6, S1-S3 i nagroda z danych (`cadfix/checks`, `cadfix/core/spec.py`), spec hinge_lid jako dane (`scenarios/hinge_lid/spec.py`), grader CLI `python -m cadfix.grade` (zawsze pisze reward.txt). Stare warianty 2c/2d przez nowy grader: 210 wariantów, 0 różnic (`docs/acceptance_4.txt`).
- Operacje CAD (chamfer, fillet, offset_face, extrude_cut, cut_box, add_box, undo), zapytania (krawędzie/ściany w świecie, measure, section), środowisko z logiem JSONL i migawkami STEP+GLB, serwer MCP stdio, instruction.md z danych publicznych (test wycieków).
- Rozwiązanie wzorcowe tylko przez narzędzia: **1.000 na L1/L2/L3 seedy 0-9 (30/30)**, 1.00-1.03 x V_ref, 27-33 wywołań, 2-5 s. do_nothing i stop_early: 0 na 30/30 (`results/run_eval_20261115_011537.csv`).
- Exploity (17, L2 i L3): najgorszy **0.300** (< 0.4), tabela `docs/exploits.txt`.
- Harbor 0.26 (Docker lokalnie, `harbor_tasks/judge` = L1/L2/L3 seed 0, weryfikator w osobnym kontenerze): **oracle 3/3 = 1.000, nop 0.000, stop-early 0.000**; komendy z README sprawdzone dokładnie w tej postaci; logi w `harbor_runs/`.
- README dla jury (`README.md`), CLAUDE.md uzupełniony.
- Testy: `pytest -q -m "not slow"` **73 passed, 58 s**; pełne `pytest -q` **309 passed, 1 failed, 20:26** (błąd: przypadkowa zbieżność liczby w teście wycieków briefu, L1 seed 2: 5 x V_ref = 70.5 mm³ = długość pudełka; test poprawiony, `test_dev_scripts.py` + `test_instruction.py` 19/19 po poprawce).

**Rano do zrobienia (użytkownik)**
1. `pip install harbor==0.26.0` (venv z Pythonem 3.12), klucz API modelu w zmiennych środowiska, z katalogu `starter/`:
   `harbor run -p harbor_tasks/judge -a opencode -m <provider/model> -k 3`
2. Wynik i ścieżkę `jobs/...` wpisać w README, sekcja "Harbor run log" (opcjonalnie skopiować job do `harbor_runs/`).

**Otwarte problemy**
1. Licznik test_fit jest w katalogu wyjściowym agenta: agent z shellem może ukryć wywołania (zysk max 0.1, D18).
2. Ściany cieńsze niż 0.2 mm ignoruje filtr cech (D15); taki cut nigdy nie pomaga w S1, ale to luka w S2.
3. Pełne `pytest -q` trwa długo (~20 min): każdy moduł testów generuje seedy L3 od nowa (11 s+ na seed). Pamięć podręczna generatora w testach by to skróciła.
4. Seed 3 L3 potrzebuje 16 zastąpień przy limicie 20 (P5 z 2d, nadal otwarte).
5. OpenCode nie był uruchamiany (płatny model). Nie sprawdziłem, czy OpenCode rzeczywiście widzi serwer MCP w kontenerze; oracle i stop-early używają tych samych narzędzi lokalnie w kontenerze.

**Decyzje**: `docs/DECISIONS.md` D11-D26 (m.in. podział publiczne/prywatne, strefy, filtr 0.2 mm po grubości, układ pudełka dla S1, weryfikator separate, flagi Harbora 0.26).


## PODSUMOWANIE zadania 2c: poziomy L1-L3 (2026-11-14, praca autonomiczna)

Nie było powodu do STOP: spec jest wykonalna. Jedno oczekiwanie z TASK_2c się nie spełnia (L3 „identyczne podcięcia wyraźnie < 0.9”), opisane niżej, liczby nie były dostrajane.

**Co działa**
- Generator z poziomami: L1/L2 = dokładnie części z 2b (różnią się tylko S3), L3 = 3 różne żebra + losowa poza w świecie (yaw 15-40°, tilt 0-8°, offset 20-200 mm). Wyjście `output/hinge_lid/<L>/seed_NNNN/`.
- Ogólne operacje `chamfer` i `extrude_cut` (`cadfix/ops/edit.py`) z czytelnymi błędami; `evaluate.py` przyjmuje listę operacji JSON, `--level`, `--hide-score`.
- Skan 2D per żebro → V_ref (suma najmniejszych podcięć, żebro ± 0.35 mm), V_full_edge, V_identical; luz na końcach sprawdzany w 3D. Poprawka odniesienia jako operacje (ukryta, tylko do oceny).
- Nagroda 0.6: 0.25 · postęp / 0.3 + 0.1 · druk + 0.6 · S3, S3 = krotność V_ref (L1 4×/8×, L2/L3 1.15×/2×). Liczby sprawdzane testem z tekstem `scenario.json`.
- `brief.py` per poziom: S3 tylko jako reguła; L3 wyłącznie w układzie świata. Test wycieków na wszystkich poziomach.
- `pytest -q`: **245 passed** w 320 s (przed 2c: 109 w 24 s).

**Tabele akceptacyjne** (3D, prawdziwe operacje B-rep, seedy 0-9; pełne: `docs/acceptance_2c.txt`; komenda `python -m scenarios.hinge_lid.dev_sweep --level L1,L2,L3 --seeds 0-9`, 342 s)

**L1** (nagroda; S3 4× / 8× V_ref)

| seed | src | V_ref mm³ | full/ref | ident/ref | oryginał | odniesienie | cała krawędź | identyczne | dł. = żebro | 0.7× side | sym. 45° |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 25.83 | 3.20 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.052 | 0.000 |
| 1 | 1 | 16.36 | 3.51 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.054 | 0.000 |
| 2 | 2 | 14.10 | 3.75 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.081 | 0.000 |
| 3 | 3 | 13.18 | 4.16 | 1.000 | 0.000 | 1.000 | 0.976 | 1.000 | 0.000 | 0.055 | 0.000 |
| 4 | 4 | 15.88 | 3.34 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.062 | 0.696 |
| 5 | 5 | 11.12 | 4.27 | 1.000 | 0.000 | 1.000 | 0.959 | 1.000 | 0.000 | 0.071 | 0.000 |
| 6 | 6 | 12.88 | 4.68 | 1.000 | 0.000 | 1.000 | 0.897 | 1.000 | 0.000 | 0.100 | 0.000 |
| 7 | 7 | 17.05 | 4.15 | 1.000 | 0.000 | 1.000 | 0.977 | 1.000 | 0.000 | 0.033 | 0.000 |
| 8 | 8 | 17.07 | 4.23 | 1.000 | 0.000 | 1.000 | 0.965 | 1.000 | 0.000 | 0.057 | 0.000 |
| 9 | 2009 | 18.33 | 3.67 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.053 | 0.000 |

**L2** (nagroda; S3 1.15× / 2× V_ref)

| seed | src | V_ref mm³ | full/ref | ident/ref | oryginał | odniesienie | cała krawędź | identyczne | dł. = żebro | 0.7× side | sym. 45° |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 25.83 | 3.20 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.052 | 0.000 |
| 1 | 1 | 16.36 | 3.51 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.054 | 0.000 |
| 2 | 2 | 14.10 | 3.75 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.081 | 0.000 |
| 3 | 3 | 13.18 | 4.16 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.055 | 0.000 |
| 4 | 4 | 15.88 | 3.34 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.062 | 0.400 |
| 5 | 5 | 11.12 | 4.27 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.071 | 0.000 |
| 6 | 6 | 12.88 | 4.68 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.100 | 0.000 |
| 7 | 7 | 17.05 | 4.15 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.033 | 0.000 |
| 8 | 8 | 17.07 | 4.23 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.057 | 0.000 |
| 9 | 2009 | 18.33 | 3.67 | 1.000 | 0.000 | 1.000 | 0.400 | 1.000 | 0.000 | 0.053 | 0.000 |

**L3** (nagroda; S3 1.15× / 2× V_ref)

| seed | src | V_ref mm³ | full/ref | ident/ref | oryginał | odniesienie | cała krawędź | identyczne | dł. = żebro | 0.7× side | sym. 45° |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1000 | 16.75 | 4.52 | 1.160 | 0.000 | 1.000 | 0.400 | 0.993 | 0.000 | 0.110 | 0.000 |
| 1 | 1 | 20.12 | 4.40 | 1.388 | 0.000 | 1.000 | 0.400 | 0.832 | 0.000 | 0.057 | 0.000 |
| 2 | 1002 | 13.00 | 4.99 | 1.392 | 0.000 | 1.000 | 0.400 | 0.829 | 0.000 | 0.067 | 0.000 |
| 3 | 3 | 21.84 | 3.85 | 1.284 | 0.000 | 1.000 | 0.400 | 0.906 | 0.000 | 0.044 | 0.000 |
| 4 | 4 | 19.54 | 3.89 | 1.199 | 0.000 | 1.000 | 0.400 | 0.965 | 0.000 | 0.036 | 0.000 |
| 5 | 1005 | 14.97 | 5.26 | 1.332 | 0.000 | 1.000 | 0.400 | 0.872 | 0.000 | 0.048 | 0.000 |
| 6 | 2006 | 14.02 | 3.84 | 1.213 | 0.000 | 1.000 | 0.400 | 0.956 | 0.000 | 0.053 | 0.000 |
| 7 | 2007 | 17.95 | 4.29 | 1.378 | 0.000 | 1.000 | 0.400 | 0.839 | 0.000 | 0.041 | 0.000 |
| 8 | 8 | 18.30 | 3.87 | 1.236 | 0.000 | 1.000 | 0.400 | 0.940 | 0.000 | 0.053 | 0.000 |
| 9 | 9 | 16.05 | 4.61 | 1.289 | 0.000 | 1.000 | 0.400 | 0.901 | 0.000 | 0.050 | 0.000 |

Kolumny: src = seed źródłowy po zastąpieniu; full/ref, ident/ref = V_full_edge / V_ref, V_identical / V_ref; pozostałe = nagroda. Sworzeń, moduł, wsporniki: 0 kolizji we wszystkich 210 wariantach. Czas przeglądu S1: L1/L2 0.09-0.17 s, L3 1.6-2.2 s.

**Oczekiwane vs rzeczywiste**
- wszystkie poziomy: oryginał 0 ✓, odniesienie 1.0 ✓ (30/30), 0.7× side < 0.25 ✓ (max 0.110)
- L1 cała krawędź ~1.0: 0.897-1.0 (5/10 dokładnie 1.0, bo full/ref do 4.68 > 4)
- L2/L3 cała krawędź ~0.4: 0.400 ✓ (20/20)
- **L3 identyczne wyraźnie < 0.9: NIE**: 0.829-0.993, średnio 0.903, tylko 4/10 < 0.9
- długość = żebro: S1 FAIL na każdym seedzie ✓ (30/30, nagroda 0.000)

**Otwarte problemy**
1. Pułapka L3 (identyczne podcięcia) jest za słaba przy ograniczeniu „max/min ≥ 1.5×” (P3).
2. Przegląd S1 w L3 ~13× wolniejszy niż w L1 (`min_gap` manifold3d na obróconej geometrii; te same siatki w układzie lokalnym 0.16 s). < 5 s, ale do poprawy w zadaniu 4 (np. przegląd w układzie wyrównanym z osią przegubu).
3. Mikro-„wióry” z przyciągania współrzędnych świata do 0.001 mm dają fałszywe przewieszenia (D7); agent wpisujący współrzędne trafi na to samo. Zadanie 4: progi rozmiaru cech.
4. Bramki w devgrade to wciąż przybliżenia dev; brak stref keep-in pokrywy (zawiasy, żebra, rama), edycje pokrywy nie są bramkowane.
5. L3: 6/10 seedów wymaga zastąpienia (seed + 1000k), bo przy 3 niezależnych żebrach częściej któreś jest nienaprawialne.
6. Testy trwają 5.3 min; warto oznaczyć wolne testy (`-m slow`) przed zadaniem 4.
7. Tekst S3 w `scenario.json` („the smallest valid relief per rib”) zdradza poprawkę; instruction.md (zadanie 7) musi używać reguły z brief.py.
8. Repo nie było gitem: zrobiłem `git init` + commit bazowy (D1).

**Decyzje**: `docs/DECISIONS.md` (D1-D9: m.in. 2 lub 3 żebra w L1/L2, losowanie L3, poza, „najgorsze żebro”, spawanie siatki 1e-6 mm, kształt narzędzia, zmiany starych testów).

**Propozycje zmian spec** (w DECISIONS, `scenario.json` nietknięty):
- P1: „three identical ribs” w L1/L2 → „two or three” (8/10 seedów ma 2 żebra).
- P2: L1 4×/8× nie daje pełnych punktów całej krawędzi na 5/10 seedów → 5×/10×.
- P3: L3 ograniczyć losowanie przez V_identical / V_ref ≥ 1.4 (nagroda ≤ 0.82) zamiast max/min ≥ 1.5.
- P4: podcięcia „dokładnie na długość żebra” dostają 0, a nie częściowy kredyt (informacyjnie).

---

Wpisy po każdym zakończonym zadaniu z docs/TASKS.md (najnowsze na dole).

## Zadanie 1: szkielet repo + CadQuery w Dockerze (2026-11-14)

**Zrobione**
- Szkielet pakietu zgodny z `CLAUDE.md`: `cadfix/{core,checks,ops,env,harbor}`, `scenarios/hinge_lid`, `tests/`. Moduły puste (tylko docstringi).
- `pyproject.toml` (luźne zakresy) + `requirements.lock` (pełny `pip freeze`, 77 pakietów). Docker instaluje dokładnie lock.
- `Dockerfile`: `python:3.11-slim` przypięty po digeście (Debian 13 trixie, Python 3.11.18). Pakiety systemowe tylko `libgl1`, `libx11-6`, `libexpat1`, wyznaczone przez `ldd` na wszystkich `.so` w site-packages. Pozostałe nierozwiązane zależności to opcjonalne wtyczki (komercyjne solvery casadi, most MATLAB, pule wątków numba TBB/OpenMP), których nie ładujemy.
- `pip --retries 5` + timeout 120 s: duże koła (vtk, cadquery-ocp) zrywały się na PyPI przy pierwszej próbie.
- Pakiet instalowany jako editable, więc `-v "$PWD":/app` działa bez przebudowy.
- `cadfix/smoke.py` + `tests/test_smoke.py`: box 40×30×20, fillet r=3 na jednej pionowej krawędzi, eksport STEP, import, tesselacja (tol 0.01 mm), przyciąganie do 0.001 mm i sklejenie wierzchołków, manifold3d.

**Wersje**: cadquery 2.8.0, cadquery-ocp 7.9.3.1.1, vtk 9.6.2, manifold3d 3.5.5, trimesh 5.2.1, numpy 2.4.6, scipy 1.17.1, shapely 2.2.0, mcp 1.30.0, pytest 9.2.0.

**Komendy**
```bash
docker build -t cadfix-dev .
docker run --rm cadfix-dev pytest -q
docker run --rm cadfix-dev python -m cadfix.smoke
```

**Wyniki**
- Build od zera: 215.5 s, obraz 2.23 GB (vtk ~640 MB i casadi ~280 MB przychodzą jako zależności cadquery).
- `pytest -q`: 1 passed in 1.15 s.
- Objętości: B-rep (OCC) 23961.3717 mm³, siatka (manifold3d) 23961.3207 mm³, różnica 0.0002% (próg 0.1%). Analitycznie 24000 − 9·(1−π/4)·20 = 23961.37 mm³. Siatka: 140 trójkątów, status NoError.

**Otwarte problemy**
- Obraz 2.2 GB. Dla obrazu Harbora (agent) można później spróbować odchudzić (np. bez vtk), ale cadquery-ocp wymaga vtk jako zależności pip.
- Tesselacja OCC jest per ściana; spawanie wierzchołków przez przyciąganie do 0.001 mm działa tu, ale przy bardzo małych cechach (< 0.001 mm) mogłoby zapadać trójkąty. Do sprawdzenia przy prawdziwej geometrii zawiasu.

## Zadanie 2: geometria hinge_lid dla seeda + „czy naprawdę koliduje?” (2026-11-14)

**Zrobione**
- `cadfix/core/kernel.py` (ogólne, bez wiedzy o zawiasach): `to_manifold` (tesselacja + przyciąganie do 0.001 mm, przeniesione ze `smoke.py`), `rotation_matrix`/`rotate`/`rotate_points` (oś przez punkt, reguła prawej dłoni), `intersection` (objętość + bbox, próg `VOL_EPS` = 1e-3 mm³), `intersection_components`, `export_step`/`import_step`.
- `scenarios/hinge_lid/generator.py`: `HingeLidParams`, `sample_params(seed)` (losowanie z odrzucaniem w obrębie seeda, numer próby zapisany), `feasibility(p)` (analitycznie), `build_parts(p)` (CadQuery), `write(seed, out)` → 4 pliki STEP + `params.json` (parametry, przegub, segmenty zawiasu, objętości, feasibility).
- `scenarios/hinge_lid/dev_sweep.py`: części wczytane ze STEP, obrót pokrywy i modułu 0..110° co 1°, kolizje z obudową i sworzniem (każdy rozłączny kawałek kolizji osobno), potem prawdziwe fazowanie B-rep (OCC `BRepFilletAPI_MakeChamfer`, asymetryczne, krawędź znaleziona geometrycznie) o rozmiarze z feasibility i ponowny obrót. `--glb` zapisuje sceny (zamknięta / pierwsza kolizja / 110°, kolizja na czerwono), `--show` używa `ocp_vscode`, jeśli jest.
- Testy: `tests/test_kernel.py` (6), `tests/test_hinge_lid.py` (6 × seedy 0..9).

**Decyzja geometryczna (zatwierdzona przez użytkownika)**: pokrywa drukuje się górą w dół (scenario.json S2), więc zawiasy pokrywy muszą być pod jej górną powierzchnią → oś tylko 0.4–0.8 mm nad górą ścianki. Żeby kolizja wypadła w 30–100°, kolidujący materiał musi wisieć mniej więcej pionowo pod osią: jest to **występ (lug) pod każdym zawiasem pokrywy**, za tylną ścianką (jak za długi ogranicznik otwarcia). Zawiasy obudowy są przyczepione do zewnętrznej ściany tylnej PONIŻEJ wolnego pasa 4 mm, więc zewnętrzna górna krawędź tylnej ścianki to jedna ciągła krawędź (pod `chamfer(edge)` w zadaniu 5).

Wymiary: pokrywa 3 mm, zawias r 2.2, sworzeń Ø1.75 (filament), otwory Ø2.0 (luz promieniowy 0.125), szczeliny osiowe 0.4, 5 lub 7 zawiasów. Losowane: L 60–100, W 40–70, H 22–35, ścianka 2.4–3.0, oś a = 2.7–3.2 za ścianką, b = 0.4–0.8 nad nią, występ (szerokość, przesunięcie, głębokość wejścia 0.2–0.45 mm za krawędź), moduł.

Feasibility: R = największy promień materiału pokrywy, który wchodzi w ściankę; wymagane Rc = R + 0.3; usunięcie w okręgu Rc (szerokość na górze, głębokość z boku); fazowanie styczne do okręgu Rc o najmniejszym polu, z zapasem uszczelki ≥ 0.15 mm i bokiem ≤ wolny pas − 0.5; nogi zaokrąglone w górę do 0.01 i sprawdzone ponownie; przewidywany kąt pierwszej kolizji (2D, siatka 0.01°) musi być w [40, 95].

**Komendy**
```bash
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev pytest -q
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m scenarios.hinge_lid.generator --seeds 0-9 --out output/hinge_lid
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m scenarios.hinge_lid.dev_sweep --seeds 0-9 --out output/hinge_lid [-v] [--glb]
```

**Wyniki** (seedy 0..9)

| seed | kolizja przy 0° | przewidywany / zmierzony 1. kąt | max obj. kolizji mm³ | wszystko przy krawędzi | fazowanie góra × bok | uszczelka po | kolizje po fazowaniu |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 56.4 / 57 | 4.745 | tak | 0.92 × 2.08 | 1.81 | 0 |
| 1 | 0 | 42.1 / 43 | 1.966 | tak | 0.75 × 1.89 | 1.98 | 0 |
| 2 | 0 | 46.0 / 47 | 2.603 | tak | 0.83 × 1.70 | 1.73 | 0 |
| 3 | 0 | 56.5 / 57 | 1.546 | tak | 0.70 × 1.76 | 1.88 | 0 |
| 4 | 0 | 49.5 / 50 | 2.365 | tak | 0.71 × 1.51 | 2.21 | 0 |
| 5 | 0 | 57.6 / 58 | 1.009 | tak | 0.63 × 1.58 | 2.30 | 0 |
| 6 | 0 | 70.5 / 72 | 1.700 | tak | 0.81 × 1.81 | 2.00 | 0 |
| 7 | 0 | 40.0 / 41 | 3.152 | tak | 0.88 × 1.90 | 2.00 | 0 |
| 8 | 0 | 46.9 / 48 | 2.963 | tak | 0.82 × 1.88 | 1.80 | 0 |
| 9 | 0 | 48.0 / 49 | 4.166 | tak | 0.77 × 2.67 | 1.65 | 0 |

- Sworzeń vs obudowa i vs pokrywa: 0 na wszystkich kątach. Jedyna kolidująca para to pokrywa × obudowa (moduł nigdy).
- Każdy kawałek kolizji leży w strefie analitycznej przy zewnętrznej górnej krawędzi tylnej ścianki (np. seed 0: y 57.762–58.2, z 30.256–31.5 przy W = 58.2, H = 31.5) i w obrębie jednego segmentu zawiasu pokrywy.
- Objętość usunięta przez fazowanie B-rep = analityczna ½·d_top·d_side·L (np. 81.806 mm³), 0.15–0.27 % objętości obudowy (S3: < 1 %).
- Pułapka działa: symetryczne fazowanie 45° wystarczające do usunięcia kolizji (1.42–1.83 mm) niszczy uszczelkę na 9 z 10 seedów.
- Obrót 0..110° (111 kroków, 4 pary): 0.08–0.11 s na seed. `pytest -q`: 67 passed w 8.7 s. Generowanie 10 seedów ~6 s.

**Otwarte problemy**
- Kąty pierwszej kolizji skupione w 40–72° (okno feasibility to 40–95). Można przesunąć rozkład przesunięcia występu, jeśli chcemy więcej rozrzutu.
- Zapas uszczelki bywa mały (seed 9: 0.15 mm), to jest „tight window” z scenario.json. Na niższy poziom trudności trzeba będzie go poszerzyć.
- `ocp_vscode` nie jest w obrazie (wymaga VS Code na hoście); do oglądania są pliki `.glb`.
- `.pytest_cache` z zadania 1 należy do roota, więc pytest z `-u` pokazuje ostrzeżenie o cache (nieszkodliwe; `sudo rm -rf .pytest_cache` je usuwa).

## Zadanie 2b: luz przy otwieraniu + najmniejsze fazowanie + progi S3 (2026-11-14)

**Przebieg decyzji**
- Wersja 0.4 (okno ogranicznika [110, 130]) porzucona: analiza 2D pokazała, że z tym żebrem (lug) żadne fazowanie obudowy nie daje pierwszego kontaktu ≥ 110° (najpóźniej 56–105°, większe fazowania = brak kontaktu). Szczegóły w `scenario.json` → `decision_log`.
- Wersja 0.5: żebro to element konstrukcyjny (keep-in), bez funkcji ogranicznika. S1 = brak nakładania (> 1e-3 mm³) od 0 do 110° (styk dozwolony) i luz ≥ 0.3 mm od 10 do 110° (przy 0° pokrywa leży na uszczelce, luz przy podnoszeniu rośnie ~a·θ i osiąga 0.3 mm dopiero przy 5–7°). Sworzeń wyłączony z luzu (otwory mają celowo 0.125 mm). S3: pełne punkty do 1.25·V_best, zero przy 3·V_best. Nagroda przy spełnionym S1: 0.4 + 0.2·printability + 0.4·minimal_change.

**Zrobione**
- `cadfix/core/kernel.py` (ogólne): `first_contact_sweep` (przegub obrotowy, kroki 1°, doprecyzowanie co 0.1°, zwraca kąt / None, objętość, bbox i wszystkie stykające się pary), `clearance_sweep` (min. luz na krok przez `Manifold.min_gap` z promieniem szukania, para, objętość nakładania: styk ≠ kolizja), `changed_volume`, `box_overlap_volume`, `downward_area`; `intersection_components(min_volume=...)`.
- `cadfix/core/reward.py`: `linear_score`, `progress`, `RewardPolicy` (bramki → 0, cel niespełniony → waga·postęp, spełniony → baza + ważone wyniki). Liczby podaje scenariusz (`generator.REWARD_POLICY`).
- `scenarios/hinge_lid/generator.py`: dokładny skan 2D (shapely): przekrój pokrywy w segmencie zawiasu pokrywy (płyta, ogon, zawias, żebro, rama, moduł) obrócony co 1° i zsumowany osobno dla 0..9° (test nakładania) i 10..110° (test luzu), ściana tylna z fazowaniem; siatka top × side co 0.05 mm, top ≤ t − 1.8 (zapas uszczelki ≥ 0.3, ścianka ≥ 1.2), side ≤ free_band − 0.5 = 3.5. S1 jest monotoniczne w side, więc dla każdego top bisekcja minimalnego side. Wynik w `params.json`: V_best i jego fazowanie, zakres top, przedział side przy środkowym top (+ podprzedział z pełnymi punktami S3), najmniejsze symetryczne 45° przechodzące S1, `spec` (parametry S1, progi S3 w % objętości obudowy, wagi nagrody), strefy keep-in wsporników zawiasów obudowy. Pusty zbiór → seed + 1000·k, zapisane w `source_seed` / `rejected_source_seeds`. Skan 0.1–0.34 s na seed.
- `scenarios/hinge_lid/dev_sweep.py` przepisany: pierwszy kontakt oryginału (0..180°) + 5 wariantów obudowy z prawdziwym fazowaniem B-rep (oryginał, best, 0.7× side, 2× side, symetryczne), dla każdego S1, bramki (wersja dev: poprawna bryła, szerokość uszczelki ≥ 1.5, wsporniki wypełnione ≥ 99 %, pozycja zamknięta), printability, S3 i nagroda. Gdy operacja fazowania OCC się nie uda, to samo cięcie robione jest booleanem i oznaczone w tabeli.
- Testy: 107 (kernel +6, reward 3 nowe, hinge_lid przepisany: m.in. „best jest ciasne”, tzn. side − 0.05 przy tym samym top nie przechodzi S1 w 3D na każdym seedzie).

**Komendy**
```bash
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev pytest -q
rm -rf output/hinge_lid   # dev_sweep generuje tylko brakujące seedy
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m scenarios.hinge_lid.generator --seeds 0-9 --out output/hinge_lid
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m scenarios.hinge_lid.dev_sweep --seeds 0-9 --out output/hinge_lid [-v] [--glb]
```

**Wyniki: oryginał, skan, progi S3** (seed 9 zastąpiony: 9 i 1009 mają pusty zbiór, użyty 2009)

| seed | 1. kontakt pred / 3D | para | w strefie | best top × side | V_best mm³ | S3 pełne ≤ / zero ≥ (% obudowy) | top ważne | side przy środkowym top (pełne pkt) | szerokość |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 56.4 / 56.7 | lid × enclosure | tak | 0.90 × 2.15 | 82.72 | 0.306 / 0.734 | 0.80–0.90 | 2.30–3.50 (2.30–2.80) | 0.50 |
| 1 | 42.1 / 42.4 | lid × enclosure | tak | 0.75 × 1.90 | 57.36 | 0.228 / 0.547 | 0.65–0.90 | 1.80–3.50 (1.80–2.20) | 0.40 |
| 2 | 46.0 / 46.3 | lid × enclosure | tak | 0.75 × 2.00 | 52.88 | 0.339 / 0.813 | 0.70–0.75 | 2.00–3.50 (2.00–2.50) | 0.50 |
| 3 | 56.5 / 56.9 | lid × enclosure | tak | 0.70 × 1.75 | 54.82 | 0.231 / 0.553 | 0.60–0.75 | 1.75–3.50 (1.75–2.15) | 0.40 |
| 4 | 49.5 / 49.8 | lid × enclosure | tak | 0.70 × 1.55 | 53.00 | 0.189 / 0.454 | 0.65–1.10 | 1.40–3.50 (1.40–1.50) | 0.10 |
| 5 | 57.6 / 58.0 | lid × enclosure | tak | 0.60 × 1.65 | 47.47 | 0.183 / 0.438 | 0.55–1.10 | 1.45–3.50 (1.45–1.45) | 0.00 |
| 6 | 70.5 / 71.1 | lid × enclosure | tak | 0.80 × 1.85 | 60.31 | 0.255 / 0.611 | 0.70–1.00 | 1.75–3.50 (1.75–2.15) | 0.40 |
| 7 | 40.0 / 40.3 | lid × enclosure | tak | 0.90 × 1.85 | 70.76 | 0.300 / 0.720 | 0.75–1.05 | 1.85–3.50 (1.85–2.30) | 0.45 |
| 8 | 46.9 / 47.2 | lid × enclosure | tak | 0.80 × 1.95 | 72.23 | 0.284 / 0.681 | 0.70–0.80 | 2.15–3.50 (2.15–2.60) | 0.45 |
| 9 (2009) | 53.8 / 54.1 | lid × enclosure | tak | 0.75 × 1.90 | 67.33 | 0.266 / 0.637 | 0.65–0.85 | 1.90–3.50 (1.90–2.35) | 0.45 |

Górna granica side 3.50 to limit skanu (free_band − 0.5), nie S1: większe side zawsze przechodzi S1, karze je tylko S3.

**Wyniki: warianty 3D** (S1 do kąta / min. luz 10–110° / nagroda)

| seed | oryginał | best | 0.7× side | 2× side | symetryczne 45° |
|---|---|---|---|---|---|
| 0 | 45° / 0 / 0.000 | 110 / 0.308 / **1.000** | 46° / 0.119 / 0.005 | 110 / ≥0.35 / S3 0.571 → **0.829** ¹ | 1.80: uszczelka 0.93 → 0 |
| 1 | 32° / 0 / 0.000 | 110 / 0.305 / **1.000** | 32° / 0.130 / 0.000 | S3 0.571 → **0.829** | 1.70: 1.03 → 0 |
| 2 | 36° / 0 / 0.000 | 110 / 0.304 / **1.000** | 36° / 0.195 / 0.000 | S3 0.571 → **0.829** ¹ | 1.55: 1.01 → 0 |
| 3 | 45° / 0 / 0.000 | 110 / 0.304 / **1.000** | 45° / 0.132 / 0.000 | S3 0.571 → **0.829** | 1.55: 1.03 → 0 |
| 4 | 39° / 0 / 0.000 | 110 / 0.307 / **1.000** | 39° / 0.148 / 0.000 | S3 0.571 → **0.829** | 1.40: 1.52 → **0.873** ² |
| 5 | 45° / 0 / 0.000 | 110 / 0.301 / **1.000** | 45° / 0.170 / 0.000 | S3 0.571 → **0.829** | 1.45: 1.48 → 0 |
| 6 | 54° / 0 / 0.000 | 110 / 0.306 / **1.000** | 75° / 0.129 / 0.113 | S3 0.571 → **0.829** | 1.60: 1.21 → 0 |
| 7 | 31° / 0 / 0.000 | 110 / 0.301 / **1.000** | 31° / 0.080 / 0.000 | S3 0.571 → **0.829** | 1.70: 1.18 → 0 |
| 8 | 37° / 0 / 0.000 | 110 / 0.307 / **1.000** | 37° / 0.136 / 0.000 | S3 0.571 → **0.829** | 1.65: 0.97 → 0 |
| 9 | 43° / 0 / 0.000 | 110 / 0.302 / **1.000** | 43° / 0.128 / 0.000 | S3 0.572 → **0.829** | 1.70: 0.98 → 0 |

- best: zapas uszczelki 0.31–0.83 mm, ścianka 1.81–2.33 mm, zmieniona objętość 0.146–0.271 % obudowy (= 0.8 × próg pełnych punktów), S3 = 1, printability = 1, wsporniki 100 %.
- Luz 2D vs 3D dla best: 0.3005–0.3076 vs 0.301–0.308 (różnica ≤ 0.001 mm), żadna decyzja się nie odwraca. „side − 0.05” nie przechodzi S1 w 3D na żadnym seedzie.
- Kontakt oryginału: tylko para pokrywa × obudowa, po jednym kawałku na segment zawiasu pokrywy, wszystkie przy zewnętrznej górnej krawędzi tylnej ścianki. Sworzeń i moduł nigdy.
- Czas: przegląd S1 (111 kroków) 0.09–0.16 s, pierwszy kontakt 0..180° 0.03–0.06 s, cała tabela 10 seedów ~14 s, `pytest -q`: 107 passed w 23 s.

¹ Seedy 0 i 2: side 2× = 4.30 / 4.00 ≥ free_band 4.0, więc fazowanie OCC się nie udaje (agent dostałby błąd narzędzia). To samo cięcie booleanem ścina tylko korzeń wspornika (wypełnienie 99.97 % / 100 % ≥ 99 %), więc bramka wsporników przechodzi. Na żadnym seedzie 2× nie tnie wsporników ponad tolerancję 1 %; ścieżka „wsporniki ścięte → 0” nie zadziałała w tym zestawie (prawdopodobnie zadziała przy 3×, side 4.6–6.5 mm; nie testowane).
² Seed 4: najmniejsze symetryczne przechodzące S1 (1.40 mm) zostawia uszczelkę 1.52 mm ≥ 1.5, więc bramka przechodzi i nagroda to 0.873. Symetryczne pada na uszczelce na 9/10 seedów (jak w zadaniu 2).

**Otwarte problemy**
- Za małe fazowanie (0.7× side) dostaje praktycznie 0 (8/10 seedów 0.000, max 0.113): luz spada poniżej 0.3 mm przy tym samym kącie co w oryginale, bo żebro najpierw zbliża się do nieściętej ściany zewnętrznej poniżej małego fazowania. Własność „≤ 0.3” jest spełniona, ale częściowego kredytu prawie nie ma. Do decyzji w zadaniu 4: czy postęp liczyć gładziej (np. z min. luzu albo objętości nakładania).
- Okno pełnych punktów S3 przy środkowym top jest wąskie: 0.00–0.50 mm side (seed 5: jedna wartość 1.45, seed 4: 0.10 mm). Przy top z V_best szerokość to zawsze side_best·0.25 (0.39–0.54 mm).
- Bramki w tabeli są przybliżeniami dev (uszczelka = t − top, wsporniki = pudełka keep-in, przewieszenia = nowa powierzchnia skierowana w dół); prawdziwe ogólne checki to zadanie 4.
- Nazwy pól `lug_*` w params zostały (to żebro z wersji 0.5); zmiana nazw przy zadaniu 4/7, jeśli params będą publiczne.

## Drobne zadanie dev: brief.py + evaluate.py (2026-11-14)

- `scenarios/hinge_lid/brief.py --seed N`: to, co agent wie po obejrzeniu seeda narzędziami: zgłoszenie błędu, spec z `scenario.json` (S3 jako progi % dla seeda), układ współrzędnych, przekrój tylnej ściany, oś zawiasu, przekrój pokrywy przy zawiasie (narożniki żebra względem osi), strefy, zmierzony obrót oryginału (pierwszy kontakt 56.7°, bbox, S1 do 45°). Bez wyników skanu feasibility.
- `scenarios/hinge_lid/evaluate.py --seed N --top T --side S [--symmetric]`: jedno fazowanie B-rep → raport w stylu test_fit + nagroda. Seed 0, best 0.9 × 2.15: S1 PASS, min. luz 0.308 mm przy 88°, zapas uszczelki +0.330, ścianka 1.83, 0.2445 % (pełne ≤ 0.3056 %), S3 1.000, nagroda 1.000.
- Test `tests/test_dev_scripts.py` (brief nie zawiera „chamfer”, V_best ani wymiarów best; evaluate best = 1.0). `pytest -q`: 109 passed.
- Uwaga dla zadania 7: tekst S3 w `scenario.json` („the smallest valid chamfer”) oraz `reward.reference_points` / `properties` zdradzają poprawkę; brief (i później instruction.md) używa neutralnego sformułowania S3 i ich nie pokazuje.
- Brak: współrzędne stref keep-in dla zawiasów i żeber pokrywy, ramy modułu i uszczelki (w params są tylko wsporniki obudowy); do dodania w zadaniu 4.

## Zadanie 2c (poziomy L1-L3), notatki z kamieni milowych

### M1: poziomy w generatorze (2026-11-14)
- `generator.py`: `level` w parametrach, wyjście `output/hinge_lid/<L>/seed_NNNN/`. L1 i L2 mają identyczne części jak w 2b (sprawdzone: parametry, najlepsze fazowanie i symetryczne 45° identyczne ze starymi `params.json` na seedach 0-9, seed 9 dalej → 2009).
- L3: zawsze 7 zawiasów = 3 żebra, każde losowane osobno (głębokość, przód/tył), osobny strumień losowy. Ograniczenia: każde żebro koliduje (okno 40-95°), każde naprawialne (skan 2D per żebro, pusty → seed + 1000k), potrzebne objętości różnią się ≥ 1.5x (redraw). Poza: yaw 15-40°, tilt 0-8°, offset 20-200 mm; części, oś, strefy (prostopadłościany zorientowane), orientacje druku w świecie; poza zapisana w `params.json`. Feasibility w układzie lokalnym.
- Znalezisko: przyciąganie wierzchołków siatki do 0.001 mm w obróconym układzie dawało fałszywe nakładanie pokrywy na uszczelce przy 0° (0.01-0.21 mm³ na 10/10 seedów L3). Spawanie siatki teraz co 1e-6 mm (DECISIONS D6).
- Testy: `tests/test_levels.py` (L2 = L1, żebra L3, spójność układu świata, oryginał L3 zacina się na każdym żebrze i nigdzie indziej). `pytest -q`: 149 passed.

### M2: ogólne extrude_cut + operacje w evaluate (2026-11-14)
- `cadfix/ops/edit.py` (bez nazw z zawiasu): `chamfer(edge_near, d1, d2, d1_face_normal, edge_direction)` i `extrude_cut(origin, normal, x_dir, polygon_2d, depth_from, depth_to)` (y_dir = normal × x_dir), `apply_op` / `apply_ops` dla list słowników JSON. Walidacja z czytelnymi błędami (np. „x_dir must be perpendicular…”, „no edge within 1.0 mm… nearest edge is…”, „ambiguous…”, „would split the part into 2 separate solids”, „removed no material”). Punkty i długości przyciągane do 0.001 mm.
- `scenarios/hinge_lid/devgrade.py`: wspólny grader dev. Bramki mierzone na geometrii, a nie z rozmiaru fazowania: szerokość uszczelki = najmniejsza szerokość pierścienia ścian górnych (erozja), najcieńsza ścianka z przekrojów poziomych, wsporniki jako zorientowane prostopadłościany, przewieszenia względem kierunku druku części.
- `evaluate.py`: `--ops` (plik albo tekst JSON), `--top/--side` jako skrót (ta sama operacja), `--level`, `--hide-score` (bez REWARD, S3 tylko usunięta objętość i %).
- Kontrola: L1 seed 0, 0.9 × 2.15 przez nową ścieżkę = dokładnie liczby z 2b (S1 PASS, 0.308 mm przy 88°, uszczelka +0.330, ścianka 1.830, 0.2445 %, nagroda 1.000). Ręczne 3 lokalne podcięcia (żebro ± 0.35 mm): S1 PASS, 0.308 mm, 25.83 mm³ zamiast 82.72.
- `pytest -q`: 157 passed (nowe `tests/test_ops.py`, testy evaluate).

### M3: feasibility per żebro i objętości odniesienia (2026-11-14)
- Skan 2D per żebro (top × side co 0.05, S1 dla tego żebra, zapas uszczelki ≥ 0.3, ścianka ≥ 1.2) na zakresie x żebra ± 0.35 mm. V_ref = suma najmniejszych podcięć; zapisane też V_full_edge (najmniejsze fazowanie całej krawędzi ważne dla wszystkich żeber) i V_identical (ten sam profil na każdym żebrze, DECISIONS D5).
- Luz na końcach wzdłuż x sprawdzany w 3D na prawdziwym B-rep w `resolve_seed` (D8); nigdy nie zawiódł na seedach 0-9.
- Poprawka odniesienia zapisana jako operacje `extrude_cut` w formacie evaluate (`reference_ops` w układzie świata, `feasibility.reference.ops_local`); tylko do oceny i testów.
- Znalezisko: trójkątny przekrój narzędzia zostawiał w obróconym układzie mikroskopijny „wiór” nad narzędziem → fałszywe przewieszenie 0.21 mm² (D7). Narzędzie jest teraz pięciokątem.
- V_full_edge / V_ref: L1/L2 3.2-4.7×, L3 3.8-5.3×; V_identical / V_ref w L3: 1.16-1.39.
- `pytest -q`: nowe `tests/test_reference.py` (60 testów, wszystkie poziomy × seedy 0-9).

### M4: nagroda 0.6 (2026-11-14)
- `cadfix/core/reward.py`: `ratio_score` (S3 jako krotność V_ref), `sweep_progress` (0.5 · postęp kąta + 0.5 · postęp luzu, luz 0 przy jakimkolwiek nakładaniu).
- `generator.py`: `REWARD_POLICY` = 0.25 · postęp / 0.3 + 0.1 · printability + 0.6 · minimal_change; `S3_FACTORS` L1 (4, 8), L2/L3 (1.15, 2). Test sprawdza, że liczby zgadzają się z tekstem w `docs/scenario.json`. `spec.S3` w params: V_ref, czynniki, progi w mm³ i %.
- `devgrade.py` liczy S3 = f(zmieniona objętość / V_ref), postęp S1 jak w spec. `dev_sweep.py` przepisany na 7 wariantów z M6 (operacje), stare testy 2b przeniesione (zmiany i powody: DECISIONS D9).
- Punkty odniesienia: poprawka odniesienia 1.0, działająca, ale rozrzutna 0.4, zepsuta < 0.25, nic nie robić 0. L1, fazowanie całej krawędzi: 0.897-1.0 (5/10 seedów > 4 × V_ref; propozycja P2).
- `pytest -q`: 221 passed.

### M5: brief.py per poziom (2026-11-14)
- `brief.py --seed N --level L`: S3 tylko jako reguła („full points if the changed volume is within 1.15x of the best known fix for this task, zero at 2x”), bez objętości i procentów odniesienia. L1/L2 jak dotąd (x/y/z). L3 wyłącznie w układzie świata: płaszczyzny ścian (punkt + normalna), krawędzie (końce), oś, segmenty zawiasu na osi, narożniki każdego żebra w świecie z odległością od osi, strefy jako zorientowane prostopadłościany. Bez pozy i bez układu lokalnego.
- Test wycieków dla L1/L2/L3 (seedy 0-2): brak słów naprawy (chamfer, relief, notch, V_ref, local, per rib, …, także pose/yaw/tilt) i liczb ze skanu (objętości, pary top × side, progi S3). Sprawdzone też ręcznie na wszystkich 30 briefach; pojedyncze nogi podcięcia pomijam w teście, bo przypadkiem pokrywają się z publiczną geometrią (np. 2.2 = promień zawiasu).
- `pytest -q`: 230 passed.

### M6: tabele akceptacyjne 3D (2026-11-14)
- `python -m scenarios.hinge_lid.dev_sweep --level L1,L2,L3 --seeds 0-9`: 30 seedów × 7 wariantów jako prawdziwe operacje B-rep, 342 s. Pełny wynik: `docs/acceptance_2c.txt`, streszczenie na górze tego pliku.
- Oczekiwania vs rzeczywistość: oryginał 0 ✓ (30/30); odniesienie 1.0 ✓ (30/30); 0.7× side < 0.25 ✓ (max 0.110); L1 fazowanie całej krawędzi ~1.0: 0.897-1.0 (5/10 = 1.0); L2/L3 fazowanie całej krawędzi 0.400 ✓ (20/20); podcięcia dokładnie na długość żebra: S1 FAIL ✓ (30/30, nagroda 0); **L3 identyczne podcięcia „wyraźnie < 0.9”: NIE** - 0.829-0.993, średnio 0.903, tylko 4/10 < 0.9 (propozycja P3). Sworzeń, moduł, wsporniki: 0 kolizji we wszystkich 210 wariantach ✓.
- Czas przeglądu S1 dla L3: 1.6-2.2 s na wariant (L1: 0.09-0.17 s). Te same siatki przeniesione do układu lokalnego: 0.16 s, więc to `min_gap` manifold3d na obróconej geometrii, nie liczba trójkątów (ta sama). Poniżej 5 s, ale do poprawy w zadaniu 4.
- Testy: `tests/test_acceptance.py` (seedy 0-1 na poziom). `docs/examples/L2_seed0_reference.json`, `docs/examples/L3_seed0_reference.json`.

### M7: podsumowanie (2026-11-14)
- CLAUDE.md: komendy per poziom (generator, brief, evaluate z operacjami JSON, tabele dev_sweep), link do DECISIONS. Podsumowanie 2c na górze tego pliku. Przykłady operacji: `docs/examples/L2_seed0_reference.json`, `docs/examples/L3_seed0_reference.json` (evaluate: nagroda 1.000 / S1 PASS 0.302 mm).

## Zadanie 2d: poprawki po 2c, scenario.json 0.7-levels-tuned (2026-11-15)

**Zrobione**
- P2: L1 S3 4×/8× → **5×/10×** (`generator.S3_FACTORS`, tekst w `scenario.json`). Fazowanie całej krawędzi w L1 (3.20-4.68 × V_ref) ma teraz pełne punkty na 10/10 seedów (było 5/10, min 0.897).
- P3: losowanie L3 przyjmuje próbę tylko, gdy **V_identical / V_ref ≥ 1.4** (`L3_MIN_IDENTICAL_RATIO`), zamiast „max/min ≥ 1.5”. Warunek na płytę pokrywy zostaje.
- Znalezisko przy P3: odniesienie L3 na seedach 0 i 1 nie przechodziło S1 w układzie świata (nagroda 0.221 / 0.149): luz 2D 0.3002 / 0.3001 mm, po obrocie i przyciągnięciu do 0.001 mm odczyt tuż pod 0.3. W 0.6 trzy odniesienia L3 też miały 0.300 i przechodziły przypadkiem. Poprawka: skan 2D w L3 wymaga luzu ≥ 0.3 + 0.002 mm (`L3_SCAN_CLEARANCE_MARGIN`, DECISIONS D10). Próg gradera dalej 0.3, L1/L2 bez zmian.
- `scenario.json`: wersja `0.7-levels-tuned`, dwa wpisy „0.7” w decision_log, tekst L1 S3, opis losowania L3, oczekiwanie dla identycznych podcięć („<= ~0.82”). Plik na dysku był jeszcze 0.6, więc te zmiany wpisałem sam (patrz otwarte problemy).
- Wolne testy oznaczone `@pytest.mark.slow` (`tests/marks.py`, marker w `pyproject.toml`): cały `test_acceptance.py`, seedy 1-9 testów wieloseedowych, L3 poza `test_levels` seed 0. Komendy w CLAUDE.md.
- Odświeżone: `docs/acceptance_2c.txt` (L1 i L3 nowe, L2 z 2c bez zmian), `docs/examples/L3_seed0_reference.json` (evaluate: S1 PASS, nagroda 1.000), testy M6 (`test_acceptance.py`) i testy z liczbami 4/8 (`test_hinge_lid.py`, `test_reward.py`, `test_levels.py`).

**Komendy**
```bash
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev pytest -q -m "not slow"   # szybko
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev pytest -q                  # całość
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/app cadfix-dev python -m scenarios.hinge_lid.dev_sweep --level L1,L3 --seeds 0-9 --out output/hinge_lid
```

**Wyniki**
- `pytest -q -m "not slow"`: 48 passed, 197 deselected, **42.9 s**. `pytest -q`: **245 passed, 1158.5 s** (19:18; przed 2d 320 s, wzrost przez wolniejsze losowanie L3).
- Zastąpienia seedów L3: **8/10** (było 6/10); bez zastąpienia tylko 4 i 8. Seed źródłowy: 0→2000, 1→2001, 2→7002, 3→**16003** (16 odrzuconych), 5→6005, 6→6006, 7→9007, 9→3009. L1: bez zmian (9→2009).
- L3, identyczne podcięcia (3D, prawdziwe operacje):

| seed | src | V_ref mm³ | ident/ref | nagroda ident. | full/ref |
|---|---|---|---|---|---|
| 0 | 2000 | 15.91 | 1.464 | 0.778 | 5.81 |
| 1 | 2001 | 17.54 | 1.464 | 0.778 | 5.71 |
| 2 | 7002 | 19.36 | 1.404 | 0.821 | 4.92 |
| 3 | 16003 | 12.31 | 1.448 | 0.791 | 5.82 |
| 4 | 4 | 14.67 | 1.433 | 0.801 | 5.17 |
| 5 | 6005 | 19.71 | 1.411 | 0.816 | 4.35 |
| 6 | 6006 | 17.72 | 1.459 | 0.782 | 5.35 |
| 7 | 9007 | 15.18 | 1.430 | 0.803 | 5.42 |
| 8 | 8 | 12.40 | 1.445 | 0.791 | 5.00 |
| 9 | 3009 | 16.65 | 1.498 | 0.754 | 4.44 |

  Identyczne: 0.754-0.821, średnio 0.791, **10/10 < 0.9** (było 0.829-0.993, 4/10).
- Podsumowanie tabel: L1 odniesienie 1.0 / cała krawędź 1.0 / identyczne 1.0 (10/10); L3 odniesienie 1.0 (10/10, min luz 0.302 mm), cała krawędź 0.400 (10/10); oryginał 0, „długość = żebro” 0, 0.7× side ≤ 0.100 na obu poziomach; 0 kolizji sworzeń/moduł/wsporniki. L1 sym. 45° na seedzie 4 (jedyny, który przechodzi bramkę uszczelki): 0.696 → 0.877, przez łagodniejsze S3.
- Czas: dev_sweep L3 593.8 s (w 2c wszystkie 3 poziomy razem 342 s), generowanie L3 ~11 s na seed.

**Otwarte problemy**
1. `docs/scenario.json` na dysku był w wersji 0.6 (bez wpisów „0.7”), choć polecenie mówiło o 0.7. Wpisy 0.7 są moje: do przejrzenia.
2. Seed 3 L3 potrzebuje 16 zastąpień przy limicie `max_replacements=20`. Warunek 1.4× faworyzuje próby z jednym dużym żebrem, które częściej jest nienaprawialne, a każda taka próba kończy seed (reguła ze spec). Przy większej liczbie seedów (Harbor) limit może zostać przekroczony. Propozycja P5: w L3 żebro bez podcięcia → nowe losowanie w obrębie seeda, nie zastąpienie seeda.
3. Pełny `pytest -q` trwa 19 min, bo każdy moduł testów osobno generuje seedy L3. Pamięć podręczna generatora na sesję testów skróciłaby to kilkukrotnie (zadanie 4).
4. Zapas 0.002 mm (D10) to łatka na dokładność przyciągania współrzędnych; właściwe rozwiązanie to tolerancja pomiaru albo przegląd S1 w układzie osi przegubu (zadanie 4, razem z problemem 2 z 2c).

## Zadania 4-7 (praca autonomiczna, docs/TASK_4-7.md)

Plan: `docs/PLAN_4-7.md`. Projekt rozwiązania wzorcowego (M0): `docs/SOLVER_DESIGN.md`. Decyzje D11+ w `docs/DECISIONS.md`.

### M1 (zadanie 4): ogólne checki + nagroda z danych + grader CLI (2026-11-15)
- `cadfix/core`: `assembly.py` (Region: oriented box / cylinder, Zone, Joint, Part z leniwą siatką, Assembly z task.json), `registry.py` (CheckResult, CheckContext z cache oryginału, rejestr), `spec.py` (checki i nagroda z spec.json, koszt test_fit).
- `cadfix/checks`: valid_solid, interface_frozen, keep_in, keep_out, collision_free, sweep_clearance (opcjonalnie w układzie pudełka: L3 ~0.15 s zamiast 1.6-2.7 s), contact_width, min_wall i overhang (tylko NOWE wady względem oryginału, filtr 0.2 mm po grubości), volume_change, envelope.
- Generator: wszystkie strefy keep-in (zawiasy i żebra pokrywy, rama modułu, pas uszczelki na obu częściach, wsporniki) i keep-out (moduł) jako regiony świata; walce interfejsu zawiasu; osie pudełka; płaszczyzna szczytów ścian. `scenarios/hinge_lid/spec.py` = spec jako dane; `task.py` = zadanie publiczne (`task/`) + prywatne (`pristine/` z V_ref).
- `python -m cadfix.grade --task-dir T --pristine P --submitted S --level L --out report.json --reward-file reward.txt`: brak / śmieciowy plik -> oryginał (0), reward.txt zawsze, koszt test_fit z max(episode.json, actions.jsonl).
- devgrade/evaluate/dev_sweep/brief przepięte na nowe checki (stare przybliżenia usunięte).
- Akceptacja: `python -m scenarios.hinge_lid.acceptance --level L1,L2,L3 --seeds 0-9` -> `docs/acceptance_4.txt`, 203 s. **210 wariantów, 0 różnic** względem `docs/acceptance_2c.txt` (po dwóch poprawkach po drodze: pas uszczelki tylko jako wewnętrzny pierścień, D12; szczelina zerowej szerokości w kontakcie na L3 seed 4, D17; oraz filtr 0.2 mm po grubości zamiast po prostokącie, D15).
- Testy: nowe `tests/test_checks.py` (9), `tests/test_grade.py` (5), `tests/test_task.py` (2). `pytest -q -m "not slow"`: 63 passed, 52 s.

### M2 (zadanie 5): operacje, środowisko, serwer MCP (2026-11-15)
- `cadfix/ops/topology.py`: opisy krawędzi/ścian w świecie (id, typ, końce, długość, okrąg, sąsiednie ściany z normalnymi; ściany: środek, pole, bbox, normalna / oś i promień), `edges_near`, `faces_near`. Obudowa: 108 krawędzi, 43 ściany, 0.03 s.
- `cadfix/ops/edit.py`: + fillet, offset_face (płaska ściana, push/pull), cut_box / add_box (zorientowane), wybór krawędzi/ściany po id albo punkcie; rejestr `OP_SPECS` z opisem każdego parametru (z niego powstają narzędzia MCP).
- `cadfix/env/env.py`: stan epizodu, undo, log JSONL każdego wywołania, migawki STEP + GLB (start i po każdej edycji), limit 150, run_check, test_fit (licznik w episode.json), submit, wznowienie po restarcie serwera; zapytania measure (kawałki kolizji osobno, z centroidem) i section (dowolna płaszczyzna, współrzędne u/v).
- `cadfix/env/server.py`: FastMCP stdio; narzędzia z rejestrów + zapytania + `run_check_<id>` dla każdego checka ze spec.json.
- `scenarios/hinge_lid/instruction.py`: instruction.md z publicznych danych (D23); test wycieków jak dla briefu.
- Test MCP z prawdziwym klientem stdio (`tests/test_mcp.py`): L2 seed 0, poprawka odniesienia przez narzędzia, test_fit przechodzi, grader 1.0, log ma każde wywołanie.
- Testy: + `test_env.py` (4), `test_instruction.py` (6, w szybkim 2), `test_mcp.py` (1), `test_ops.py` +1. `pytest -q -m "not slow"`: 71 passed, 55 s.

### M3 (zadanie 6): rozwiązanie wzorcowe, baseline'y, exploity (2026-11-15)
- `scenarios/hinge_lid/reference.py` wg `docs/SOLVER_DESIGN.md`: tylko narzędzia (klient in-process albo MCP stdio), deterministyczny; analiza 2D przekrojów z narzędzia + weryfikacja S1 w 3D, 3 rundy powiększania, fallback: fazowanie całej krawędzi. Jedna poprawka po pierwszym przebiegu: L3 seed 4 dawał 0.039, bo model 2D liczył styk w pozycji zamkniętej (0°) jako kolizję (zaokrąglenia przekroju, 8e-5 mm²); teraz od 1° i próg pola 1e-3 mm³ / długość segmentu jak w generatorze.
- `cadfix/agents.py`: do_nothing, stop_early. `run_eval.py`: agent x poziom x seedy -> tabela + `results/*.csv`.
- **`python run_eval.py --agent reference,do_nothing,stop_early --level L1,L2,L3 --seeds 0-9`** (`results/run_eval_20261115_011537.csv`): reference **1.000 na 30/30** (1.00-1.03 x V_ref, 27-33 wywołań, 1.6-5 s), do_nothing 0 i stop_early 0 na 30/30.
- `scenarios/hinge_lid/exploits.py` + `tests/test_exploits.py`, tabela `docs/exploits.txt`: 17 exploitów na L2 i L3 seed 0, **najgorszy 0.300** (wydrążenie tylnej ściany + fazowanie: działa, ale traci drukowalność i S3; reszta 0.000). Znane ograniczenie: ukrycie wywołań test_fit przez przepisanie własnego logu daje 1.0 zamiast 0.9 (max zysk 0.1, D18).
- Uwaga: `output/tasks` trzeba odświeżyć po zmianie stref (`python -m scenarios.hinge_lid.task`); stare foldery dawały złe strefy uszczelki.

### M4 (zadanie 7): Harbor (2026-11-15)
- `cadfix/harbor/build.py`: level + seed -> `harbor_tasks/<L>/seed_N/` (instruction.md, task.toml, environment/ z tymi samymi ciężkimi warstwami co obraz dev + ostatni `COPY task /task`, tests/ z własnym graderem i danymi pristine, solution/ z rozwiązaniem wzorcowym przez MCP). `--judge` -> `harbor_tasks/judge/` (L1, L2, L3 seed 0). Wszystkie task.toml poprawne wg `harbor.models.task.config.TaskConfig` (harbor 0.26.0, `--validate`).
- Weryfikator w osobnym kontenerze (D24), `cadfix/harbor/agents.py: StopEarlyAgent` (D25), `cadfix/env/cli.py`.
- Przebiegi Harbora (Docker lokalnie, logi w `harbor_runs/`):
  - `harbor run -p harbor_tasks/judge -a oracle -y`: **3/3 = 1.000**, 0 wyjątków, 49 s (`harbor_runs/oracle_2026-11-15__02-14-01`)
  - `harbor run -p harbor_tasks/judge -a nop -y`: **0.000 x3** (`harbor_runs/nop_2026-11-15__02-15-26`)
  - `PYTHONPATH=. harbor run -p harbor_tasks/judge -a cadfix.harbor.agents:StopEarlyAgent -y`: **0.000 x3**, 2 wywołania narzędzi w kontenerze (`harbor_runs/stop_early_2026-11-15__02-16-21`)
- OpenCode nie był uruchamiany (płatny model; zostaje dla użytkownika).

### M5: README i podsumowanie (2026-11-15)
- `README.md` (co robi agent, dlaczego trudne, punktacja, tabela exploitów, wyniki run_eval i Harbora, pięć komend, sekcja na log OpenCode). Komendy Harbora sprawdzone dokładnie w tej postaci (bez `-y`): oracle 1.000 (`harbor_runs/oracle_2026-11-15__02-21-57`), nop 0.000, stop-early 0.000. Różnica względem TASK_4-7: Harbor 0.26 nie ma `--agent-import-path`, własny agent to `-a moduł:Klasa` (D25).
- CLAUDE.md: komendy zadań, gradera, serwera MCP, run_eval, exploitów, Harbora. Podsumowanie na górze tego pliku.
- Testy: szybkie 73 passed / 58 s; pełne 309 passed + 1 poprawiony (patrz podsumowanie).
