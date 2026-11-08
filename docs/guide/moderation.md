---
layout: doc
title: Modérer et administrer — publications, comptes, réglages
description: >-
  Valider ou refuser une publication, notifier l'auteur, gérer les comptes et les rôles,
  configurer le courriel, l'IA et l'authentification unique, suivre les bannissements.
permalink: /guide/moderation/
---

<p class="doc-eyebrow">Guide · Publications, comptes, réglages</p>

# Modérer et administrer

Cette page couvre deux rôles distincts. Un **modérateur** voit la file des publications et les
signalements ; il n'accède ni à la configuration du courriel, ni à celle de l'IA, ni à l'ajout de
comptes administrateurs. Un **administrateur** a accès à tout.

## La file de publication

Un wiki ou un quiz demandé en publication arrive avec le statut **En attente de révision**. La
file se consulte depuis l'administration, onglet des publications.

Pour chaque élément, l'écran montre : le titre, l'auteur, le statut, la date de la demande, et un
aperçu du contenu. Deux actions :

- **Approuver** — l'élément devient **public** immédiatement.
- **Refuser** — l'élément repasse **privé**, avec une  note obligatoire en pratique : c'est elle
  qui explique la décision à l'auteur.

Une **note** accompagne chaque décision. Elle est transmise à l'auteur dans le courriel de
notification, et reste visible dans l'historique de l'élément.

<div class="note">
<p><strong>L'auteur est prévenu, une fois.</strong> À la validation, un courriel part
automatiquement vers l'adresse de l'auteur : titre, lien vers le contenu, note du modérateur. Si
le modérateur valide son propre contenu, aucun courriel n'est envoyé — personne n'a besoin d'être
prévenu de son propre geste. Un refus ne déclenche pas de courriel : le motif s'affiche dans
l'interface, et l'auteur le voit en revenant sur son contenu.</p>
</div>

### Ce qu'un modérateur doit regarder

- Le contenu est-il compréhensible sans son auteur à côté ?
- Les sources sont-elles citées, quand le sujet en demande ?
- Le titre correspond-il au contenu, ou promet-il autre chose ?
- Pour un quiz : les corrigés sont-ils justes ? Une erreur factuelle dans un corrigé est plus
  grave qu'une faute de frappe.

Le rôle consiste à dire **oui ou non avec une raison**, pas à réécrire le travail de quelqu'un.

## Gérer les comptes

L'administration liste les comptes avec leurs rôles :

| Rôle | Portée |
| --- | --- |
| **Auteur** | Écrit, demande la publication |
| **Modérateur** | Valide les publications, ne touche pas aux réglages sensibles |
| **Administrateur** | Tout : comptes, courriel, IA, SSO, mentions légales |

Les actions courantes : promouvoir ou rétrograder un compte, désactiver un compte (sans le
supprimer), réinitialiser un mot de passe d'urgence.

## Paramètres de l'instance

L'onglet **Paramètres** regroupe quatre blocs :

- **Instance** — nom affiché dans l'en-tête et dans les courriels, langue par défaut,
  inscription ouverte ou fermée.
- **Messagerie** — serveur SMTP, port, identifiants, adresse d'expédition, avec un bouton
  **Envoyer un message de test**. Un courriel de test qui n'arrive pas est le premier symptôme
  d'un réglage incomplet ; vérifiez ensuite SPF, DKIM et DMARC côté domaine.
- **Inscription et sécurité** — plafond de tentatives de connexion, durée de validité des liens
  de réinitialisation, intervalle minimal entre deux demandes.
- **Fournisseur de modèle** — URL compatible OpenAI, modèle, clé. Un bouton **Tester la
  connexion** indique le modèle et le temps de réponse. Sans fournisseur, les fonctions d'IA
  disparaissent de l'interface au lieu d'échouer à l'usage.

Les valeurs fixées par le déploiement (mode démo, base de données, TLS, serveur MCP) sont
affichées en lecture seule : elles viennent de l'environnement, pas de l'écran.

## Authentification unique

Onglet **Authentification unique** : ajouter un fournisseur OIDC (Keycloak, Authentik, Google
Workspace…) ou SAML. Champs nécessaires : URL de l'émetteur, identifiant client, secret,
domaines autorisés, et l'URL de retour à déclarer chez le fournisseur (affichée par l'écran).
L'état indique **Prêt**, **Incomplet** ou **Désactivé**.

L'option **Créer les comptes inconnus** décide si une personne authentifiée par le fournisseur
obtient un compte automatiquement. Désactivée, seuls les comptes déjà présents peuvent se
connecter par ce canal.

## Bannissements et abus

Un visiteur qui martèle un formulaire (connexion, inscription, mot de passe oublié) reçoit des
avertissements, puis un **bannissement temporaire** — en mémoire, avec expiration. L'écran
d'administration liste les adresses concernées, le motif et l'échéance, et permet de lever un
bannissement.

Les réseaux privés et les proxys de confiance sont exemptés : sans cela, un reverse proxy
ferait partager la même adresse à tous les visiteurs, et le premier spammeur bannirait tout le
monde.

## Journal des erreurs d'IA

Quand un appel au modèle échoue, l'erreur est enregistrée (onglet **Journal des erreurs IA**) avec
la date, le point d'entrée et le message. C'est le premier endroit à regarder quand « la
traduction ne marche plus » ou « le brouillon IA ne répond pas ».

## Mentions légales

Onglet **Mentions légales** : éditeur, hébergeur, contact, et textes affichés sur `/legal`. Une
instance publique doit les renseigner ; la démonstration les remplit à titre d'exemple.

## Bonnes pratiques

- Un administrateur ne modère pas son propre contenu : confiez la validation à un autre compte.
- Testez le courriel **après chaque changement** de configuration SMTP.
- Avant une mise à jour, faites une sauvegarde et vérifiez la restauration : voir
  [Auto-héberger]({{ '/auto-hebergement/' | relative_url }}).
