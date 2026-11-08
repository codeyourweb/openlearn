---
title: Questions fréquentes sur OpenLearn
description: >-
  Licence, hébergement, coût, courriel, données personnelles, accessibilité, différences avec
  Moodle ou Kahoot, traduction, gouvernance du projet.
permalink: /faq/
---

# Questions fréquentes

<h2>Est-ce vraiment gratuit ?</h2>
<p>Oui, et sans contrepartie cachée : le logiciel est sous AGPL-3.0-only, il n'y a ni version
« pro », ni limite de comptes, ni fonctionnalité réservée. Héberger coûte ce que coûte un
serveur — quelques euros par mois pour une instance de classe.</p>

<h2>Quelle différence avec Moodle ?</h2>
<p>Moodle est une plate-forme de formation complète : cours, devoirs, notes, inscriptions,
calendrier. OpenLearn ne fait pas cela. Il fait trois choses : écrire un wiki, faire réciter par
des quiz, et planifier des révisions. Si vous cherchez un ENT, ce n'est pas le bon outil ; si
vous cherchez « un wiki et des quiz qui marchent, que je peux héberger », c'en est un.</p>

<h2>Et avec Kahoot ou Quizlet ?</h2>
<p>Le mode en direct ressemble à Kahoot, et les cartes à Quizlet. La différence tient en trois
points : vos contenus restent chez vous, il n'y a pas de traceur publicitaire, et le logiciel
est modifiable. La contrepartie : pas de bibliothèque de millions de quiz communautaires.</p>

<h2>Faut-il un serveur puissant ?</h2>
<p>Non. Un serveur à 1 Go de RAM suffit pour une centaine d'utilisateurs occasionnels ; SQLite
tient la charge. Au-delà, PostgreSQL est pris en charge. Le guide d'installation détaille les
variables et la sauvegarde.</p>

<h2>Mes données sont-elles exploitées ?</h2>
<p>Il n'y a ni régie publicitaire, ni script d'analyse tiers, ni revente de données. Le logiciel
écrit des journaux d'accès pour diagnostiquer une panne et bloquer un spammeur, pas pour
construire un profil. Sur votre propre instance, vous êtes seul maître des données ; sur la
démonstration publique, n'y déposez rien de confidentiel.</p>

<h2>Pourquoi l'adresse électronique doit-elle être confirmée ?</h2>
<p>Pour que les notifications de publication vous parviennent réellement. La confirmation n'est
pas bloquante : vous pouvez travailler sans, un bandeau le rappelle simplement. Elle sert aussi
à éviter qu'une adresse mal saisie serve à créer des comptes en série.</p>

<h2>Je ne reçois aucun courriel</h2>
<p>Trois causes ordinaires : le message est en indésirable (SPF/DKIM/DMARC absents sur le
domaine d'envoi), l'instance n'a pas de SMTP configuré, ou la demande a été faite deux fois en
moins de cinq minutes et n'a donc produit qu'un seul envoi. Voir la page
<a href="{{ '/guide/depannage/' | relative_url }}">Dépannage</a>.</p>

<h2>Combien de langues sont disponibles ?</h2>
<p>Douze : français, anglais, allemand, espagnol, italien, russe, chinois, japonais, portugais,
hindi, bengali et arabe. Toute l'interface est traduite, pas seulement la page d'accueil, et
l'arabe bascule en écriture de droite à gauche.</p>

<h2>Puis-je utiliser le nom « OpenLearn » pour mon instance ?</h2>
<p>Pour une instance privée, oui. Pour une instance publique, présentez-la comme « une instance
OpenLearn » plutôt que comme l'instance officielle : le nom et la démonstration ne sont pas
cédés par la licence. Voir <a href="{{ '/contribuer/' | relative_url }}">Contribuer</a>.</p>

<h2>Comment le projet est-il financé ?</h2>
<p>Il ne l'est pas. Le développement est porté par son auteur ; il n'y a ni fondation, ni
investisseur, ni feuille de route conditionnée par un client. C'est une fragilité assumée, et une
raison de plus pour que le code reste lisible et reprenable par d'autres.</p>

<h2>Que se passe-t-il si le projet s'arrête ?</h2>
<p>Les sources restent disponibles, la base est un fichier SQLite, les contenus s'exportent en
Markdown et en JSON. Une instance continue de fonctionner sans mise à jour. C'est exactement la
raison du choix de l'AGPL et de l'auto-hébergement : la disparition d'un mainteneur ne doit pas
être la disparition des données.</p>
