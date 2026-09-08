# Założenia biznesowe (ASSUMPTIONS)

Ten dokument zbiera **wszystkie** istotne założenia biznesowe zaimplementowane
w systemie. Żadne założenie nie jest „ukryte w kodzie” — jeśli zmieniasz
regułę, zaktualizuj ten plik.

## 1. Dokumenty zmniejszające stan magazynu

* Faktury sprzedażowe (`income = true`) o typie (`kind`) znajdującym się na
  liście `stock_sale_invoice_kinds` — domyślnie: `vat`, `receipt`, `bill`,
  `final`, `invoice` — generują ruch `SALE` o wartości `-ilość` dla każdej
  pozycji zmapowanej na produkt magazynowy.
* Lista typów jest edytowalna w **Ustawieniach** (klucz
  `stock_sale_invoice_kinds`), bez zmiany kodu.
* Faktury `proforma`, `estimate` oraz inne typy spoza listy **nie zmieniają**
  stanu magazynu.
* Dokumenty kosztowe/zakupowe (`income = false`) są poza zakresem kontroli
  sprzedaży i nie generują ruchów.

## 2. Dokumenty zwiększające stan magazynu

* **Stany początkowe** (`opening_balances`) — ruch `OPENING_BALANCE`
  o godz. 00:00 dnia `as_of_date`.
* **Ręczne korekty dodatnie** (`local_stock_adjustments`) — ruch
  `MANUAL_ADJUSTMENT`.
* **Korekty sprzedaży zwracające towar** — patrz punkt 4.
* Opcjonalnie **importowane akcje magazynowe Fakturowni** (PZ/PW/ZW jako
  przyjęcia, WZ/RW jako wydania) — ruch `IMPORTED_WAREHOUSE_ACTION`.
  Domyślnie **wyłączone** (`stock_use_imported_warehouse_actions = false`),
  ponieważ sprzedaż jest już rozliczana z faktur i równoległe importowanie
  dokumentów WZ powodowałoby **podwójne zdjęcie stanu**. Włącz tylko wtedy,
  gdy świadomie budujesz stany wyłącznie z dokumentów magazynowych.

## 3. Faktury anulowane

* Faktura jest uznana za anulowaną, gdy payload zawiera `cancelled = true`
  albo `status ∈ {cancelled, canceled}`.
* Faktury anulowane **nigdy nie generują ruchów magazynowych** i są pomijane
  w walidacji pozycji.
* Jeżeli mimo to w ledgerze istnieją ruchy powiązane z anulowaną fakturą
  (np. dane sprzed anulowania, przed przeliczeniem), walidacja zgłasza
  `CANCELLED_INVOICE_INCLUDED` — rozwiązaniem jest przeliczenie stanów.
* Statusy z listy `stock_excluded_invoice_statuses` (domyślnie `rejected`)
  traktowane są tak samo jak anulowanie.

## 4. Faktury korygujące

* Dokument `kind = correction` generuje ruch `SALE_CORRECTION`.
* **Założenie:** ilości na pozycjach korekty są **deltami** (różnicą „po −
  przed”), tak jak zwraca je API Fakturowni. Korekta zmniejszająca sprzedaż
  o 2 szt. ma pozycję z `quantity = -2`, więc ruch magazynowy wynosi
  `-(-2) = +2` (towar wraca na stan).
* Korekta bez rozpoznawalnego dokumentu pierwotnego (`from_invoice_id` pusty
  lub wskazuje na fakturę nieobecną lokalnie) jest zgłaszana jako
  `CORRECTION_NOT_HANDLED` i wymaga ręcznej weryfikacji.
* Ujemne ilości są dozwolone wyłącznie na korektach; na zwykłej fakturze
  sprzedażowej powodują `INVALID_QUANTITY`.

## 5. Usługi

* Produkt oznaczony lokalnie jako `SERVICE` (albo `service = true`
  w Fakturowni — przenoszone przy pierwszym imporcie) **nie zmienia stanu
  magazynu** i nie jest walidowany magazynowo.
* Usługa z włączoną flagą „kontrola magazynowa” to błąd konfiguracji —
  walidacja zgłasza `SERVICE_INCLUDED_IN_STOCK`.
* Klasyfikację (towar/usługa/zestaw/ignorowany) można zmienić lokalnie na
  karcie produktu; zmiana nigdy nie jest wysyłana do Fakturowni.

## 6. Pozycje bez `product_id`

* Kolejność rozpoznawania: `product_id` → zatwierdzone mapowanie po sygnaturze
  (nazwa+kod+EAN+jm.) → alias (`CODE`, `EAN`, `NAME`) → dokładny kod → EAN →
  znormalizowana nazwa.
* Dopasowania po kodzie/EAN/nazwie mają status `PROPOSED` i **liczą się do
  magazynu**, ale panel mapowań wymaga ich zatwierdzenia; walidacja oznacza
  je ostrzeżeniem `PRODUCT_ID_MISSING`.
