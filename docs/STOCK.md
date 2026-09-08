# Lokalny magazyn

## Model

| Tabela | Rola | Charakter |
|---|---|---|
| `opening_balances` | stan początkowy produktu w magazynie (ilość, na dzień, notatka, autor) | źródło, edytowalne (audytowane nadpisanie) |
| `local_stock_adjustments` | ręczne korekty ± z wymaganym opisem | źródło, **append-only** (odwracanie przez storno) |
| `local_stock_ledger` | każdy ruch magazynowy z saldem przed/po | **projekcja pochodna**, w pełni odtwarzalna |
| `local_stock_balances` | bieżące saldo produkt × magazyn + ostatni ruch/sprzedaż | cache przeliczany razem z ledgerem |

## Typy ruchów

| Typ | Źródło | Znak |
|---|---|---|
| `OPENING_BALANCE` | `opening_balances` | + (ilość początkowa) |
| `SALE` | pozycja faktury sprzedażowej | − ilość |
| `SALE_CORRECTION` | pozycja faktury korygującej | − delta (ujemna delta ⇒ zwrot na stan) |
| `MANUAL_ADJUSTMENT` | korekta ręczna | ± |
| `IMPORTED_WAREHOUSE_ACTION` | akcja magazynowa z Fakturowni (opcjonalnie) | PZ/PW/ZW +, WZ/RW − |

## Przebudowa (`POST /stock/recalculate`)

1. Zebranie wszystkich ruchów ze źródeł.
2. Deterministyczne sortowanie: `occurred_at` → priorytet (stan początkowy 0,
   import 2, korekta ręczna 3, korekta sprzedaży 6, sprzedaż 7) → produkt.
3. Wyzerowanie ledgera i sald, ponowne naliczenie z `balance_before/after`
   i numerem sekwencji.
4. Aktualizacja `local_stock_balances` (saldo, ostatni ruch, ostatnia sprzedaż).

Przebudowa uruchamia się automatycznie po dodaniu stanu początkowego,
korekty lub storna oraz na początku każdej walidacji, więc stany są zawsze
spójne ze źródłami. Operacja jest w 100% lokalna.

## Zasady

* Pozycje niezmapowane, usługi, produkty ignorowane i zestawy bez składu nie
  generują ruchów (raportuje je walidacja).
* Zestaw z lokalnym składem rozlicza komponenty: `ilość pozycji × ilość
  komponentu`.
* Faktury anulowane/wykluczone i oznaczone jako usunięte w Fakturowni są
  pomijane.
* Magazyn dokumentu: `warehouse_id` faktury → mapowanie na magazyn lokalny;
  brak → magazyn domyślny.
* Storno korekty tworzy korektę odwrotną powiązaną `reverses_adjustment_id`
  — historia operacji nigdy nie jest usuwana.

## API

| Endpoint | Opis |
|---|---|
| `GET /stock/balances` | salda z porównaniem do stanów Fakturowni (różnica) |
| `GET /stock/ledger` | pełny ledger z filtrami (produkt, magazyn, typ, faktura) |
| `GET/POST /stock/opening-balances` | odczyt / ustawienie stanu początkowego |
| `GET/POST /stock/local-adjustments` | odczyt / dodanie korekty lokalnej |
| `POST /stock/local-adjustments/{id}/reverse` | storno korekty |
| `POST /stock/recalculate` | pełna przebudowa ledgera i sald |

Wszystkie operacje zapisu wymagają roli operator/admin, są audytowane
(użytkownik, czas, IP, opis) i dotyczą wyłącznie lokalnej bazy.
