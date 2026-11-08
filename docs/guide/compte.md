---
layout: doc
title: Le compte — profil, mot de passe, adresse, clés d'API
description: >-
  Gérer son compte OpenLearn : nom affiché, avatar, mot de passe, adresse électronique et
  vérification, clés d'API, invitations à une évaluation, suppression du compte.
permalink: /guide/compte/
---

<p class="doc-eyebrow">Guide · Profil, mot de passe, clés d'API</p>

# Le compte

Tout se passe sur `/account`, en onglets.

## Profil

- **Nom affiché** : ce que voient les autres, à côté de vos contributions.
- **Avatar** : une image carrée, redimensionnée automatiquement. Un avatar explicite n'est pas
  obligatoire ; les initiales servent de repli.
- **Langue** et **thème** : mémorisés sur votre compte, ils suivent d'un appareil à l'autre.

## Adresse électronique et vérification

L'adresse sert à la connexion et aux notifications. Elle n'est **jamais** affichée publiquement.

Le bloc **Adresse électronique** indique si elle est **confirmée** ou non, avec un bouton
**Renvoyer le lien** quand ce n'est pas le cas. Après un changement d'adresse, la confirmation
redevient nécessaire : une adresse non vérifiée ne reçoit pas les notifications de publication.

Un nouvel envoi est limité à un par tranche de cinq minutes, et le bouton le dit clairement.

## Mot de passe

**Changer le mot de passe** demande l'ancien, puis le nouveau deux fois. Les autres sessions
ouvertes restent valides ; pour les couper toutes, utilisez **Déconnecter les autres sessions**
quand elle est proposée, ou changez le mot de passe depuis un appareil de confiance.

En cas d'oubli, `/forgot` envoie un lien. Un seul courriel part par tranche de cinq minutes par
adresse : si vous cliquez dix fois, un seul lien arrivera, et c'est celui-là qui fonctionne.

## Clés d'API

Une clé d'API permet à un script ou à un agent de travailler avec **vos** droits.

1. **Créer une clé** : donnez-lui un nom (« import de fiches », « agent de veille »).
2. La valeur n'est affichée **qu'une fois** — copiez-la immédiatement.
3. **Révoquer** une clé la désactive sans supprimer ce qu'elle a créé.

Une clé se comporte comme votre compte : ne la mettez pas dans un dépôt public, et préférez une
clé par usage, pour pouvoir en révoquer une seule.

## Invitations et partages

- **Évaluation partagée** : depuis un quiz, un lien `/e/<jeton>` ouvre directement la tentative
  d'évaluation, sans passer par le catalogue. Utile pour un examen à distance.
- **Invitation à un wiki** : le propriétaire d'un espace invite par adresse électronique, avec un
  rôle — *contributeur* (il propose des modifications) ou *administrateur* (il écrit directement
  et gère les membres). Le lien `/join/<jeton>` rejoint l'espace.

## Supprimer son compte

**Supprimer le compte** efface le profil et les données personnelles. Les contenus publiés
(wikis, quiz) restent en place, attribués à un compte anonymisé : les effacer casserait le
travail des autres contributeurs. Cette action est définitive et demande votre mot de passe.
