---
layout: doc
title: Le wiki — écrire, versionner, relier, publier
description: >-
  Créer un espace wiki dans OpenLearn, écrire des pages en Markdown, suivre l'historique,
  restaurer une version, relier les pages, suggérer une modification et demander la publication.
permalink: /guide/wiki/
---

<p class="doc-eyebrow">Guide · Écrire, versionner, publier</p>

# Le wiki

Un wiki est un espace de pages reliées entre elles, avec un historique. C'est l'endroit où le
savoir s'écrit : une fiche, une procédure, un cours, une notice.

## Créer un espace

1. **Nouveau wiki** (`/wiki/new`).
2. Renseignez le **titre**, une **description** courte et la **langue** de l'espace.
3. Validez : l'espace est créé avec une première page d'accueil.

Vous êtes **propriétaire** de l'espace. Vous pouvez ensuite y inviter des **contributeurs**
(ils écrivent) ou des **administrateurs** (ils gèrent l'espace et ses membres).

## Écrire une page

**Nouvelle page** ouvre l'éditeur (`/wiki/<id>/edit`). Le titre sert d'adresse : « Les volcans »
devient `/wiki/<id>/p/les-volcans`.

L'éditeur est en **Markdown**, avec un aperçu. Quelques bases :

| Pour obtenir | Écrivez |
| --- | --- |
| Un titre de section | `## Titre` |
| Une liste | `- élément` |
| Un lien interne | `[Les volcans](les-volcans)` |
| Un lien externe | `[USGS](https://www.usgs.gov)` |
| Une citation | `> texte` |
| Du code | `` `code` `` ou trois accents graves |
| Un tableau | `| a | b |` puis `| --- | --- |` |

Les titres de section alimentent automatiquement le sommaire **Sur cette page**, à droite.

<div class="note">
<p><strong>Écriture simultanée.</strong> Si deux personnes ouvrent la même page, les
modifications se synchronisent en direct, avec le curseur de chacun. Il n'y a pas de « verrou
d'édition » : la dernière frappe gagne, et l'historique garde la trace de chaque version.</p>
</div>

## Versions et restauration

Chaque enregistrement crée une **version**. **Historique** (`/wiki/<id>/history/<pageId>`) liste
les versions avec leur auteur, leur date et leur différence avec la précédente. Une version
antérieure peut être **restaurée** : elle devient la version courante, sans effacer celles qui
la suivent — l'historique ne se réécrit jamais.

## Relier les pages

- `[Un titre](un-titre)` crée un lien interne ; si la page n'existe pas, le lien est affiché
  comme **rompu** et l'outil propose de la créer.
- **Liens entrants** : sur chaque page, la liste des pages qui pointent vers elle.
- **Graphe de liens** (`/wiki/<id>/graph`) : une vue d'ensemble des pages et de leurs liens, pour
  repérer les îlots et les impasses.
- **Structure** (`/wiki/<id>/structure`) : l'arborescence des pages, pour réorganiser sans
  casser les adresses.
- **Références** (`/wiki/<id>/references`) : pages, sources citées, pages liées, liens rompus,
  pages orphelines — l'état de santé du maillage.

## Modèles de page

**Modèles** (`/wiki/<id>/templates`) propose des structures prêtes à remplir : fiche, procédure,
notice. Un modèle n'est qu'un point de départ ; une fois la page créée, elle vit sa vie.

## Suggérer une modification

Sur une page que vous ne pouvez pas modifier directement, **Suggérer une modification** ouvre le
même éditeur (`/wiki/<id>/propose/<pageId>`). Votre proposition est enregistrée comme une mise à
jour à réviser : les responsables de l'espace voient le nombre de propositions en attente et
peuvent les accepter ou les refuser, avec une note.

## Interroger le wiki

Si l'instance dispose d'un fournisseur de modèle, **Interroger le wiki** (`/wiki/chat`) répond à
une question en s'appuyant sur les pages de l'espace, et cite les pages utilisées. Sans
fournisseur configuré, le bouton n'apparaît pas.

## Publier

Un espace naît **brouillon** ou **privé**. Pour le rendre lisible par tous :

1. ouvrez les réglages de l'espace et demandez la **publication** ;
2. l'espace passe **en attente de révision** — un modérateur le relit ;
3. après validation, il devient **public** et vous recevez un courriel, avec la note du
   modérateur le cas échéant ;
4. en cas de refus, l'espace reste privé et le motif est affiché aux responsables.

| Statut | Qui le voit |
| --- | --- |
| Brouillon | Vous et les membres de l'espace |
| Privé | Les membres invités uniquement |
| En attente de révision | Les membres, et les modérateurs |
| Public | Tout le monde, y compris sans compte |
| Refusé | Les membres ; la publication peut être redemandée après correction |

## Exporter

Depuis un espace : **Exporter (.md)** pour une page, **Exporter (.zip)** pour l'ensemble des
sources, **Exporter le wiki en PDF** pour une version imprimable. L'export Markdown est
volontairement brut : il doit rester lisible dans un éditeur de texte et réimportable ailleurs.

## Rechercher

La recherche (`/wiki`) porte sur les titres et les contenus, avec un filtre **Tous les wikis** /
**Mes wikis**. Depuis l'éditeur, <kbd>Ctrl</kbd> + <kbd>F</kbd> cherche dans la page courante.
