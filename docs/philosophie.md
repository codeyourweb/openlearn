---
title: La philosophie d'OpenLearn — logiciel libre, savoirs communs, sobriété
description: >-
  Pourquoi OpenLearn est sous AGPL, sans traceur, accessible WCAG 2.2 AA, sans mesure
  d'audience intrusive et conçu pour durer dix ans sur un serveur modeste.
permalink: /philosophie/
---

<p class="muted small">Philosophie · lecture d'environ sept minutes</p>

# La philosophie d'OpenLearn

Un logiciel dit toujours quelque chose de ceux qui l'ont écrit. Celui-ci part de quatre
convictions, et chaque décision technique qui suit en découle. Elles ne sont pas des slogans
jetés en tête de dépôt : ce sont des contraintes qui ont coûté du temps, parfois des
fonctionnalités, et qui expliquent l'aspect actuel du code.

## 1. Le savoir ne se met pas sous clé

Une plateforme d'apprentissage moderne ressemble souvent à un guichet : on paie, on entre,
on consomme, on ressort. Les contenus produits par les enseignants restent dans la base du
fournisseur ; les progrès de l'élève aussi ; et le jour où l'établissement change d'avis, il
n'emporte rien.

OpenLearn prend le contre-pied : les contenus sont écrits en Markdown, stockés dans une base
SQLite qu'on peut copier d'un seul fichier, exportés à la demande et lisibles par n'importe
quel outil. Un wiki n'est pas un produit qu'on loue, c'est une mémoire qu'on tient.

> Rien de ce que vous écrivez ici ne dépend de notre serveur. C'est exactement pour cela que
> nous vous encourageons à héberger le vôtre.

C'est ce qui justifie **AGPL-3.0-only** plutôt qu'une licence permissive : si quelqu'un propose
OpenLearn comme service, il doit rendre le code de sa version — et donc ses corrections — à
la communauté. Une licence permissive aurait permis qu'une société reprenne le travail, y
ajoute un traceur, et ferme la porte derrière elle.

## 2. La sobriété n'est pas une contrainte, c'est un choix

Le logiciel tient dans un conteneur, parle à une base SQLite par défaut, sert des pages dont le
JavaScript est chargé en modules natifs, sans étape de compilation ni framework de plusieurs
mégaoctets. Un Raspberry Pi 4 suffit à faire tourner une instance pour une classe. Une instance
municipale tient sur le plus petit serveur d'un hébergeur associatif.

Cette sobriété a un coût : pas de rendu côté serveur « universel », pas de recherche full-text
exotique par défaut, pas de file d'attente distribuée. Nous les ajouterons le jour où un cas
d'usage réel les exigera — pas parce que c'est la mode dans les tutoriels.

La sobriété s'entend aussi dans le temps : une installation ne doit pas exiger une migration
douloureuse tous les six mois. Les migrations sont additives, testées, et un déploiement
refuse de démarrer si le compte de contenus a baissé. Un projet qui peut mourir proprement
est un projet qu'on ose confier à des données réelles.

## 3. L'accessibilité n'est pas un module, c'est le plancher

OpenLearn visait **WCAG 2.2 AA** dès la première ligne d'interface, pas après un audit. Cela
signifie : navigation complète au clavier, contrastes vérifiés en thème clair comme en thème
sombre, libellés de formulaires explicites, annonces vocales sur les changements d'état,
respect de `prefers-reduced-motion`, cibles tactiles suffisamment grandes, et un lien
d'évitement en tête de chaque page.

Le test est automatique dans l'intégration continue (axe-core sur les écrans principaux, plus
des vérifications statiques de balisage), et il échoue la construction. Un écran qui régresse
n'est pas publié.

L'accessibilité rejoint ici la sobriété : une interface qui fonctionne sans JavaScript
sophistiqué, sans animation, et sans dépendre d'une souris est aussi une interface qui
fonctionne sur un vieux portable, en 3G, et avec un lecteur d'écran.

## 4. Ne pas mesurer les gens

Il n'y a pas de régie publicitaire, pas de pixel de réseau social, pas de script d'analyse
tiers. Les journaux d'accès du serveur servent à diagnostiquer une panne et à bannir un
spammeur, pas à construire un profil. Une instance peut activer une mesure agrégée locale
(nombre de pages vues, sans identifiant persistant) si son administrateur le souhaite ; la
démonstration publique n'en fait rien qui permette de vous suivre.

Ce refus a un prix : nous ne saurons jamais précisément combien de personnes utilisent
OpenLearn. Nous préférons l'ignorer que de l'apprendre en espionnant nos visiteurs.

## Ce que cela change dans le produit

| Décision | Raison |
| --- | --- |
| Compte facultatif pour lire un wiki public | Le savoir public ne doit pas exiger une inscription. |
| Vérification de l'adresse par lien, non bloquante | On ne refuse pas un accès parce qu'un serveur SMTP a du retard. |
| Un seul courriel de réinitialisation toutes les cinq minutes | Un formulaire public ne doit pas servir à harceler quelqu'un. |
| Bannissement temporaire des formulaires spammés | Protéger l'instance sans construire un système de réputation. |
| Courriel à l'auteur quand sa publication est validée | Le travail mérite une réponse, même automatique. |
| Modération humaine des publications publiques | Un filtre automatique juge mal ; un modérateur juge, et signe. |
| Aucune note privée d'élève conservée sans nécessité | Une donnée qu'on ne garde pas ne peut pas fuir. |
| Double licence et conditions de marque | Le code reste libre ; le nom et la démonstration restent identifiables. |

## Comment nous travaillons

Les contributions passent par des *pull requests* relues, un CLA signé et une intégration
continue qui exige : lint sans erreur, tests unitaires verts, tests de bout en bout au
navigateur, et contrôle d'accessibilité. L'historique Git est signé. Les décisions
structurantes sont écrites dans le dépôt plutôt que dans un fil de discussion privé, pour que
la personne qui reprendra le projet dans cinq ans comprenne le pourquoi, pas seulement le quoi.

Nous refusons trois choses, par principe : ajouter une dépendance qui collecte des données,
introduire un composant d'interface inaccessible « en attendant », et fusionner une
fonctionnalité dont nous ne savons pas expliquer le besoin en une phrase.

## Et si vous n'êtes pas d'accord

C'est le propre d'un logiciel libre : la philosophie n'engage que ceux qui la partagent. Le
code est là, la licence vous autorise à le modifier, à le redistribuer, à en faire une version
différente — à condition de rendre vos modifications. Si vous pensez qu'une de ces quatre
convictions est une erreur, ouvrez une discussion : nous avons déjà changé d'avis sur des
points techniques, et nous préférons un désaccord argumenté à un silence poli.

<p class="muted small">
Cette page décrit le projet, pas une personne morale. Elle n'a pas de valeur contractuelle ;
la licence AGPL-3.0-only, elle, en a.
</p>
