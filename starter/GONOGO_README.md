# Test go/no-go: jak sprawdzić, czy model radzi sobie z zadaniem

Instrukcja dla osoby bez kontekstu. Zajmie ok. 15–20 minut na jeden model i jeden poziom.

## O co chodzi w projekcie (w 30 sekund)

Budujemy środowisko RL na hackathon AfterQuery „Break the Agent”. Agent dostaje złożenie do druku 3D, które
nie działa: pudełko z pokrywą na zawiasie, w którym pokrywa zacina się przy otwieraniu, bo żebra pod uchami
zawiasu uderzają w tylną ścianę. Agent ma naprawić część operacjami CAD (fazowanie, wycięcia) tak, żeby
pokrywa otwierała się do 110°, z luzem ≥ 0,3 mm, bez naruszania uszczelnienia i z jak najmniejszą zmianą.

Są trzy poziomy:

| Poziom | Co sprawdza |
| --- | --- |
| L1 | czy model w ogóle znajdzie problem i dobierze rozmiar fazowania |
| L2 | czy wpadnie, że naprawa ma być **lokalna**, tylko tam, gdzie przechodzą żebra |
| L3 | L2 + każde żebro wymaga innego rozmiaru wybrania + całe złożenie jest obrócone w przestrzeni |

Ten test robimy ręcznie, w zwykłym czacie z modelem. Model dostaje opis zadania, odpowiada listą operacji
w JSON, my sprawdzamy ją skryptem i odsyłamy mu raport.

## Przygotowanie (raz)

1. Repo sklonowane, obraz Dockera zbudowany według sekcji „Commands” w `CLAUDE.md`
   (obraz nazywa się `cadfix-dev`).
2. Sprawdź, że działa (powinna pojawić się linia z nagrodą 1.000 w `gonogo_log.csv`):
   ```bash
   ./scripts/try.sh L2 0 docs/examples/L2_seed0_reference.json
   tail -1 gonogo_log.csv
   ```

## WAŻNE: czysty model

Testowany model nie może znać rozwiązania. Dlatego:

- **Zawsze nowa rozmowa.** Jedna rozmowa = jeden model × jeden poziom × jeden seed.
- **Nie w projekcie „hackjunction”** ani w żadnym czacie, w którym była mowa o tym zadaniu. Testując Claude'a
  na claude.ai: zwykły nowy czat poza projektami. Jeśli masz włączoną pamięć lub przeszukiwanie starych
  rozmów, wyłącz je na czas testu.
- **Nigdy nie pokazuj modelowi** plików z `docs/` (zwłaszcza `docs/examples/`, `scenario.json`,
  `acceptance_2c.txt`, `PROGRESS.md`), bo zawierają rozwiązanie.
- **Nie podpowiadaj.** Odpowiadasz tylko raportem ze skryptu i jednym z gotowych zdań poniżej.

## Przebieg testu

Przykład dla poziomu L2, seed 0, model „claude”. Dla innego poziomu zmień `L2`, dla innego modelu nazwę pliku.

### 1. Opis zadania

```bash
mkdir -p gonogo
./scripts/brief.sh L2 0 > gonogo/brief_L2_s0.txt
```

### 2. Pierwsza wiadomość do modelu

Wklej po kolei, w jednej wiadomości:

1. ten tekst:
   ```
   You are a mechanical engineer who designs parts for FDM 3D printing. Below are a bug report, the
   specification and everything measured about the assembly. Fix it.
   Explain your reasoning with calculations, then give the final answer as a JSON list of operations
   in the format below. After each attempt you get a test_fit report. You have at most 3 attempts.
   ```
2. sekcję z formatem operacji z `gonogo/README.md` (sam format pól, bez żadnych przykładowych rozwiązań),
3. całą zawartość `gonogo/brief_L2_s0.txt`.

### 3. Sprawdzenie odpowiedzi

Skopiuj JSON z odpowiedzi modelu do pliku i uruchom skrypt:

```bash
nano gonogo/claude_L2_s0_a1.json          # próba 1: a1, potem a2, a3
./scripts/try.sh L2 0 gonogo/claude_L2_s0_a1.json
```

- Na ekranie pojawia się raport **bez nagrody**. To jest to, co dostaje model.
- Nagroda trafia tylko do `gonogo_log.csv`. **Modelowi jej nie pokazuj.**

### 4. Odpowiedź do modelu

Wklej raport ze skryptu (bez ostatniej linii „logged to gonogo_log.csv”) i dopisz:

- po próbie 1: `Improve your fix.`
- po próbie 2: `You have one attempt left. Give your final answer (it may be the same as before).`

Jeśli model odpowie bez poprawnego JSON-a, napisz tylko:
`Please give the final answer as a JSON list of operations in the required format.`
Taka odpowiedź nie liczy się jako próba.

Jeśli model chce zmienić coś, czego skrypt nie potrafi zrobić (np. pokrywę, sworzeń albo operację spoza
listy), zapisz to w notatkach i odpowiedz:
`This operation is not available. Use only the listed operations on editable parts.`

### 5. Koniec

Po 3 próbach koniec rozmowy. Następny model, poziom albo seed: nowa rozmowa.

## Co zapisać

1. `gonogo_log.csv` zapisuje się sam: czas, poziom, seed, plik, nagroda, czy otwiera się do 110°,
   ile razy więcej materiału niż rozwiązanie wzorcowe.
2. Do `gonogo/notes.md` dopisz po każdej rozmowie kilka linijek:
   ```
   ## claude, L2, seed 0
   - a1: co zrobił (np. fazowanie całej krawędzi 0.8 x 1.9), wynik z logu
   - a2: ...
   - a3: ...
   - Wniosek: jednym zdaniem, gdzie się pomylił / czego nie zauważył
   - Cytat: jedno zdanie z jego rozumowania, które dobrze pokazuje błąd (do demo)
   ```
3. Jeśli możesz, wyeksportuj albo zrób zrzut całej rozmowy do `gonogo/transcripts/`.

## Jak czytać wynik

| Nagroda | Co to znaczy |
| --- | --- |
| 1.0 | idealnie: działa i zmiana jest minimalna (tak robi nasze rozwiązanie wzorcowe) |
| ok. 0.4–0.9 | działa, ale usunął za dużo materiału; kolumna `volume_over_vref` mówi, ile razy za dużo |
| 0.4 | typowe dla L2/L3: fazowanie całej krawędzi zamiast lokalnych wybrań |
| poniżej 0.25 | nie działa: pokrywa dalej uderza albo ociera (luz < 0,3 mm) |
| 0 | naruszył coś chronionego: uszczelnienie, żebra, wsporniki, pokrywę |

Dotychczasowy wynik: Hydrogen na L2 seed 0 dostał kolejno 0.103 → 0.400 → 0.400. Za każdym razem robił
fazowanie całej krawędzi (ok. 3,2 × za dużo materiału) i ani razu nie spróbował naprawy lokalnej.

Najciekawsze do sprawdzenia:
- czy mocniejszy model na L2 wpadnie na lokalne wybrania tylko przy żebrach,
- jeśli tak: czy przedłuży je poza końce żeber (bez tego wynik to 0),
- na L3: czy dobierze inny rozmiar dla każdego żebra i czy poradzi sobie z obróconym układem.
