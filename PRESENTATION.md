# Guida completa per la presentazione PowerPoint

Questa guida descrive una presentazione di **5 slide e 5 minuti** per il progetto Inventory and Profitability Simulator. Contiene struttura, testo da inserire nelle slide, indicazioni per grafici e schermate, copione con tempi e sequenza per la demo. Il mazzo va realizzato in PowerPoint e salvato come `Inventory_Profitability_Simulator.pptx`.

## 1. Preparazione

### Materiale da tenere aperto

Apri PowerPoint e prepara anche un terminale con la cartella del progetto come directory corrente. I risultati mostrati sotto provengono dalla configurazione `inventory_student_sample_files/config/storage.toml`, seed 2026, 60 giorni e capacità di 300 unità.

La pipeline e la demo riproducibile sono:

```sh
.venv/bin/python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml import
.venv/bin/python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml summary
.venv/bin/python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml run
```

Prima della presentazione esegui i comandi, poi apri questi due file in un editor o foglio di calcolo:

- `inventory_student_sample_files/results/storage/policy_comparison.csv`
- `inventory_student_sample_files/results/storage/report.txt`

Il progetto importa 8 prodotti e 720 osservazioni storiche, cioè 90 giorni per prodotto. La domanda futura è generata una volta con NumPy e la stessa matrice viene riutilizzata in tutti i confronti.

### Stile del mazzo

- Formato: widescreen 16:9, 13,333 × 7,5 pollici.
- Sfondo: bianco caldo `#F7F8FA`; testo blu scuro `#152238`; accento teal `#087E8B`; colore secondario arancione `#F28C28`.
- Carattere: Aptos o Arial. Titoli 30–34 pt; testo 20–24 pt; note e fonti almeno 14 pt.
- Mantieni un margine di almeno 0,6 pollici. Usa allineamento a sinistra e spazio vuoto; evita riquadri decorativi e paragrafi lunghi.
- Metti il numero slide in basso a destra. Non aggiungere logo se il gruppo non ne ha uno ufficiale.
- Tutti i testi del copione vanno nelle note relatore, non nelle slide.

## 2. Costruzione slide per slide

### Slide 1 — Scorte, domanda e capacità

**Tempo:** 0:00–0:45. **Scopo:** introdurre il problema e l’estensione scelta.

**Titolo grande:**

> Inventory and Profitability Simulator

**Sottotitolo:**

> Come bilanciare disponibilità, costi di magazzino e capacità limitata

**Riga informativa in basso:**

> Progetto Python · 8 prodotti · 90 giorni di vendite storiche · estensione storage

**Composizione:** titolo e sottotitolo nella metà sinistra. A destra crea un diagramma semplice con tre elementi collegati da frecce: `Domanda` → `Decisione di riordino` → `Scorte disponibili`. Sotto la terza voce scrivi `Capacità massima: 300 unità`. Usa forme native di PowerPoint così il diagramma resta modificabile.

**Copione (circa 45 secondi):**

> Il nostro progetto simula le decisioni di riordino di un piccolo negozio. Il problema è bilanciare tre aspetti: soddisfare la domanda, limitare i costi di magazzino e rispettare la capacità disponibile. Abbiamo implementato le due politiche richieste e scelto l’estensione storage. La capacità è di 300 unità, mentre la scorta iniziale totale è 270. Confronteremo due regole per assegnare lo spazio disponibile agli ordini.

### Slide 2 — Flusso dell’applicazione

**Tempo:** 0:45–2:00. **Scopo:** illustrare architettura e una scelta tecnica significativa.

**Titolo:**

> Dati, simulazione e risultati

**Contenuto esatto:** disegna un flusso orizzontale con cinque passaggi:

1. `CSV + TOML`
2. `Validazione`
3. `SQLite + riepiloghi SQL`
4. `Domanda NumPy`
5. `Politiche → report CSV/TXT`

Sotto il flusso aggiungi due righe:

> Fixed quantity: se stock < 20, ordina 40 unità
>
> Order up to: se stock < 20, ordina fino a 60 unità

In un testo più piccolo, ma leggibile:

> Stessa matrice di domanda per tutte le politiche e regole di allocazione

**Composizione:** il diagramma occupa la fascia centrale; le due politiche stanno sotto come righe di testo semplici, senza card. Evidenzia `stessa matrice di domanda` in teal.

**Copione (circa 75 secondi):**

> La configurazione TOML definisce percorsi, orizzonte, seed, costi, soglie e capacità. Prima della simulazione validiamo prodotti e storico: ogni prodotto deve avere una registrazione per ogni data e i valori devono rispettare i vincoli. SQLite conserva catalogo, vendite, esecuzioni e risultati giornalieri. Le query SQL producono i riepiloghi storici, inclusi ricavi per categoria e migliori vendite in un intervallo.
>
> Per la parte numerica, stimiamo la domanda media giornaliera dai 90 giorni forniti e NumPy genera una matrice di Poisson di 60 righe per 8 prodotti. La scelta importante per il confronto è generare la matrice una sola volta: così ogni politica affronta la stessa domanda e le differenze dipendono dalle decisioni di riordino e dall’allocazione, non dal caso. Il motore applica un’interfaccia comune alle due politiche. Ogni giorno riceve gli ordini del giorno precedente, serve la domanda, calcola le vendite perse, applica i costi e pianifica i nuovi ordini.

### Slide 3 — Demo riproducibile

**Tempo:** 2:00–3:10. **Scopo:** mostrare il programma e seguire un risultato fino ai file prodotti.

**Titolo:**

> Dalla configurazione ai file di risultato

**Contenuto sulla slide:**

