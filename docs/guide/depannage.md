---
layout: doc
title: Dépannage — courriels, liens expirés, erreurs courantes
description: >-
  Résoudre les problèmes les plus fréquents sur OpenLearn : courriel de confirmation absent,
  lien de réinitialisation inutilisable, message 429, mode en direct qui ne démarre pas,
  fonctions d'IA invisibles, téléversement refusé.
permalink: /guide/depannage/
---

<p class="doc-eyebrow">Guide · Courriel, liens, erreurs courantes</p>

# Dépannage

## Je ne reçois pas le courriel de confirmation

1. **Vérifiez le dossier indésirable** — c'est la cause la plus fréquente, surtout sur une
   instance dont le domaine n'a pas encore publié ses enregistrements SPF, DKIM et DMARC.
2. **Attendez cinq minutes** avant de redemander : un nouvel envoi n'est possible qu'après ce
   délai, et cliquer dix fois ne produit qu'un seul lien.
3. **Essayez une autre adresse** si votre fournisseur bloque le domaine d'expédition.
4. **L'administrateur** peut vérifier l'onglet **Messagerie** et envoyer un message de test. Un
   test qui n'arrive pas situe le problème côté serveur, pas côté utilisateur.

L'adresse non confirmée ne bloque rien : vous pouvez travailler normalement, seule la
notification de publication vous manquera.

## Mon lien de réinitialisation ne fonctionne pas

- Un lien **expire** (durée fixée par l'administrateur) et un lien **déjà utilisé** ne
  fonctionnent plus : demandez-en un nouveau depuis `/forgot`.
- Un seul lien est valide à la fois : demander un nouveau lien invalide les précédents. Si deux
  courriels sont arrivés, seul le plus récent fonctionne.

## « Trop de requêtes » (429)

Le plafond de débit protège les formulaires. Il s'applique par adresse réseau et par fenêtre :

- patientez jusqu'à la fin de la fenêtre (souvent une minute) ;
- si vous êtes derrière un proxy d'entreprise ou un VPN partagé, vous partagez peut-être l'adresse
  avec beaucoup de monde — d'où un 429 qui ne vous concerne pas personnellement ;
- un martèlement répété peut déclencher un **bannissement temporaire** de quelques minutes,
  indépendant du mot de passe.

Un mauvais mot de passe répété verrouille le **compte** pour un temps ; le message de
verrouillage n'apparaît qu'après un mot de passe correct, pour ne pas révéler l'existence du
compte.

## Le mode en direct ne démarre pas

- Le **PIN** est valable pour une session : s'il est refusé, la session est terminée ou annulée.
  Créez-en une nouvelle depuis la page du quiz.
- Les joueurs doivent être sur la **même instance** que l'hôte : un lien `/play/<code>` d'une
  instance ne fonctionne pas sur une autre.
- Un quiz en **tentative unique** refuse une deuxième participation au même compte, y compris en
  direct, et y compris pour l'hôte s'il a choisi de jouer.
- Si l'écran reste figé, rechargez : la session survit à un rechargement tant que l'hôte ne l'a
  pas fermée.

## Les fonctions d'IA n'apparaissent pas

C'est normal : sans fournisseur configuré, l'interface **masque** les boutons plutôt que de les
afficher en échec. Demandez à l'administrateur si un modèle est configuré ; l'onglet
**Fournisseur de modèle** le dit, avec un bouton de test.

## Le téléversement d'image est refusé

- Formats acceptés : images courantes (JPEG, PNG, WebP, GIF) dans une taille limitée.
- Un fichier volumineux est refusé par le serveur, pas par le navigateur : réduisez-le avant de
  le déposer.
- Les médias d'une instance vivent dans le volume de données : ils sont sauvegardés en même temps
  que la base, et restaurés avec elle.

## Ma page a disparu de l'historique

Elle n'a pas disparu : **Historique** liste les versions, et une restauration crée une nouvelle
version sans effacer les précédentes. Si la page entière n'apparaît plus, vérifiez que vous êtes
dans le bon espace wiki et que votre rôle donne accès aux brouillons.

## Rien ne s'affiche, la page reste blanche

- Videz le cache ou rechargez sans cache.
- Vérifiez la console du navigateur : une extension qui bloque les scripts casse l'interface.
- Sur une instance ancienne, un déploiement partiel laisse parfois des fichiers incohérents :
  signalez-le à l'exploitant, avec l'heure et la page.

## Signaler un problème

Pour un défaut du logiciel : une *issue* sur le dépôt, avec l'écran, le navigateur, ce que vous
attendiez et ce qui s'est produit. Pour un problème d'**accessibilité**, l'étiquette
`accessibility` est traitée comme un défaut bloquant. Pour tout le reste d'une instance
particulière — compte, contenu, courriel — voyez son administrateur : le projet ne gère pas les
données de chaque installation.
