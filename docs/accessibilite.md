---
title: Accessibilité WCAG 2.2 AA — engagement et méthode
description: >-
  Comment OpenLearn tient WCAG 2.2 AA : navigation clavier, contrastes, annonces vocales,
  réduction des animations, tests automatisés dans l'intégration continue.
permalink: /accessibilite/
---

# Accessibilité

<p class="muted small">Objectif tenu : WCAG 2.2 niveau AA sur les parcours principaux.</p>

## Pourquoi c'est un plancher, pas un argument

Une plateforme d'apprentissage s'adresse par définition à des gens qui apprennent — dont une
part significative rencontre des difficultés de lecture, de vision, d'attention ou de
motricité. Livrer une interface qui exclut une partie de ces personnes n'est pas seulement un
défaut juridique : c'est un contresens pédagogique.

L'accessibilité a donc été traitée comme une contrainte de conception, dès la première ligne
d'interface, et non comme une campagne de rattrapage.

## Ce qui est effectivement en place

- **Structure sémantique** : un seul `h1` par écran, hiérarchie de titres continue, régions
  `header`/`main`/`nav`/`footer`, listes pour les listes.
- **Clavier** : tous les parcours réalisables sans souris (connexion, création de quiz, partie
  en direct, édition de page, révision). Ordre de tabulation naturel, pas de piège au clavier.
- **Focus visible** : anneau de focus de 3 px, jamais supprimé, contraste suffisant sur les
  deux thèmes.
- **Contrastes** : palette choisie pour viser le niveau AAA sur le texte courant et 3:1
  minimum sur les composants ; le contrôle automatique échoue en dessous de AA.
- **Formulaires** : chaque champ a un `label` associé, les erreurs sont liées au champ par
  `aria-describedby`, et le message d'erreur est annoncé.
- **États dynamiques** : les changements de score, les confirmations et les erreurs passent par
  des régions `role="status"` ou `aria-live`, jamais par un simple changement de couleur.
- **Mouvement** : `prefers-reduced-motion` supprime les transitions et les animations de jeu.
- **Langue** : `lang` correct par écran, y compris bascule `dir="rtl"` pour l'arabe.
- **Zoom et reflow** : utilisable jusqu'à 200 % sans perte de contenu ni défilement horizontal.
- **Cibles tactiles** : au moins 24 × 24 px partout (critère 2.5.8), davantage sur les actions
  principales.

## Comment c'est vérifié

Trois niveaux, tous exécutés à chaque *pull request* :

1. **Contrôles statiques** dans la suite de tests : présence des libellés, des alternatives
   textuelles, des liens d'évitement, absence d'`onclick` en attribut, unicité du `h1`.
2. **Audit automatique axe-core** au navigateur sur les écrans principaux (accueil, connexion,
   tableau de bord, wiki, quiz, administration), avec échec de la construction en cas de
   violation sérieuse.
3. **Revue manuelle** avant chaque version : parcours complet au clavier, lecteur d'écran
   (NVDA et VoiceOver), zoom 200 %, thème sombre.

Un audit automatique ne remplace pas un test humain : il attrape les oublis mécaniques, pas
les ambiguïtés. Les deux sont nécessaires.

## Signaler un problème d'accessibilité

Ouvrez une *issue* avec l'étiquette `accessibility` en précisant : l'écran concerné, le
navigateur, la technologie d'assistance utilisée, et ce que vous attendiez. Une régression
d'accessibilité est traitée comme un défaut bloquant, pas comme une amélioration.

Si vous ne pouvez pas passer par GitHub, écrivez à `developper@openlearnproject.org` : le
message sera recopié dans le suivi public, sauf si vous demandez le contraire.
