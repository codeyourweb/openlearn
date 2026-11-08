---
title: Fonctionnalités — wiki, quiz, révisions espacées, API et MCP
description: >-
  Détail des fonctions d'OpenLearn : wiki versionné en Markdown, quiz en direct, cartes de
  révision, rôles et modération, API REST, serveur MCP, import/export, sauvegarde.
permalink: /fonctionnalites/
---

# Fonctionnalités

<p class="muted small">Ce que le logiciel fait aujourd'hui, sans liste de souhaits.</p>

## Wiki collaboratif

- **Pages en Markdown**, rendues avec un assainissement strict (liste blanche de balises).
- **Versions** : chaque enregistrement crée une révision consultable et restaurable.
- **Structure** : arborescence de pages, sections, et graphe visuel des liens entre pages.
- **Références** : bibliographie par page, citations réutilisables, détection des liens morts.
- **Recherche** plein texte sur les titres et contenus, avec filtrage par espace.
- **Modèles de page** pour les formats récurrents (fiche, procédure, notice).
- **Publication en deux temps** : un brouillon, puis une demande de publication ; la page
  devient publique après validation par un modérateur.
- **Assistant IA facultatif** : un panneau de discussion ancré sur la page courante, activé
  seulement si l'administrateur a configuré un fournisseur. Sinon, il n'existe pas dans
  l'interface.

## Quiz

- Questions à **choix unique** ou **multiple**, nombre d'options libre, explication par option.
- **Échelles de certitude** : l'apprenant indique son degré de confiance, ce qui distingue
  une erreur d'inattention d'une lacune réelle.
- **Mode en direct** : un hôte lance la partie, les joueurs rejoignent par code, les questions
  défilent, un classement se construit. Utile en salle comme à distance.
- **Parties solo** avec plafond de tentatives configurable par quiz.
- **Évaluation** : score, détail par question, temps par question, export CSV.
- **Import / export JSON** pour préparer un quiz hors ligne et le charger ensuite.

## Révisions espacées

Une mauvaise réponse peut être transformée en **carte de révision**. Le moteur resservira la
carte après un intervalle qui s'allonge à chaque réussite (algorithme de type SM-2 simplifié),
et se raccourcit en cas d'échec. Les cartes sont regroupées en paquets, par thème ou par quiz.

## Comptes, rôles et modération

| Rôle | Peut | Ne peut pas |
| --- | --- | --- |
| Visiteur | Lire les contenus publics, jouer aux quiz publics | Écrire |
| Auteur | Créer wiki et quiz, demander leur publication | Publier directement |
| Modérateur | Approuver ou refuser les publications, gérer les signalements | Accéder à la configuration IA, courriel ou SSO |
| Administrateur | Tout, y compris comptes, courriel, IA, SSO, sauvegardes | — |

- **Vérification d'adresse** par lien envoyé à l'inscription, renvoyable depuis le compte.
- **Réinitialisation de mot de passe** limitée à un envoi toutes les cinq minutes par adresse.
- **Protection anti-spam** : un visiteur qui martèle un formulaire (connexion, réinitialisation,
  inscription) reçoit un bannissement temporaire, en mémoire, sans système de réputation.
- **Notification de publication** : un courriel prévient l'auteur dès que son wiki ou son quiz
  passe en public, avec la note éventuelle du modérateur.

## Interface et API

- **Douze langues** : français, anglais, allemand, espagnol, italien, russe, chinois, japonais,
  portugais, hindi, bengali, arabe — avec bascule automatique en écriture de droite à gauche.
- **Thème clair et thème sombre**, contraste vérifié, respect de `prefers-reduced-motion`.
- **Navigation clavier** complète, lien d'évitement, annonces vocales sur les changements d'état.
- **API REST documentée** (OpenAPI) : tout ce que fait l'interface passe par l'API.
- **Clés d'API** par compte, avec portée et révocation.
- **Serveur MCP** : un agent (Claude, ou tout client compatible) peut lire et créer des pages
  et des quiz avec les droits du compte qui l'autorise.

## Exploitation

- **Une image Docker**, SQLite par défaut, PostgreSQL possible pour les instances chargées.
- **Sauvegarde** : copie cohérente de la base (`.backup`), archive des médias, script fourni.
- **Restauration** documentée et testée.
- **Déploiement sûr** : conserve l'image précédente, permet un retour arrière immédiat, mesure
  l'interruption, et refuse de remplacer une instance dont les compteurs de contenus baissent.
- **Santé** exposée sur `/api/v1/health` pour une supervision simple.
- **Authentification unique** OIDC (Keycloak, Authentik, Google Workspace…) en option.

<p class="muted small">
Une fonction absente de cette page n'existe pas encore. Le suivi des demandes se fait dans les
issues du dépôt, pas dans une feuille de route tenue secrète.
</p>
