# Walidacja sprzedaży

## Przebieg uruchomienia

1. `POST /validation/run` (przycisk „Waliduj” / moduł Walidacje).
2. Przebudowa lokalnego magazynu (spójne salda przed sprawdzeniami).
3. Wykonanie wszystkich reguł i zebranie znalezisk.
4. Materializacja problemów (patrz „Cykl życia problemu”).
5. Zapis statystyk w `validation_runs` + wpisy audytu.

## Reguły (mapowanie wymagań 1–20 → typy problemów)

| # | Sprawdzenie | Typ problemu |
|---|---|---|
| 1 | produkt rozpoznany? | `PRODUCT_NOT_RECOGNIZED` |
| 2 | pozycja ma `product_id`? | `PRODUCT_ID_MISSING` (rozpoznana lokalnie) |
| 3 | towar czy usługa? | `UNKNOWN_PRODUCT_TYPE`, `SERVICE_INCLUDED_IN_STOCK` |
| 4 | produkt kontrolowany magazynowo? | pomijany w ruchach; błędna konfiguracja → jw. |
| 5 | ilość dodatnia i logiczna? | `INVALID_QUANTITY` (≤0 poza korektą; > próg) |
| 6 | jednostka zgodna z produktem? | `UNIT_MISMATCH` |
| 7 | wystarczający stan w dniu sprzedaży? | `INSUFFICIENT_STOCK` (saldo przed < potrzeba) |
| 8 | sprzedaż powoduje stan ujemny? | `NEGATIVE_STOCK` (saldo po < 0) |
| 9 | faktura zdublowana? | `DUPLICATE_INVOICE` (numer+klient) |
| 10 | faktura anulowana rozliczona? | `CANCELLED_INVOICE_INCLUDED` |
| 11 | korekta wymaga przeliczenia? | `CORRECTION_NOT_HANDLED` |
| 12 | status wykluczający z walidacji? | dokument pomijany (lista w Ustawieniach) |
| 13 | pozycja bez `product_id` rozpoznawalna aliasem? | mapowanie automatyczne; nierozpoznana → #1 |
| 14 | produkt nieaktywny/wyłączony? | `INACTIVE_PRODUCT_SOLD` |
| 15 | rozbieżność stan lokalny vs Fakturownia? | `STOCK_DISCREPANCY` |
| 16 | korekta poprawnie odwraca wydanie? | `SALE_CORRECTION` w ledgerze + #11 przy braku pierwotnego |
| 17 | faktura rozliczona magazynowo > 1 raz? | `DOUBLE_STOCK_SETTLEMENT` |
| 18 | brak stanu początkowego? | `MISSING_OPENING_BALANCE` |
| 19 | sprzedaż przed datą stanu początkowego? | `SALE_BEFORE_OPENING_BALANCE` |
| 20 | nierozpoznana jednostka miary? | `UNKNOWN_UNIT` |

Dodatkowo: `UNKNOWN_DOCUMENT_TYPE` (typ dokumentu bez reguły),
`MAPPING_CONFLICT` (wiele produktów pasuje), `LOCAL_RULE_REQUIRED`
(np. zestaw bez składu).

## Statusy problemów

`OK`, `WARNING`, `ERROR`, `NEEDS_MAPPING`, `NEEDS_OPENING_BALANCE`,
`IGNORED`, `RESOLVED` — status początkowy wynika z typu problemu (np.
`NEGATIVE_STOCK` → `ERROR`, `PRODUCT_NOT_RECOGNIZED` → `NEEDS_MAPPING`).
Ważność: `INFO/LOW/MEDIUM/HIGH/CRITICAL`.

## Zawartość problemu

Faktura, pozycja, produkt (jeśli rozpoznany), magazyn, ilość, stan przed/po,
typ, status, ważność, opis techniczny (dla diagnozy), opis biznesowy (dla
operatora, po polsku), rekomendowana akcja, daty utworzenia/rozwiązania,
użytkownik rozwiązujący, komentarze.

## Cykl życia problemu

* `dedupe_key = sha256(typ|faktura|pozycja|produkt|magazyn)` — problem jest
  unikalny w tym wymiarze.
* Ponowna walidacja: istniejący otwarty problem jest **aktualizowany**
  (ilości, salda, opisy), nie duplikowany.
* Problem niewykryty ponownie → automatycznie `RESOLVED`
  (licznik `issues_auto_resolved`).
* `IGNORED` ustawione przez operatora jest **trwałe** — kolejne walidacje go
  nie ruszają.
* `RESOLVED`, którego przyczyna wróciła → ponowne otwarcie ze statusem
  domyślnym dla typu.
* Zmiany statusu i komentarze są lokalne i audytowane.

## Typowy workflow operatora

1. Dashboard → liczniki błędów/ostrzeżeń → moduł Walidacje.
2. Filtrowanie po typie/statusie/produkcie/fakturze; przejście z problemu do
   faktury, produktu i ruchów magazynowych jednym kliknięciem.
3. Naprawienie przyczyny: mapowanie produktu / stan początkowy / korekta
   lokalna / wyjaśnienie z komentarzem.
4. Ponowna walidacja — naprawione problemy zamykają się automatycznie.
