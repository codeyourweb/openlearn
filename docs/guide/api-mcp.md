---
layout: doc
title: API et MCP — automatiser OpenLearn et y brancher un agent
description: >-
  Utiliser l'API HTTP d'OpenLearn avec une clé personnelle, parcourir la référence OpenAPI, et
  connecter un agent au serveur MCP avec les droits d'un compte.
permalink: /guide/api-mcp/
---

<p class="doc-eyebrow">Guide · Automatiser et brancher un agent</p>

# API et MCP

Tout ce que fait l'interface passe par une API HTTP : il n'existe pas de chemin privilégié.
C'est ce qui rend l'automatisation possible, et c'est aussi la raison pour laquelle une clé
d'API doit être traitée comme un mot de passe.

## Se procurer une clé

1. **Compte** → **Clés d'API** → **Créer une clé**.
2. Nommez-la d'après son usage (« import de fiches », « robot de sauvegarde »).
3. Copiez la valeur : elle n'est plus affichée ensuite.
4. Révoquez-la dès qu'elle n'est plus utile.

Chaque clé agit **avec les droits du compte** qui l'a créée. Il n'existe pas de portée plus
fine : si vous voulez une clé en lecture seule, créez un compte dédié.

## Appeler l'API

```bash
curl -H "Authorization: Bearer $OPENLEARN_KEY" \
     https://votre-instance.example/api/v1/auth/me
```

Les ressources suivent les objets du produit : `/api/v1/wiki`, `/api/v1/quizzes`,
`/api/v1/cards`, `/api/v1/auth`, `/api/v1/admin`. Les échecs reviennent avec un code HTTP
explicite — 401 non authentifié, 403 interdit, 404 absent, 409 conflit, 422 validation, 429 trop
de requêtes.

Deux règles pratiques :

- Les écritures attendent un jeton CSRF quand vous utilisez une session de navigateur ; avec une
  clé d'API, l'en-tête `Authorization` suffit.
- Les listes sont paginées. Un script qui ignore la pagination croira qu'il n'y a que la
  première page.

## La référence complète

Chaque instance publie sa propre référence, générée depuis le code :

- `/docs` — explorateur OpenAPI, avec un filtre de recherche ;
- `/api/openapi.json` — le document brut, à charger dans Postman, Insomnia, ou à générer en
  client typé.

La référence d'une instance reflète exactement sa version : c'est plus fiable qu'une
documentation recopiée à la main.

## Le serveur MCP

OpenLearn embarque un serveur **MCP** (Model Context Protocol). Un agent — un assistant de
bureau, un client MCP, un script d'orchestration — peut ainsi lire et créer des pages de wiki ou
des quiz, avec les droits du compte qui l'autorise.

- L'activation se fait côté serveur (`OL_MCP_ENABLED`) ; l'onglet **Environnement** de
  l'administration indique si c'est le cas.
- L'écran `/docs/mcp` de l'instance donne l'URL du point d'entrée et les outils exposés.
- L'authentification se fait avec une clé d'API : un agent n'a jamais plus de droits que la clé
  qu'on lui confie.

<div class="note">
<p><strong>Un agent écrit, il ne relit pas.</strong> Un modèle qui rédige une page de wiki produit
une page plausible, pas une page vraie. Dans un usage pédagogique, faites relire : la
responsabilité éditoriale ne se délègue pas à une clé d'API.</p>
</div>

## Cas d'usage raisonnables

| Objectif | Moyen |
| --- | --- |
| Importer un catalogue de questions préparé ailleurs | `POST /api/v1/quizzes` puis ajout des questions |
| Sauvegarder les pages d'un wiki en Markdown | `GET /api/v1/wiki` puis export par page |
| Alimenter un tableau de bord de résultats | Export CSV depuis l'interface, ou les points d'entrée de statistiques |
| Faire rédiger un brouillon de fiche par un agent | Clé dédiée, puis relecture humaine avant publication |
| Synchroniser avec un ENT ou un autre wiki | Import/export JSON, ou appels API planifiés |

## Limites à connaître

- Les **plafonds de débit** s'appliquent aussi aux clés : un import massif doit ralentir ou
  échelonner ses appels.
- Les **droits suivent le compte** : une clé d'auteur ne peut pas publier, elle ne peut que
  demander la publication.
- Une **suppression** reste une suppression, même par API : il n'y a pas de corbeille générale.
  Sauvegardez avant d'écrire un script qui efface.
