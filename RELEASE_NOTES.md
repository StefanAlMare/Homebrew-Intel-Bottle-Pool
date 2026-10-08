# Homebrew Intel Bottle Pool 0.3.4 — Release Notes

Data: 8 octombrie 2026.

## Hotfix Retry Failed

Pentru un keg deja instalat și curent care nu are receipt `built_as_bottle`,
clientul nu mai apelează combinația invalidă `brew reinstall --build-bottle`.
Folosește comanda acceptată de Homebrew:

`brew install --formula --build-bottle --force [--as-dependency] FORMULA`

Înainte de comandă, keg-ul curent este mutat atomic într-un backup al aceluiași
rack/volum. La orice eșec ulterior — build, `brew bottle`, postinstall, test,
hash/manifest/context sau publicare — keg-ul nou este eliminat și cel original
este restaurat, inclusiv starea linked. Backup-ul este șters numai după validarea
completă și păstrarea bottle-ului în spool. Dacă receipt-ul este deja
`built_as_bottle`, compilarea este omisă și se reiau doar bottle/test/validare.
O cerere Stop oprește build-ul, dar nu întrerupe pașii bounded de unlink/link
necesari restaurării keg-ului original.

Retry folosește `failed_package` când eroarea aparține unei dependențe nested.
Astfel, cazul `fastfetch` → `pkgconf` repară/revalidează `pkgconf` fără a forța o
recompilare inutilă a lui `fastfetch`. Pașii pending rămân în `job.json` și se
execută numai după Resume.
Pentru cozi create de v0.3.3, care nu aveau încă `failed_package`, hotfix-ul
recuperează strict numele din diagnosticul Homebrew salvat
`Formula was not installed with --build-bottle` fără a modifica anticipat job-ul.

## Hotfix Maintenance Console

Argumentul positional nu mai suprascrie subcomanda argparse `maintenance`.
Backend-ul primește acum `maintenance_command`, execută exact șirul introdus,
păstrează stdout/stderr live și returnează codul real al procesului. Interfața
nu mai poate afișa `[exit code 0]` pentru o comandă care nu a fost lansată.

Protecția comenzilor distructive, autorizarea administrator, locking-ul,
stdin-ul închis și eliminarea secretului din mediu sunt neschimbate.

## Compatibilitate și operare

- bundle `0.3.4`, build `34`, Intel x86_64, minimum macOS 12;
- protocolul pool/schema 1 este neschimbat și compatibil cu v0.3.3;
- config-ul, tokenul, spool-ul și `job.json` existente sunt păstrate la instalare;
- aplicația nu lansează automat upgrade-uri sau comenzi de mentenanță;
- nu s-a modificat TrueNAS; build-ul, testele, semnarea și notarizarea au fost
  executate local, iar GitHub este folosit numai pentru distribuirea release-ului final.
