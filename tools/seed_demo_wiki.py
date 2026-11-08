# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Seed the demo wiki as the administrator, so the catalogue shows a real example."""

from __future__ import annotations

import os

import httpx

BASE = os.environ.get("OL_TEST_BASE_URL", "http://openlearn:8000")
EMAIL = os.environ["OL_ADMIN_EMAIL"]
PASSWORD = os.environ["OL_ADMIN_PASSWORD"]
TITLE = "Réseau et DNS"

PAGES = [
    (
        "Résolution DNS",
        """# Résolution DNS

Quand un navigateur demande `example.org`, il ne connaît pas son adresse. La
**résolution** est le mécanisme qui traduit un nom en adresse IP.

## Les trois serveurs

- **Résolveur récursif** : celui de votre fournisseur ou de votre entreprise.
  Il fait le travail à votre place, et garde la réponse en cache.
- **Serveur faisant autorité** : il détient la zone, et il est le seul à
  pouvoir répondre « voici l'adresse ».
- **Serveur racine** : il ne connaît pas `example.org`, il connaît seulement
  qui gère `.org`.

> Si le résolveur répond « je ne sais pas », c'est qu'aucun serveur faisant
> autorité n'a été trouvé : la délégation est cassée quelque part.

## Le cache

Chaque réponse porte une durée de vie, le **TTL**. Le résolveur la garde en
mémoire jusqu'à expiration, ce qui évite de rejouer toute la chaîne à chaque
requête. Un TTL trop long fige une erreur de configuration ; trop court, il
sature les serveurs racines.

Voir aussi [[Types d'enregistrement]] et [[Diagnostic avec dig]].
""",
    ),
    (
        "Types d'enregistrement",
        """# Types d'enregistrement

Chaque zone contient des enregistrements, un par ligne, avec un type.

| Type | Rôle | Exemple |
| --- | --- | --- |
| `A` | Nom vers adresse IPv4 | `93.184.216.34` |
| `AAAA` | Nom vers adresse IPv6 | `2606:2800:220:1::` |
| `CNAME` | Alias vers un autre nom | `www` vers `example.org` |
| `MX` | Serveur de messagerie | `10 mail.example.org` |
| `TXT` | Texte libre, SPF et DKIM | `v=spf1 -all` |

## Le piège du CNAME

Un `CNAME` ne peut pas cohabiter avec un autre enregistrement au même nom.
C'est pour cela qu'on n'en met pas à la racine d'un domaine : la racine porte
déjà `SOA` et `NS`, et souvent `MX` et `TXT`.

Un TTL de **300 s** est un bon compromis pendant une migration.
""",
    ),
    (
        "Diagnostic avec dig",
        """# Diagnostic avec dig

`dig` interroge un serveur précis et affiche la réponse telle quelle.

```bash
dig example.org A
dig @1.1.1.1 example.org +trace
dig example.org MX +short
```

## Lire la réponse

- `status: NOERROR` : la requête a abouti, même si la réponse est vide.
- `status: NXDOMAIN` : le nom n'existe pas.
- `status: SERVFAIL` : le serveur n'a pas pu répondre, souvent une
  délégation cassée.

## Comparer deux résolveurs

```bash
dig @192.168.1.1 example.org A +short
dig @9.9.9.9 example.org A +short
```

Deux réponses différentes signifient un cache local encore chaud, ou un
transfert de zone qui ne s'est pas propagé.
""",
    ),
    (
        "Plan de reprise",
        """# Plan de reprise

Ce qu'on fait quand le DNS de production tombe.

## Les cinq premières minutes

1. Vérifier depuis un poste hors du réseau concerné : le problème est-il chez
   nous ou chez le fournisseur d'accès ?
2. Interroger les deux résolveurs internes, puis `9.9.9.9` : trois réponses
   identiques accusent la zone, trois réponses différentes accusent le cache.
3. Si la zone est en cause, repasser le TTL des enregistrements critiques à
   **60 s** avant toute modification, et attendre l'expiration de l'ancien TTL.

## Après l'incident

- Noter l'heure exacte du premier signalement et celle du retour à la normale.
- Ajouter une surveillance qui interroge la zone toutes les minutes depuis
  deux réseaux différents.
- Relire [[Diagnostic avec dig]] avant de changer quoi que ce soit en zone.
""",
    ),
]


def main() -> int:
    api = httpx.Client(timeout=60, follow_redirects=True)
    api.get(f"{BASE}/api/v1/auth/csrf")
    login = api.post(f"{BASE}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200, login.text
    api.headers["X-CSRF-Token"] = api.cookies.get("ol_csrf") or ""

    existing = [wiki for wiki in api.get(f"{BASE}/api/v1/wiki?scope=mine").json() if wiki["title"] == TITLE]
    if existing:
        wiki_id = existing[0]["id"]
        detail = api.get(f"{BASE}/api/v1/wiki/{wiki_id}").json()
        titles = {page["title"] for page in detail["pages"]}
        print("reusing", wiki_id, sorted(titles))
    else:
        created = api.post(
            f"{BASE}/api/v1/wiki",
            json={
                "title": TITLE,
                "description": "Notes de terrain sur la résolution de noms, écrites pour l'équipe.",
                "default_language": "fr",
            },
        )
        assert created.status_code == 201, created.text
        wiki_id = created.json()["id"]
        titles = set()
        print("created", wiki_id)

    for title, body in PAGES:
        if title in titles:
            continue
        answer = api.post(
            f"{BASE}/api/v1/wiki/{wiki_id}/pages",
            json={"title": title, "content_md": body, "tags": ["dns", "réseau"]},
        )
        print("page", title, answer.status_code)

    # The home page created with the wiki duplicates the topic: give it a front door.
    detail = api.get(f"{BASE}/api/v1/wiki/{wiki_id}").json()
    home = next((page for page in detail["pages"] if page["title"] in {"Accueil", "Home"}), None)
    if home and "Résolution DNS" in {page["title"] for page in detail["pages"]}:
        api.put(
            f"{BASE}/api/v1/wiki/pages/{home['id']}",
            json={
                "title": "Accueil",
                "content_md": (
                    "# Réseau et DNS\n\n"
                    "Notes de terrain sur la résolution de noms, écrites pour l'équipe :\n\n"
                    "- [[Résolution DNS]] — qui répond, et ce que le cache garde.\n"
                    "- [[Types d'enregistrement]] — `A`, `AAAA`, `CNAME`, `MX`, `TXT`.\n"
                    "- [[Diagnostic avec dig]] — lire une réponse sans se tromper.\n"
                    "- [[Plan de reprise]] — les cinq premières minutes d'un incident.\n"
                ),
                "tags": ["dns"],
            },
        )

    published = api.post(f"{BASE}/api/v1/wiki/{wiki_id}/publish", json={"visibility": "public"})
    print("publish", published.status_code, published.json().get("status"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
