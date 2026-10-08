# Homebrew Intel Bottle Pool 0.3.5 — Release Notes

8 octombrie 2026. Intel x86_64, minimum macOS 12, build 35.

## Proveniență și recuperare

Blocajul analizat la gobject-introspection 1.86.0_4 apărea când identitatea unei
rețete din API se schimba deși dependența instalată rămânea aceeași. Clientul
folosește acum SHA-256 al fișierului `.brew/FORMULA.rb` din keg-ul curent.
Schimbarea versiunii instalate sau a rețetei instalate schimbă varianta; o
schimbare exclusiv API a dependenței nu o schimbă. Lipsa dovezii, citirea eșuată
și rețetele/directoarele legate simbolic opresc publicarea cu diagnostic.

Planificarea folosește explicit graful declarat pentru platformă (`brew deps
--os=TAG`), nu graful runtime al unui keg existent. Codul Homebrew local arată că
fără această opțiune `deps` poate citi runtime_dependencies din receipt: înainte
de upgrade este keg-ul vechi, după upgrade este keg-ul nou. Jurnalul harfbuzz
14.5.1 → 14.6.0, cu brotli absent → 1.2.0, este compatibil cu acest mecanism;
jurnalul singur nu exclude o modificare concurentă de rețetă.

La un build sursă, instalarea și comenzile ulterioare folosesc rețetele locale
sincronizate, cu instalarea din API dezactivată. HEAD-ul tap-ului este păstrat și
verificat; un tap modificat sau schimbat concurent oprește execuția. Preflight și
build-ul împart evidența sincronizării: fetch-ul nu se repetă în aceeași operație.
Verificările locale de siguranță și de rețetă se repetă fără fetch.

Recuperarea este limitată la o singură refacere a planului per pachet/per execuție,
cu graful recitit și lease nou. Înainte de compilare aceasta nu compilează nimic.
După o schimbare reală în timpul build-ului, primul artifact este refuzat; se
repară dependențele necesare și se permite un singur rebuild tranzacțional.
O a doua schimbare oprește operația. Lipsa provenienței și dependențele runtime
nedeclarate nu sunt ignorate sau acceptate automat. `brew linkage --test` verifică
rezultatul înainte de enqueue/publicare.

Dovezile locale `build-proofs` păstrează contextul runtime, intrările build/test,
hash-ul rețetei instalate și identitatea keg-ului imediat după compilare. Copia
`.brew` este verificată prin transformarea exactă folosită de Homebrew pentru
eliminarea blocului bottle, după verificarea checksum-ului sursei complete. Retry sare peste recompilare numai când dovada, rețeta
instalată și toate intrările corespund planului curent. Un keg legacy fără această
dovadă poate necesita un rebuild verificat; nu se pretinde că o compilare veche
cu proveniență incompletă este sigură. Rollback-ul 0.3.4 este păstrat.

## Compatibilitate

Protocolul pool, spool-ul și job.json rămân schema 1. Nu este necesară o migrare
pe server. Variantele 0.3.5 au un identificator distinct inclusiv pentru formule
fără dependențe, evitând conflicte de rang cu artefactele legacy. Artefactele
vechi nu sunt șterse, relabelate sau acceptate drept proveniență nouă. Prima
construcție a unei variante noi poate fi necesară; clienții vechi își păstrează
propriile variante. Configurația, tokenul și coada existentă sunt păstrate.
Retry execută numai pașii failed; cei pending sunt executați prin Resume.

## Distribuție

Build-ul se produce local pe Intel macOS. Release-ul final necesită Developer ID
Application, Team YWVVK7QZ6X, notarizare Accepted pentru app și DMG, stapling,
Gatekeeper și verificarea conținutului ZIP/DMG față de sursele commitului.
SHA256SUMS.txt acoperă artefactele și documentele distribuite. GitHub este folosit
pentru distribuție; nu se folosesc GitHub Actions sau compilări găzduite.
Consultați VALIDATION.md pentru verificările efectiv finalizate și limitări.
