---
layout: doc
title: Guide d'utilisation — prendre en main OpenLearn
description: >-
  Le guide utilisateur d'OpenLearn, fonction par fonction : écrire dans le wiki, créer et animer
  des quiz, réviser avec des cartes, gérer son compte, modérer les publications.
permalink: /guide/
---

<p class="doc-eyebrow">Guide d'utilisation</p>

# Prendre en main OpenLearn

Ce guide décrit le logiciel tel qu'il se présente aujourd'hui, écran par écran. Il ne suppose
aucune connaissance technique : si vous savez utiliser un navigateur, vous saurez écrire une
page de wiki et lancer un quiz.

Chaque page suit la même logique : **à quoi ça sert**, **où cela se trouve**, **comment on s'en
sert**, et **les pièges ordinaires**. Les chemins indiqués (`/wiki/new`, `/quizzes/new`…) sont
ceux de l'instance de démonstration ; ils sont identiques sur toute instance du logiciel.

## Par où commencer

<ol class="steps">
  <li><strong>Créez un compte</strong> sur l'instance, puis ouvrez le lien de confirmation que
  vous recevez par courriel. Tant que l'adresse n'est pas confirmée, l'application fonctionne
  normalement mais affiche un bandeau de rappel.</li>
  <li><strong>Ouvrez le tableau de bord</strong> (<code>/dashboard</code>) : il liste vos wikis,
  vos quiz et vos cartes, et c'est de là que partent toutes les créations.</li>
  <li><strong>Écrivez une première page</strong> dans un espace wiki, ou
  <strong>créez un quiz</strong> de cinq questions pour tester le mode en direct.</li>
  <li><strong>Demandez la publication</strong> : votre contenu devient public après validation
  par un modérateur, qui vous envoie alors un courriel.</li>
</ol>

## Les trois objets du logiciel

<div class="grid">
  <div class="card">
    <h3>Le wiki</h3>
    <p>Un espace de pages en Markdown, versionnées, structurées et publiables. C'est là qu'on
    écrit le savoir. <a href="{{ '/guide/wiki/' | relative_url }}">Guide du wiki</a></p>
  </div>
  <div class="card">
    <h3>Le quiz</h3>
    <p>Une suite de questions à choix, jouable seul, entre amis ou animée en salle.
    <a href="{{ '/guide/quiz/' | relative_url }}">Guide des quiz</a></p>
  </div>
  <div class="card">
    <h3>La carte de révision</h3>
    <p>La mémoire du quiz : une question, une réponse, et un intervalle qui s'allonge quand
    vous réussissez. <a href="{{ '/guide/revisions/' | relative_url }}">Guide des révisions</a></p>
  </div>
</div>

## Selon qui vous êtes

| Vous êtes | Commencez par | Puis |
| --- | --- | --- |
| Visiteur | Lire les wikis publics, jouer aux quiz publics | Créer un compte pour écrire |
| Auteur | [Démarrer]({{ '/guide/demarrage/' | relative_url }}) | [Écrire dans le wiki]({{ '/guide/wiki/' | relative_url }}), [créer un quiz]({{ '/guide/quiz/' | relative_url }}) |
| Modérateur | [Modérer]({{ '/guide/moderation/' | relative_url }}) | Valider les publications, suivre les signalements |
| Administrateur | [Administrer]({{ '/guide/moderation/' | relative_url }}) | Paramètres, comptes, courriel, IA, SSO, sauvegardes |
| Développeur | [API et MCP]({{ '/guide/api-mcp/' | relative_url }}) | Automatiser, brancher un agent |
| Exploitant | [Auto-hébergement]({{ '/auto-hebergement/' | relative_url }}) | Sauvegarde, restauration, mises à jour |

## Ce qui n'est pas dans ce guide

L'installation, la sauvegarde et les mises à jour sont du ressort de l'exploitant : elles sont
décrites dans [Auto-héberger OpenLearn]({{ '/auto-hebergement/' | relative_url }}). La référence
complète des points d'entrée HTTP est intégrée au logiciel, à l'adresse `/docs` de votre
instance, et résumée dans [API et MCP]({{ '/guide/api-mcp/' | relative_url }}).

<div class="note">
<p><strong>Une instance, un comportement.</strong> Un administrateur peut désactiver
l'inscription, l'assistant IA, l'authentification unique ou l'envoi de courriels. Si un écran
décrit ici n'existe pas chez vous, c'est probablement que la fonction est éteinte côté serveur
— la page le signale généralement.</p>
</div>
