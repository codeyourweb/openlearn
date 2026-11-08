---
layout: doc
title: Les quiz — créer, jouer seul, animer en direct
description: >-
  Créer un quiz dans OpenLearn, rédiger les questions et les corrigés, régler les tentatives,
  publier, jouer en solo, animer une partie en direct avec un PIN, lire les statistiques.
permalink: /guide/quiz/
---

<p class="doc-eyebrow">Guide · Créer, jouer, animer</p>

# Les quiz

Un quiz est une suite de questions à choix. Il se joue seul pour s'entraîner, ou en direct,
animé par un hôte, avec un classement qui se construit question après question.

## Créer un quiz

**Nouveau quiz** (`/quizzes/new`) propose deux méthodes :

- **Manuel** : vous écrivez les questions une par une. C'est la voie normale pour un contenu
  maîtrisé.
- **Assisté** : si l'instance dispose d'un fournisseur de modèle, une description de sujet
  produit une première version des questions. Relisez-la : un modèle propose, il ne vérifie pas.

L'éditeur (`/quizzes/new/<mode>/<variante>` puis `/quizzes/<id>/edit`) présente deux onglets :
**Aperçu** et **Questions**.

## Rédiger les questions

Pour chaque question :

1. **Intitulé** — une phrase, pas un fragment.
2. **Réponses** — au moins deux. Cochez la ou les bonnes ; une question à plusieurs réponses
   affiche **Plusieurs réponses** côté joueur.
3. **Explication** — affichée après la réponse. C'est la partie pédagogique : sans elle, un quiz
   n'apprend rien, il note.
4. **Barème** (facultatif) — une question peut rapporter plus qu'une autre.

<div class="note">
<p><strong>Ce qui fait une bonne question.</strong> Une seule idée par question, des mauvaises
réponses plausibles, pas de « toutes les réponses ci-dessus », et une explication qui tient même
si le joueur a deviné juste. Les tests de l'interface vérifient la forme, pas la pertinence :
c'est votre travail.</p>
</div>

## Régler le déroulé

| Réglage | Effet |
| --- | --- |
| **Tentatives par candidat** | *Illimité (entraînement)* ou *Tentative unique (évaluation)* |
| **Certitude** | Le joueur indique son degré de confiance ; une erreur « sûre » pèse plus qu'une erreur « hésitante » |
| **Zéro point en cas d'erreur** | Supprime les points partiels, pour un barème strict |
| **Langues secondaires** | Traductions du questionnaire, proposées au joueur |

Un quiz en **évaluation** (tentative unique) ne s'ouvre pas deux fois pour le même compte : la
deuxième tentative est refusée, y compris en session en direct.

## Publier

Comme un wiki, un quiz se crée en brouillon puis demande sa **publication**. Un modérateur le
relit ; à la validation, il devient public, apparaît dans le catalogue `/quizzes` et vous
recevez un courriel. Un refus laisse le quiz privé, avec le motif.

Chaque enregistrement crée une **version** (onglet **Versions**), restaurable : modifier un quiz
déjà joué ne réécrit pas les résultats passés, qui restent attachés à la version jouée. Une
version plus ancienne que la courante est marquée **obsolète**.

## Jouer en solo

Depuis la page du quiz, **Jouer** lance une partie classique : questions dans l'ordre, correction
à la fin (ou au fil de l'eau selon le réglage), puis un écran de résultat avec le détail par
question. **Aventures** (`/adventures/new`) permet de construire un parcours enchaînant
plusieurs quiz, avec une progression.

## Animer en direct

1. Sur la page du quiz, **Animer** crée une session et affiche un **PIN** et un lien
   (`/host/<code>` pour l'hôte, `/play/<code>` pour les joueurs, ou `/join/<jeton>` par lien
   direct).
2. Les joueurs rejoignent avec le PIN, choisissent un pseudo.
3. L'hôte lance la première question ; le minuteur tourne ; les réponses arrivent en direct.
4. Le classement s'affiche entre les questions, puis le podium à la fin.

**Vous pouvez jouer aussi** : l'hôte peut participer depuis son propre écran. Attention, un hôte
qui joue **ne bénéficie plus** du régime de l'animateur pour le plafond de tentatives : la règle
suit le candidat, pas le mode de jeu.

## Lire les statistiques

L'onglet **Statistiques** donne, pour un quiz publié : participants, sessions terminées, score
moyen, temps moyen, réponses correctes, et **taux de réussite par question**. C'est là qu'on
repère la question mal formulée — celle que tout le monde rate pour de mauvaises raisons.

**Exporter** produit un CSV des résultats, réutilisable dans un tableur.

## Import et export

Un quiz peut être exporté en JSON et réimporté ailleurs : pratique pour préparer un contenu hors
ligne, le versionner dans Git, ou le dupliquer d'une instance à l'autre.

## Bonnes pratiques d'animation

- Annoncez la règle de certitude avant la première question, sinon les joueurs la découvrent en
  jouant.
- Laissez le commentaire de la question s'afficher : c'est le seul moment où l'explication est
  lue.
- Pour une évaluation notée, utilisez une session en direct **sans** participation de l'hôte :
  le plafond de tentatives s'applique alors à tous les candidats de la même façon.