* Brak dopasowania → pozycja pozostaje niezmapowana, **nie generuje ruchu
  magazynowego**, walidacja zgłasza `PRODUCT_NOT_RECOGNIZED`
  (status `NEEDS_MAPPING`), a w module mapowań czeka gotowy wpis do
  uzupełnienia.
* Niejednoznaczne dopasowanie (≥2 kandydatów) → `MAPPING_CONFLICT`, pozycja
  niezmapowana do czasu ręcznego rozstrzygnięcia.

## 7. Brakujące magazyny

* Jeżeli konto Fakturowni nie ma magazynów, system tworzy automatycznie
  lokalny **„Magazyn główny (lokalny)”** i księguje w nim wszystkie ruchy.
* Faktura bez `warehouse_id` księgowana jest w magazynie domyślnym
  (pierwszy magazyn z Fakturowni albo magazyn lokalny).
* Magazyny usunięte w Fakturowni pozostają lokalnie z flagą
  `is_deleted_upstream`.

## 8. Brakujące stany początkowe

* Stan początkowy nie jest wymagany do działania systemu: bez niego saldo
  startuje od 0, więc każda sprzedaż natychmiast tworzy stan ujemny.
* Walidacja zgłasza wtedy `MISSING_OPENING_BALANCE`
  (status `NEEDS_OPENING_BALANCE`) dla każdej pary produkt×magazyn ze
  sprzedażą bez wpisu w `opening_balances` oraz `NEGATIVE_STOCK` /
  `INSUFFICIENT_STOCK` dla konkretnych pozycji.
* Sprzedaż z datą wcześniejszą niż `as_of_date` stanu początkowego →
  `SALE_BEFORE_OPENING_BALANCE`.
* Jeden stan początkowy na parę produkt×magazyn; ponowne ustawienie nadpisuje
  wpis (audytowane), a niuanse ilościowe koryguje się ręcznymi korektami.

## 9. Zestawy / pakiety

* Fakturownia nie udostępnia składów zestawów przez API, więc skład definiuje
  się **lokalnie** na karcie produktu (`product_bundle_components`).
* Sprzedaż zestawu rozlicza wyłącznie komponenty (ilość pozycji × ilość
  komponentu); sam zestaw nie ma własnego stanu.
* Zestaw bez zdefiniowanego składu nie zmienia magazynu, a walidacja zgłasza
  `LOCAL_RULE_REQUIRED`.

## 10. Czas i kolejność ruchów

* Ruchy z faktur mają znacznik czasu `sell_date` (fallback `issue_date`)
  o godz. 12:00 UTC; stany początkowe o 00:00, więc zawsze poprzedzają
  sprzedaż z tego samego dnia.
* Przy identycznym czasie kolejność wyznacza priorytet: stan początkowy →
  importy magazynowe → korekty ręczne → korekty sprzedaży → sprzedaż.
  Dzięki temu dostawa zaksięgowana tego samego dnia „wchodzi” przed sprzedażą.

## 11. Rozbieżności ze stanami Fakturowni

* Jeśli Fakturownia raportuje stany (globalne `products.quantity` lub per
  magazyn `products.json?warehouse_id=`), walidacja porównuje je z lokalnymi
  saldami; różnica powyżej tolerancji
  (`validation_stock_discrepancy_tolerance`, domyślnie 0.001) →
  `STOCK_DISCREPANCY` (ostrzeżenie, nie błąd — lokalny magazyn jest źródłem
  prawdy dla kontroli).

## 12. Duplikaty faktur

* Dwie nieanulowane faktury o tym samym numerze i tym samym kliencie
  (`client_id`) → `DUPLICATE_INVOICE` na każdym dokumencie poza pierwszym.
  System nie rozstrzyga, który dokument jest właściwy — decyzja należy do
  operatora (status `IGNORED`/`RESOLVED` + komentarz).

## 13. Dane usunięte w Fakturowni

* Pełna synchronizacja oznacza rekordy nieobecne w API flagą
  `is_deleted_upstream = true`. Nic nie jest fizycznie usuwane lokalnie;
  faktury oznaczone jako usunięte nie biorą udziału w rozliczeniu magazynu.
* Pozycje, które zniknęły z payloadu faktury, są usuwane z tabeli mirrored
  positions (historia pozostaje w `source_snapshots`).

## 14. Ilości „podejrzane”

* `quantity ≤ 0` na zwykłej fakturze sprzedażowej → `INVALID_QUANTITY` (błąd).
* `|quantity| > validation_max_reasonable_quantity` (domyślnie 100 000) →
  `INVALID_QUANTITY` jako ostrzeżenie przed literówką.

## 15. Jednostki miary

* Porównanie jednostek jest case-insensitive po normalizacji spacji.
* Jednostka pozycji ≠ jednostka produktu → `UNIT_MISMATCH` (ostrzeżenie);
  różnice zamierzone rozwiązuje się aliasem jednostki albo ignorując problem.
* Brak jednostki i na pozycji, i na produkcie → `UNKNOWN_UNIT`.
