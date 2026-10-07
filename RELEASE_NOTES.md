# Homebrew Intel Bottle Pool 0.3.3 — Release Notes

Data: 7 octombrie 2026. Build: Intel x86_64, macOS 12+.

## Recovery prioritar

Versiunea 0.3.3 elimină blocarea în care aplicația rămânea vizual
`Paused / Stopped`, cu numai `Resume` și `Stop`, deși backendul raporta `idle`,
zero eșecuri și zero pași rămași. La cold launch, la deschiderea meniului și apoi
la fiecare 10 secunde, starea schema 1 a backendului este autoritară. Cache-urile
GUI reziduale și joburile deja rezolvate nu mai blochează operațiile normale.

`Repair Pool State…` oferă două acțiuni explicite:

- reconcilierea UI cu backendul;
- `Discard Pending Job`, care anulează numai coada rămasă și păstrează formulae,
  Cask-uri, bottle-uri, config, token și spool deja existente.

## Dependențe înainte de formula dependentă

Graful topologic al dependențelor runtime este verificat și adus la zi înainte ca
formula dependentă să fie declarată current sau să ajungă la build/publicare.
Scenariul `coreutils: Runtime dependency not current: openssl@3` are o cale de
recovery dedicată: `Repair / Install Dependency…`, apoi `Retry Failed` și
`Resume`. Coada originală rămâne intactă. După reparație se rulează `brew
missing` și `brew linkage --test`, iar retry-ul reface validarea contextului
formula/dependențe înainte de publicarea bottle-ului.

## Maintenance Console

Noua consolă este disponibilă permanent din meniu, inclusiv în Healthy, Offline,
Paused, Stopped, Action Required și Error. Oferă:

- câmp pentru o comandă lansată numai prin acțiunea explicită Run;
- stdout/stderr live, istoric vizibil în sesiune, Stop Command și exit code;
- shortcut-uri `brew doctor`, `brew outdated`, `brew missing` și
  `brew linkage --test`;
- comenzi arbitrare explicite pentru diagnostic sau reparare Homebrew/Pool.

Comenzile care modifică Homebrew folosesc același lock exclusiv ca joburile
normale. Diagnosticele read-only folosesc shared lock și nu rulează peste un
writer. Stdin este închis, textul logurilor nu este executat, iar comenzile
distructive cer confirmare. Un prefix `sudo` este delegat dialogului nativ macOS;
aplicația nu colectează parola. Consola nu modifică resursele de cod ale app-ului
semnat/notarizat; bug-urile de cod se livrează printr-un release semnat ulterior.

## Compatibilitate păstrată

Rămân disponibile Update & Upgrade, Install Auto/Formula/Cask, Settings, Sync
now, Start at Login, logurile, iconițele template adaptive, versiunile de tip
dată, filtrarea outputului `brew deps`, `root_url` pentru tap-uri externe, PATH
Intel și self-heal remotes exclusiv prin fetch + fast-forward. Protocolul server
rămâne schema 1; nu există schimbări de token sau server privat.

Release-ul este local. Nu au fost create sau modificate repository-uri, Actions,
CI ori release-uri GitHub.

## Validare finală

- 104 teste automate: OK;
- pilot GUI compilat, inclusiv cold-launch stale UI versus backend idle: OK;
- pilot Homebrew real și izolat pentru Formula și Cask: OK;
- app și DMG Developer ID: Apple Accepted, stapled și Gatekeeper accepted;
- bundle `0.3.3` build `33`, Intel x86_64, deployment macOS 12.
