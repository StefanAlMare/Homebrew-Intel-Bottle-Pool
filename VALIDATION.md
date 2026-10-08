# Validation — Homebrew Intel Bottle Pool 0.3.4

Data validării: 8 octombrie 2026.

## Build

- aplicație `0.3.4`, build `34`, Intel `x86_64`, deployment target macOS 12;
- build local cu Swift 6.3.3 pe macOS Intel;
- semnare Developer ID Application, hardened runtime și Apple timestamp;
- sursele incluse în bundle sunt comparate byte-for-byte cu sursele release.

## Teste automate

Toate cele **112 teste automate** au trecut. Suita verifică protocolul schema 1, spool/lease/fencing, formulae,
Cask-uri, coada persistentă, Stop/Resume, preflight, Maintenance Console și
aplicația macOS. Regresiile 0.3.4 acoperă explicit:

- keg instalat/current fără `built_as_bottle`: numai `install --build-bottle
  --force`, niciodată `reinstall --build-bottle`;
- backup atomic și restaurarea payload-ului/linked state după un test eșuat;
- o cerere Stop nu poate întrerupe rollback-ul bounded al keg-ului original;
- receipt deja bottle-ready fără recompilare;
- dependență nested atribuită lui `pkgconf`, fără forțarea părintelui;
- migrarea țintei nested din eroarea legacy v0.3.3 fără `failed_package`;
- două failed + 10 remaining păstrate în job-ul persistent;
- output read-only, exit code 7 real și comandă mutativă controlată în fixture,
  fără a atinge Homebrew-ul real.

## Verificări release

Apple Notary a acceptat ambele trimiteri:

- app: `ad506683-fc78-4041-baa8-3a8e9ea47f66`;
- DMG: `59d0b2ed-6361-4b7b-8a9c-dd2dd37d3e78`.

Se verifică semnătura, certificatul/Team ID, arhitectura,
stapling-ul, Gatekeeper, DMG-ul read-only, conținutul ZIP/DMG, installerul și
absența configurației/tokenului din bundle. Identificatorii notarizării sunt
păstrați în `dist/app-notarization.json` și `dist/dmg-notarization.json`.

## Limite

- nu s-a executat Retry asupra cozii reale și nu s-au lansat upgrade/reinstall/link reale;
- nu s-a modificat TrueNAS, config-ul, tokenul, spool-ul sau `job.json` real;
- GitHub Actions/CI nu au fost folosite sau modificate; GitHub găzduiește numai
  commitul, tag-ul și artefactele finale produse și validate local;
- validarea fizică pe al doilea Mac rămâne un pas de instalare al operatorului.
