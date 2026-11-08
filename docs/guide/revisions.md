---
layout: doc
title: Les révisions — fiches, jeux de cartes, répétition espacée
description: >-
  Créer un jeu de fiches dans OpenLearn depuis un wiki, un quiz ou à la main, réviser avec la
  répétition espacée, imprimer une fiche, publier un jeu.
permalink: /guide/revisions/
---

<p class="doc-eyebrow">Guide · Cartes et répétition espacée</p>

# Les révisions

Un quiz constate ce qu'on sait à un instant donné. Une fiche de révision fait le contraire :
elle revient au bon moment pour que la connaissance reste. OpenLearn relie les deux — chaque
mauvaise réponse peut devenir une fiche.

## Ce qu'est un jeu de fiches

Un **jeu** contient des **fiches**, chacune avec un recto (la question) et un verso (la
réponse), éventuellement une image au verso. Un jeu peut appartenir à un wiki, ce qui le rend
visible depuis les pages de cet espace.

## Créer un jeu

**Nouveau jeu** (`/cards`) propose trois sources :

1. **Depuis une page wiki** — le texte de la page est découpé en fiches (titres et définitions,
   listes, tableaux). Relisez : un découpage automatique produit du bruit, il ne comprend pas
   le sens.
2. **Depuis un questionnaire** — chaque question devient une fiche. C'est la voie la plus
   fiable : la question a déjà un corrigé rédigé.
3. **Saisie manuelle** — vous écrivez recto et verso, avec le format de carte souhaité.

## Réviser

**Réviser** (`/cards/<id>/study`) ouvre la session. Pour chaque fiche :

1. le recto s'affiche ; vous répondez mentalement (ou à voix haute) ;
2. vous retournez la carte ;
3. vous indiquez si c'était **facile**, **juste** ou **à revoir**.

De ces trois réponses dépend l'intervalle avant la prochaine présentation : une fiche sue revient
dans plusieurs jours, une fiche ratée revient dans la session ou le lendemain. L'algorithme est
volontairement simple — un SM-2 dépouillé — parce qu'un planificateur opaque n'apprend rien à
celui qui l'utilise.

<div class="note">
<p><strong>Ce que l'honnêteté change.</strong> Répondre « facile » sur une fiche dont vous avez
oublié la moitié allonge l'intervalle et vous fera perdre du temps dans trois semaines. La
machine ne peut pas vérifier : la qualité de la révision dépend entièrement de la sincérité de
la réponse.</p>
</div>

## Publier un jeu

Un jeu est privé par défaut. **Publier** le rend visible dans l'onglet **Publiés** ; **Passer en
privé** le retire. Contrairement aux wikis et aux quiz, la publication d'un jeu de fiches ne
passe pas par la modération : la carte est un outil de travail, pas une publication éditoriale.

## Imprimer

**Imprimer la fiche** produit une version papier du jeu, recto/verso, à découper. C'est encore la
manière la plus rapide de réviser dans le train.

## Voir ses progrès

Depuis `/cards`, l'onglet **Mes jeux** indique le nombre de fiches et l'état de chacune (nouvelle,
en cours, sue). Un jeu dont toutes les fiches sont « sues » reste révisable : l'oubli est
normal, et l'intervalle finira par s'allonger à nouveau.
