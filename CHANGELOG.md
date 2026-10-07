# Changelog

## 0.3.0 — 7 octombrie 2026

- Redenumește acțiunea principală în `Update & Upgrade`.
- Adaugă `Install…` și comanda pool-aware `install`, cu Auto/Formula/Cask și refuzul numelor ambigue.
- Adaugă Setup/Settings nativ: URL, token paste/file, CA, Test Connection și salvare atomică după autentificare/API validate.
- Păstrează adaptoarele/config-ul existente și copiază tokenul într-un fișier privat 0600; testele de conexiune folosesc stare temporară.
- Publică și reutilizează bottles oficiale, bottles locale testate și downloads Cask verificate. Cask-urile mutable au opțiune explicită upstream-only, fără publicare.
- Păstrează patch-ul safe tap sync v0.2.1 și revalidează dirty/detached/divergent înainte de bottling, chiar după o sincronizare anterioară.
- Păstrează Start at Login, Healthy/Connected, spool și loguri; nu introduce upgrade-uri automate.
- Împiedică scrierea bytecode-ului Python în bundle-ul sigilat.
- Distribuie app Intel x86_64 și DMG Developer ID, notarizate Apple și stapled.
- Validează instalările Formula și Cask reale într-un Homebrew temporar, fără operații asupra pachetelor instalării curente.

## 0.2.0 — 7 octombrie 2026

- Adaugă aplicația nativă Intel macOS `Homebrew Pool.app`, cu status item și clientul v0.1 inclus.
- Expune stările `Healthy/Connected`, `Offline/Spooling`, `Busy/Building or Syncing` și `Error`.
- Adaugă comenzile explicite `Sync now`, `Upgrade via Pool`, `Open logs`, `Open config`, `Start at Login` și `Quit`.
- Adaugă pornire la login prin LaunchAgent user-local, fără daemon privilegiat.
- Adaugă installer și uninstaller user-local; dezinstalarea păstrează implicit config-ul, spool-ul și logurile.
- Adaugă status JSON pentru agent, fără schimbarea protocolului sau a logicii backend v0.1.
- Adaugă build Intel `.app`, arhivă ZIP și imagine DMG, cu semnare ad-hoc pentru distribuție privată.

Nu există actualizări Brew automate și nu există workflow-uri sau build-uri GitHub.