```text
1  import  →  8 prodotti, 720 vendite validate
2  summary →  riepiloghi storici SQL
3  run     →  4 scenari, domanda condivisa
```

In un angolo scrivi il percorso dei risultati:

> `inventory_student_sample_files/results/storage/`

**Sequenza demo a schermo:**

1. Mostra il comando `import` e il messaggio `Imported 8 products and 720 sales records`.
2. Mostra il comando `summary` e i tre ricavi per categoria: Accessories €2.697,00; Office €1.996,10; Stationery €3.452,50.
3. Mostra `policy_comparison.csv` e indica le quattro righe di scenario.
4. Mostra `report.txt` per leggere la raccomandazione e una limitazione.

Se non è possibile fare una demo dal vivo, prepara prima screenshot leggibili dei quattro passaggi e inseriscili in una singola slide, ritagliando terminale e file sul contenuto necessario. Non mostrare finestre con dati personali o altre applicazioni.

**Copione (circa 70 secondi):**

> Eseguiamo la pipeline dalla configurazione storage. L’importazione conferma 8 prodotti e 720 righe, cioè 90 giorni completi per ciascun prodotto. Il riepilogo SQL mostra i ricavi storici per categoria. Il comando run confronta due politiche e due regole di assegnazione dello spazio, salvando i risultati giornalieri, i confronti e un report leggibile. Nel CSV ogni scenario ha ricavi, costo del venduto, costi di magazzino, risultato operativo, unità perse, livello di servizio e scorte finali. Le vendite perse sono domanda che non viene recuperata nei giorni successivi.

### Slide 4 — Confronto dei risultati

**Tempo:** 3:10–4:00. **Scopo:** interpretare numeri e formulare una raccomandazione supportata.

**Titolo:**

> Risultato operativo per scenario

**Crea un grafico a barre orizzontali native di PowerPoint**, con scala da €2.650 a €2.800 oppure da zero se l’opzione di asse troncato rende la lettura ambigua. Evidenzia la barra migliore in teal, le altre in grigio/blu. Aggiungi l’importo alla fine di ogni barra.

| Politica | Allocazione | Risultato operativo |
|---|---|---:|
| Fixed quantity | ID crescente | €2.770,48 |
| Fixed quantity | Margine decrescente | €2.738,36 |
| Order up to | ID crescente | **€2.775,00** |
| Order up to | Margine decrescente | €2.710,84 |

Sotto il grafico aggiungi:

> Migliore nello scenario: order up to + ID crescente · vendite perse: 15 su 2.655 unità di domanda · fulfilment: 99,44%

E una nota visibile:

> Un’unica simulazione di 60 giorni, seed 2026; non è una previsione.

**Copione (circa 50 secondi):**

> Nello scenario simulato, order up to con allocazione per ID crescente raggiunge il risultato operativo più alto, 2.775 euro, con 15 unità di domanda perse e un fulfilment del 99,44%. La strategia fixed quantity con ID crescente è molto vicina, a 2.770 euro. L’allocazione per margine decrescente non è sempre migliore: in questo caso assegna capacità in modo da aumentare le vendite perse e abbassare il risultato operativo. La raccomandazione è quindi limitata a questi parametri e a questo seed; non affermiamo che sia la politica migliore in generale.

### Slide 5 — Ipotesi e limiti

**Tempo:** 4:00–5:00. **Scopo:** chiudere con le limitazioni e cosa imparare dal modello.

**Titolo:**

> Cosa non rappresenta ancora il modello

**Testo esatto, quattro punti:**

- Storico trattato come domanda: eventuali stockout passati abbasserebbero le medie stimate.
- Domanda Poisson indipendente, con media stabile nel tempo.
- Prezzi, costi e lead time di un giorno restano fissi.
- Un solo seed: serve confrontare più simulazioni per misurare l’incertezza.

**Riga finale in teal:**

> Prossimo passo: valutare le politiche su molti seed e periodi di domanda diversi.

**Copione (circa 60 secondi):**

> Il risultato va letto con quattro limiti. Primo, assumiamo che le vendite storiche rappresentino tutta la domanda: se in passato c’erano stockout, la domanda media è sottostimata. Secondo, il modello Poisson tratta gli acquisti giornalieri come indipendenti e usa una media stabile, quindi non cattura stagionalità o promozioni. Terzo, prezzi, costi e lead time sono fissi. Infine, abbiamo mostrato un solo seed: una conclusione più robusta richiede molte simulazioni indipendenti e periodi diversi. Il progetto è utile per confrontare meccanismi e rendere esplicite le ipotesi; non sostituisce una previsione operativa.

## 3. Controllo prima della consegna

- Verifica che il mazzo abbia esattamente 5 slide e che il copione duri circa 5 minuti.
- Controlla che gli importi del grafico coincidano con `policy_comparison.csv`.
- Verifica che il valore migliore sia €2.775,00 e corrisponda a `order_up_to` + `product_id_ascending`.
- Controlla che la slide 4 dichiari il seed 2026 e l’orizzonte di 60 giorni.
- Prova i comandi demo nella cartella di progetto prima di entrare in aula.
- Metti i nomi e i contributi reali dei cinque membri nella dichiarazione di gruppo; la slide non deve attribuire ruoli inventati.
- Esporta anche una copia PDF solo se il docente o il gruppo la richiede; conserva il `.pptx` modificabile.

## 4. Componenti del gruppo

Questi sono i nomi forniti dal gruppo. La guida non assegna ruoli tecnici perché non sono stati specificati.

- PIETRO NICOLAZZI
- NICOLA RIZZUTO
- MAIA TRUBIANO
- TOMMASO MARRUCCI
- HADRIEN RAYMOND JULIEN GIRAL--GHATTAS
