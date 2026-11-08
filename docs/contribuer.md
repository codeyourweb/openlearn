---
title: Contribuer à OpenLearn — code, contenus, traductions, accessibilité
description: >-
  Comment contribuer au projet OpenLearn : signaler un défaut, proposer une traduction, écrire
  du contenu de démonstration, envoyer une pull request, signer le CLA.
permalink: /contribuer/
---

# Contribuer

<p class="muted small">Le projet accepte les contributions de code, de traduction, de contenu et de
signalement. Voici comment, dans l'ordre du plus utile au plus engageant.</p>

## Signaler un défaut

Une *issue* bien écrite vaut mieux qu'un correctif écrit sans contexte. Précisez :

- ce que vous faisiez, ce que vous attendiez, ce qui s'est produit ;
- la page ou le point d'entrée concerné ;
- la version (bas de page de l'instance) et le navigateur ;
- pour un défaut visuel, une capture ; pour un défaut d'accessibilité, la technologie
  d'assistance utilisée.

Les défauts d'**accessibilité** portent l'étiquette `accessibility` et sont traités comme
bloquants.

## Traduire

Les douze langues vivent dans `frontend/js/locales/`. Une contribution de traduction doit :

- couvrir **toutes** les clés (un test le vérifie, l'intégration continue échoue sinon) ;
- respecter le ton du produit : phrases courtes, pas de jargon, pas d'anglicismes inutiles ;
- conserver les variables (`{n}`, `{total}`) intactes ;
- pour l'arabe, ne jamais forcer la direction du texte dans la chaîne : la mise en page s'en
  charge.

## Écrire du contenu

Un catalogue de démonstration existe (`backend/app/demo_content.py` et les données associées).
Une contribution de contenu doit être **vraie**, sourcée quand le sujet le demande, et courte :
une page de démonstration sert à montrer le produit, pas à enseigner un domaine.

## Proposer du code

1. Ouvrez une *issue* pour discuter de l'intention, surtout s'il s'agit d'une fonction nouvelle.
2. Forkez le dépôt, créez une branche au nom explicite.
3. Écrivez le code **et** les tests ; le style suit `pyproject.toml` (ruff) pour le Python.
4. Vérifiez localement : `pytest -m "not e2e"`, `ruff check backend tests`, `shellcheck`.
5. Ouvrez une *pull request* ; l'intégration continue exige le lint, les tests, les tests de bout
   en bout et le contrôle d'accessibilité.
6. Signez le CLA (voir `CLA.md`) — il autorise le projet à distribuer votre contribution sous
   AGPL-3.0-only, sans vous retirer vos droits d'auteur.

## Ce que nous refusons

- Une dépendance qui collecte des données ou charge un script tiers.
- Un composant d'interface inaccessible « en attendant mieux ».
- Une fonction dont le besoin ne tient pas en une phrase.
- Une réécriture massive sans discussion préalable : le code a une histoire, elle compte.

## Conditions de marque

Le code est libre ; le nom **OpenLearn** et l'instance de démonstration ne sont pas cédés avec la
licence. Un déploiement dérivé doit utiliser un autre nom et ne pas se présenter comme
l'instance officielle. Voir `TRADEMARK.md` dans le dépôt.

## Contact

`developper@openlearnproject.org` pour ce qui ne peut pas passer par GitHub (données
personnelles, question de licence, signalement sensible).
