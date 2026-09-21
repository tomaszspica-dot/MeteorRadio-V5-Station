# MeteorRadio V5 — Raspberry Pi + RTL-SDR, detekcja meteorów GRAVES 143.050 MHz

MeteorRadio V5 to stacja do **radiowej detekcji meteorów i meteor scatter** oparta o **Raspberry Pi 4 + RTL-SDR** i sygnał **GRAVES 143.050 MHz**. Projekt bazuje na upstreamowym `rabssm/MeteorRadio`, ale dodaje adaptacyjne nagrywanie detekcji, scoring 1–7, retencję, ulubione, sześć publicznych paneli WWW, prerender obrazów, healthcheck oraz opcjonalne współdzielenie jednego RTL-SDR z innym odbiornikiem.

<!-- MR_SHOWCASE_V1 -->
## Podgląd projektu

![MeteorRadio V5 — panel detekcji meteorów GRAVES 143.050 MHz](assets/screenshots/dashboard-main.png)

[Więcej zrzutów ekranu](docs/SHOWCASE.md)

## Stan referencyjny

- Golden: `20260921_165532_GOLDEN`
- 104 pliki w manifeście Golden
- ok. 9.1 MB skompresowanego prywatnego archiwum Golden bez danych obserwacyjnych
- SHA-256 prywatnego archiwum Golden: `3c2017d085ad69b9331955bc8021436970b132f2e07bf2179bda75d096c56ee0`
- odbiór: **GRAVES 143.050 MHz**

## Panele

| Port | Funkcja |
|---:|---|
| 8094 | główny panel detekcji MeteorRadio |
| 8095 | kolejka/status automatycznej oceny |
| 8096 | ulubione, retencja, ręczne usuwanie, duży podgląd obrazu |
| 8097 | statystyki |
| 8099 | 3D Spectrogram Viewer — analiza zapisanych obserwacji |
| 8100 | 3D Trajectory Analyzer — rodziny rozwiązań bistatycznych |

## Najważniejsze rozszerzenia V5

`ADAPTIVE_CAPTURE_V2` zapisuje kontekst przed zdarzeniem i dynamicznie kończy zapis po zaniku sygnału. Referencyjne parametry to PRE 3.0 s, minimum POST 0.8 s, hang 1.0 s i maksymalny POST 10 s.

Detekcje dostają ocenę 1–7. Niepolubiona detekcja może być usuwana po liczbie dni odpowiadającej ocenie, a polubione są przechowywane bezterminowo do ręcznego usunięcia.

## Ważne przed publikacją

Nie publikujemy automatycznie zmodyfikowanego upstreamowego `MeteorRadio`, ponieważ upstream nie ma obecnie widocznego pliku licencji. Zmodyfikowany rdzeń może zostać zachowany lokalnie w `private_reference/`, ale ten katalog jest ignorowany przez Git. Szczegóły: `UPSTREAM_LICENSE_NOTICE.md`.

## Jak przygotować repo z finalnej instalki

Jeżeli na Pulpicie Maca znajduje się:

```text
MeteorRadio_V5_ChatGPT_Installer.zip
```

uruchom:

```bash
chmod +x IMPORT_FROM_INSTALLER.command
./IMPORT_FROM_INSTALLER.command
```

Następnie:

```bash
chmod +x VALIDATE_BEFORE_GITHUB.command
./VALIDATE_BEFORE_GITHUB.command
```

Dopiero po przejściu walidacji inicjalizuj Git i publikuj repozytorium.


## Analiza 3D

### Port 8099 — 3D Spectrogram Viewer

Panel tylko do odczytu przeznaczony do analizy zapisanych obserwacji NPZ.

### Port 8100 — 3D Trajectory Analyzer

Analizator bistatyczny pojedynczej stacji. Wynik przedstawia rodzinę geometrii zgodnych ze zmierzonym Dopplerem, a nie jednoznaczną rzeczywistą trajektorię.

Współrzędne odbiornika nie są zapisane w publicznym kodzie. Użytkownik podaje je lokalnie przez zmienne środowiskowe.
