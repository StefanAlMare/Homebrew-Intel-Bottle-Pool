# Validation — Homebrew Intel Bottle Pool 0.3.5

8 octombrie 2026. Surse reparate și testate; publicarea este blocată la notarizare.

## Audit independent

Commitul inițial 4c9c880: 120 teste, 3 failures, 1 error, 3 skipped (bundle absent).
Verificarea tap-ului local fusese omisă la sincronizările cached (testul este
redescoperit și prin importuri). Fixture-ul legacy nu furniza rețeta instalată
pentru dependență. Testul bundle-ului aștepta încă build 34 în loc de build 35.
Aceste probleme au fost corectate, fără slăbirea verificărilor de producție.

## Verificări finalizate

Toate cele **140 de teste** au trecut, fără skip, cu bundle local Intel 0.3.5,
build 35. Testele acoperă schema 1, server fixture loopback, lease/fencing,
spool offline, Retry/Resume/Stop, rollback, installer în directoare temporare,
proveniență, graf declarat, schimbări reale runtime/build/test și sursele bundle.

Regresiile noi verifică: API-only dependency changes cu identitate stabilă;
rețetă/versiune instalată schimbată cu variantă nouă; dovezi lipsă/symlink refuzate;
variante legacy separate și neconsumate; Retry cu șase și cinci pași pending;
tranziția old-keg/new-keg fără recompilare falsă; drift real cu un singur rebuild;
drift repetat oprit după două build-uri; reutilizare fără recompilare numai cu
build proof valid; runtime nedeclarat refuzat; input build-only schimbat; tap-uri
locale modificate/divergente refuzate; snapshot după update fără fetch suplimentar;
transformarea exactă a blocului bottle și newline-uri păstrate; surse modificate
în bundle respinse. Dovezile sunt legate de keg și invalidate la rollback.

În citire, receipt-urile reale harfbuzz 14.5.1 și 14.6.0 confirmă brotli absent în
primul și 1.2.0 în al doilea. Codul local Homebrew citește runtime_dependencies
din keg când deps nu selectează explicit modul recipe. Normalizarea sursei reale
harfbuzz din tap produce exact hash-ul copiei .brew instalate pentru 14.6.0.
Aceste verificări nu au rulat comenzi Homebrew mutative.

## Gate de distribuție

Build-ul final trebuie să provină dintr-un checkout curat pe branch-ul autorizat.
SourceManifest.json este inclus în semnătură și leagă commitul de inputurile Swift,
plist, icon și Python. Gate-ul verifică sursele byte-for-byte, fișierele exacte,
x86_64, build 35, Developer ID Team YWVVK7QZ6X, runtime și timestamp.
Containerele DMG/ZIP sunt comparate cu app-ul semnat; source ZIP este comparat cu
fiecare fișier Git, iar SHA256SUMS.txt este verificat. Publicarea cere și Accepted,
stapling și Gatekeeper pentru app/DMG, apoi descarcă release-ul pentru reverificare.

Profilul HomebrewPoolNotary nu există pe acest MacBook. Notarizarea, stapling-ul,
Gatekeeper pentru distribuție și release-ul GitHub nu sunt confirmate. Nu se cer
parole noi și nu se extrag parole din Keychain. Un bundle semnat sau checksum-uri
corecte nu constituie confirmare de notarizare.

## Limite și producție

Nu s-au executat operații Homebrew mutative sau Retry asupra cozii reale.
Nu s-au modificat aplicația instalată, TrueNAS, configurația, tokenul sau spool-ul.
Nu s-au declanșat GitHub Actions/CI; repository-ul raportează zero workflow-uri.
Nu este efectuată validarea fizică pe al doilea Mac sau un nou build real al
formulelor pe instalația utilizatorului. Variantele legacy nu sunt migrate;
keg-urile fără dovadă completă pot necesita un rebuild verificat.
