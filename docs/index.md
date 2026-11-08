---
title: OpenLearn — un wiki et des quiz libres pour apprendre sans compte publicitaire
description: >-
  OpenLearn réunit un wiki collaboratif, un moteur de quiz et des révisions espacées dans une
  seule application libre, auto-hébergeable, accessible WCAG 2.2 AA et traduite en douze langues.
permalink: /
---

<section class="hero">
  <h1>Apprendre ensemble, sans rien céder sur la liberté ni sur l'accessibilité.</h1>
  <p class="lead">
    OpenLearn est une plateforme d'apprentissage auto-hébergée : un wiki pour écrire les savoirs,
    un moteur de quiz pour les vérifier, et des cartes de révision pour les garder. Pas de traceur
    publicitaire, pas de dépendance à une plateforme — juste un serveur, un navigateur, et les
    gens qui se servent du logiciel.
  </p>
  <div class="hero-actions">
    <a class="btn btn-primary" href="{{ site.demo_url }}">Essayer l'instance de démonstration</a>
    <a class="btn" href="{{ '/guide/' | relative_url }}">Lire le guide d'utilisation</a>
    <a class="btn" href="https://github.com/{{ site.repository }}">Code source</a>
  </div>
  <p class="muted small" style="margin-top:1.25rem">
    Licence AGPL-3.0-only · FastAPI + SQLite · Docker · WCAG 2.2 AA · 12 langues
  </p>
</section>

## Ce que fait le logiciel

OpenLearn réunit trois gestes qui vont ensemble : écrire ce qu'on sait, le faire réciter, et
revenir dessus au bon moment.

<div class="grid">
  <div class="card">
    <h3>Un wiki qui n'a pas peur des renvois</h3>
    <p>
      Pages en Markdown, versions, structure hiérarchique, graphe des liens, références
      croisées et citations. La page sait toujours qui l'a modifiée et ce qui a changé.
    </p>
  </div>
  <div class="card">
    <h3>Un moteur de quiz complet</h3>
    <p>
      Questions à choix unique ou multiple, échelles de certitude, mode en direct animé par un
      hôte, parties solo, évaluation détaillée et export des résultats.
    </p>
  </div>
  <div class="card">
    <h3>Des révisions espacées</h3>
    <p>
      Chaque mauvaise réponse peut devenir une carte, resservie après un intervalle qui
      s'allonge quand elle revient juste. C'est la pédagogie la plus ancienne et la plus
      solide qui soit : répétition, à intervalles croissants.
    </p>
  </div>
  <div class="card">
    <h3>Un espace pour chaque équipe</h3>
    <p>
      Comptes, avatars, rôles (auteur, modérateur, administrateur), clés d'API et accès MCP
      donnent à un agent ou à un outil externe de quoi lire et créer du contenu sans passer
      par l'interface.
    </p>
  </div>
  <div class="card">
    <h3>Un serveur, pas un abonnement</h3>
    <p>
      Une image Docker, SQLite par défaut, sauvegarde et restauration en une commande. Un
      serveur modeste suffit pour une promotion entière.
    </p>
  </div>
  <div class="card">
    <h3>Douze langues, dont l'arabe en droite à gauche</h3>
    <p>
      Français, anglais, allemand, espagnol, italien, russe, chinois, japonais, portugais, hindi,
      bengali et arabe — chaque écran est traduit, pas seulement la page d'accueil.
    </p>
  </div>
</div>

## La question qui a décidé de l'architecture

> La plupart des plateformes d'apprentissage en ligne facturent l'accès au savoir, tracent
> chaque clic, et gardent les contenus enfermés. Nous voulions l'inverse : un logiciel qu'une
> association, un lycée, un laboratoire ou une famille puisse poser sur son serveur, laisser
> tourner dix ans, et quitter quand bon lui semble sans perdre une ligne.

Ce choix a des conséquences techniques, assumées une par une. La suite est décrite dans
[la philosophie du projet]({{ '/philosophie/' | relative_url }}) : pourquoi l'AGPL plutôt que MIT,
pourquoi un compte facultatif, pourquoi l'accessibilité n'est pas une couche optionnelle, et
comment le projet refuse de mesurer les gens.

## La documentation

Le guide d'utilisation décrit chaque fonction, écran par écran, avec les chemins réels de
l'application :

<div class="grid">
  <div class="card">
    <h3><a href="{{ '/guide/demarrage/' | relative_url }}">Démarrer</a></h3>
    <p>Compte, confirmation d'adresse, connexion, navigation, langues, thème.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/wiki/' | relative_url }}">Le wiki</a></h3>
    <p>Écrire en Markdown, versionner, restaurer, relier les pages, publier.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/quiz/' | relative_url }}">Les quiz</a></h3>
    <p>Créer, régler les tentatives, jouer en solo, animer en direct, lire les statistiques.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/revisions/' | relative_url }}">Les révisions</a></h3>
    <p>Fiches, jeux de cartes, répétition espacée, impression.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/moderation/' | relative_url }}">Modérer et administrer</a></h3>
    <p>File de publication, notes aux auteurs, comptes, courriel, IA, SSO, bannissements.</p>
  </div>
  <div class="card">
    <h3><a href="{{ '/guide/api-mcp/' | relative_url }}">API et MCP</a></h3>
    <p>Clés d'API, référence OpenAPI, branchement d'un agent.</p>
  </div>
</div>

## À qui cela s'adresse

- **Une équipe pédagogique** qui veut un espace de cours sans dépendre d'un fournisseur.
- **Une association de vulgarisation** qui écrit des fiches et veut les faire réviser.
- **Un club de jeux de connaissances**, qui a besoin d'un mode en direct et d'un classement.
- **Une administration soumise à des exigences d'accessibilité** et de souveraineté des données.
- **Un développeur** qui cherche un exemple lisible d'API FastAPI, de wiki versionné et de
  composants front accessibles.

## État du projet

Le logiciel est utilisé publiquement : [openlearnproject.org]({{ site.demo_url }}) est une
instance de démonstration ouverte, alimentée par un catalogue de contenus d'exemple. Le code
est complet, testé (plus de 450 tests back-end et une suite de bout en bout au navigateur),
et publié sous AGPL-3.0-only avec un CLA pour la contribution.

<p class="muted small">
OpenLearn est écrit par <a href="{{ site.author.url }}">{{ site.author.name }}</a> et publié
sous licence AGPL-3.0-only. La marque OpenLearn et l'instance de démonstration ne sont pas
cédées avec le code : voir les conditions de marque du dépôt.
</p>
