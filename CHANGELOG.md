# Changelog

## 0.3.3 — 7 octombrie 2026

- Reconciliere backend-authoritative la cold launch, deschiderea meniului și la
  fiecare 10 secunde. Un job fără erori/restanțe deblochează explicit Update &
  Upgrade, Install și Sync, chiar dacă GUI cache-ul arată vechiul Stopped.
- Repară ordinea grafului: dependențele runtime sunt aduse la zi înainte ca
  formula dependentă să fie considerată current sau să fie construită/publicată.
- Adaugă `Repair / Install Dependency…`, inclusiv pentru `openssl@3`, fără a
  distruge coada; după reparare rulează `brew missing` și `brew linkage --test`.
- Adaugă `Repair Pool State…`: resync UI sau anulare explicită a cozii, păstrând
  instalațiile, bottle-urile, configurația, tokenul și spool-ul.
- Adaugă consola de mentenanță permanent disponibilă: input explicit, output
  stdout/stderr live, istoric în sesiune, Stop Command, exit code și shortcut-uri
  doctor/outdated/missing/linkage.
- Serializează toate comenzile care modifică Homebrew cu lock-ul jobului;
  diagnosticele folosesc shared lock și nu se suprapun peste un writer.
- Închide stdin pentru procesele lansate, nu execută texte din loguri, cere
  confirmare pentru comenzi distructive și delegă autentificarea de administrator
  dialogului nativ macOS fără colectarea parolei.
- Păstrează protocolul server schema 1 și toate funcțiile 0.3.2; adaugă suita
  `tests/test_v033.py` pentru stale UI, dependențe, lock și securitatea consolei.

## 0.3.2 — 7 octombrie 2026

- Adaugă ghidul complet `INSTALLATION.md` pentru server, HTTPS/VPN, storage,
  token și configurarea/verificarea fiecărui Mac.
- Creditează explicit StefanAlMare și colaborarea cu ChatGPT by OpenAI.
- Înlocuiește licența permisivă MIT cu o licență source-available: release-ul
  oficial nemodificat poate fi descărcat și utilizat gratuit, iar reutilizarea,
  modificarea sau redistribuirea codului necesită acordul scris al StefanAlMare.
- Iconițe template cu contrast nativ în menu bar; Healthy, Busy animat, Action
  Required, Paused — Error și Paused/Stopped au simboluri diferite.
- Coada se salvează atomic. Prima eroare oprește procesarea; Retry execută numai
  pașii eșuați, Resume continuă restul, iar erorile rămân vizibile până la rezolvare.
- Stop și Quit sunt disponibile în timpul lucrului. Oprire SIGINT, apoi SIGTERM
  după 8 secunde, SIGKILL numai după încă 4 secunde; și copiii care schimbă sesiunea
  sunt urmăriți. GUI are fallback separat dacă workerul nu răspunde.
- Preflight înainte de update: remotes oficiale legacy, upstream/refspec lipsă și
  launcher brew; fetch --prune + merge --ff-only, păstrând commit-urile locale,
  mirror-urile private și URL-urile tap-urilor externe. Refuză dirty/detached/divergent.
- Modul API nu clonează core/cask. Checkout-ul core se creează numai pentru bottling.
- Suport pentru versiuni calendaristice și separarea stderr; deps acceptă doar
  linii cu nume valide, eliminând mesajele Homebrew din argumentele comenzilor.
- Retry revalidează și o dependență instalată al cărei test a eșuat.
- Teste cu fixture repos, procese copil, pilot Homebrew Intel izolat și pilot GUI.

## 0.3.1 — 7 octombrie 2026

- păstrează `root_url` pentru bottle-urile generate din tap-uri externe;
- normalizează PATH-ul proceselor GUI pentru prefixul Intel Homebrew;
- adaugă starea persistentă Action Required, notificare unică și Review Action;
- păstrează operațiile normale complet automate cu `HOMEBREW_NO_ASK=1`;
- separă vizual Healthy, Busy, Action Required și Error.

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
