# Validation — Homebrew Intel Bottle Pool 0.3.5

8 octombrie 2026. Acest document separă rezultatele testelor locale de condițiile
care trebuie confirmate pentru fiecare produs final. O copie dintr-un branch nu
certifică singură existența unui release public.

## Audit independent

Commitul inițial 4c9c880: 120 teste, 3 failures, 1 error, 3 skipped (bundle absent).
Verificarea tap-ului local fusese omisă la sincronizările cached (testul este
redescoperit și prin importuri). Fixture-ul legacy nu furniza rețeta instalată
pentru dependență. Testul bundle-ului aștepta încă build 34 în loc de build 35.
Aceste probleme au fost corectate, fără slăbirea verificărilor de producție.

## Verificări finalizate

Suita completă extinsă a trecut toate cele **160 de teste**, fără skip, cu bundle
local Intel 0.3.5, build 35. Include regresiile de publicare și notarizare, plus
cele cinci verificări ale opririi publicării înainte de contactarea GitHub.
Testele acoperă schema 1, server fixture loopback, lease/fencing,
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

Jurnalul local de la pasul node și manifestele spool-ului identifică
googletest 1.18.0 ca dependență eșuată, cu două copii locale identice.
Manifestul remote nu a fost citit; bytes/context de pe server rămân neconfirmate.
Sunt adăugate regresii pentru variante separate la schimbarea formulei,
reutilizarea verificată a unui build publicat, context/build inputs diferite
refuzate, checksum upstream nesubstituit și carantină legacy fără modificarea
bytes-urilor. Transportul notarizării verifică SSH, hash-ul transferat și păstrează
profilul exclusiv pe Mac-ul care îl deține.

Fluxul aplicației compilate a trecut verificarea izolată cu procese reale:
oprire la primul eșec, păstrarea numărului de erori, Retry numai failed, Resume
remaining, Stop cu închiderea copilului, Stop/Resume, Quit disponibil în Busy,
configurație izolată și reconcilierea UI stale la lansare. Fixture-ul de bottle
folosește tag-ul all, evitând presupunerea greșită că orice Mac rulează Tahoe.

Testul funcțional Homebrew real a trecut pe Intel macOS 15.8.1, într-un prefix
temporar: compilare C → bottle → server schema 1 local → dezinstalare temporară
→ pour exclusiv din pool → brew test și executarea programului. Cask-ul temporar
a trecut download → pool → dezinstalare → reinstalare cu sursa upstream ascunsă;
SHA-256 al executabilului instalat corespunde celui original. Aplicația sintetică
nesemnată nu este lansată ca test de Gatekeeper. Ruby, cache, loguri, Cellar și
Applications sunt izolate; niciun pachet real al utilizatorului nu este modificat.

## Gate de distribuție

Build-ul final trebuie să provină dintr-un checkout curat pe branch-ul autorizat.
SourceManifest.json este inclus în semnătură și leagă commitul de inputurile Swift,
plist, icon și Python. Gate-ul verifică sursele byte-for-byte, fișierele exacte,
x86_64, build 35, Developer ID Team YWVVK7QZ6X, runtime și timestamp.
Containerele DMG/ZIP sunt comparate cu app-ul semnat; source ZIP este comparat cu
fiecare fișier Git, iar SHA256SUMS.txt este verificat. Publicarea cere și Accepted,
stapling și Gatekeeper pentru app/DMG, apoi descarcă release-ul pentru reverificare.

Pentru o distribuție finală, `app-notarization.json` și `dmg-notarization.json`
trebuie să raporteze Accepted, iar ticket-urile reale ale app/DMG trebuie să treacă
stapler și Gatekeeper. Logurile notarizării sunt incluse în artefacte și hash-uri.
Nu se cer parole noi și nu se extrag parole din Keychain. Un bundle semnat sau
checksum-uri corecte nu constituie confirmare de notarizare.

Documentația și diagrama How it works au fost refăcute pentru întregul flux 0.3.5.
Gate-ul cere toate documentele și PNG/SVG în source ZIP și în setul final de
artefacte. Publicarea verifică toate fișierele descărcate din draft înainte de
actualizarea branch-ului implicit stable și de marcarea release-ului v0.3.5 ca
public/latest. Pregătirea se face exclusiv local; main și CI nu sunt folosite.

Codul serverului, validarea protocolului și formatul job-urilor (`server.py`,
`common.py`, `jobs.py`) sunt identice cu stable fee50c4; noile câmpuri de
proveniență sunt metadata acceptate de schema 1. Compatibilitatea este verificată
și prin serverul local real, fără schimbarea serviciului NAS.

Formatul ticketului Apple a fost confirmat în citire pe backup-ul notarizat:
`Contents/CodeResources` este un fișier regular separat de semnătură, iar
stapler validate reușește. Verificatorul acceptă această singură adăugare numai
cu ticket valid, după controalele surselor și semnăturii. Ticket fals și symlink
sunt refuzate. La rebuild, produsul local anterior este păstrat separat înainte
de copiere, evitând moștenirea unui ticket vechi prin comportamentul merge al ditto.
Acest control nu certifică notarizarea noului bundle; acesta are nevoie de
propriul Accepted și propriul ticket.

## Limite și producție

Nu s-au executat operații Homebrew mutative sau Retry asupra cozii reale.
Nu s-au modificat aplicația instalată, TrueNAS, configurația, tokenul sau spool-ul.
Nu s-au declanșat GitHub Actions/CI; repository-ul raportează zero workflow-uri.
Nu este efectuată validarea fizică pe al doilea Mac sau un nou build real al
formulelor pe instalația utilizatorului. Variantele legacy nu sunt migrate;
keg-urile fără dovadă completă pot necesita un rebuild verificat.
