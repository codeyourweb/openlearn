---
layout: doc
title: Démarrer — créer son compte, se connecter, s'orienter
description: >-
  Créer un compte OpenLearn, confirmer son adresse, se connecter, retrouver ses contenus sur
  le tableau de bord, changer de langue et de thème.
permalink: /guide/demarrage/
---

<p class="doc-eyebrow">Guide · Compte, connexion, navigation</p>

# Démarrer

## Créer un compte

1. Ouvrez `/register` (bouton **Créer un compte** en haut de page).
2. Renseignez un nom affiché, une adresse électronique et un mot de passe.
3. Validez : votre compte existe immédiatement, vous êtes connecté, et un courriel de
   confirmation part vers l'adresse indiquée.

Le nom affiché apparaît à côté de vos contributions. L'adresse, elle, n'est jamais publiée :
elle sert à la connexion et aux notifications.

<div class="note">
<p><strong>Exigences du mot de passe.</strong> Douze caractères au minimum, et l'interface
refuse les mots de passe les plus courants. Un gestionnaire de mots de passe fait très bien
l'affaire ; rien ne vous oblige à en inventer un mémorisable.</p>
</div>

## Confirmer son adresse

Le courriel reçu contient un lien vers `/verify/<jeton>`. Ouvrez-le : la page confirme l'adresse
et vous ramène à votre tableau de bord.

Si le lien a expiré, ou si le courriel n'est jamais arrivé :

- un bandeau en haut de chaque page rappelle que l'adresse n'est pas confirmée, avec un bouton
  **Renvoyer le lien** ;
- la même action existe dans **Compte** → *Adresse électronique* ;
- un nouvel envoi n'est possible qu'après un délai (cinq minutes par défaut). Le bouton répond
  alors qu'un lien a été envoyé récemment : c'est voulu, pour éviter qu'un formulaire public
  serve à inonder la boîte de quelqu'un.

Rien n'est bloqué tant que l'adresse n'est pas confirmée : vous pouvez écrire, créer des quiz et
réviser. Seules les notifications par courriel dépendent de cette confirmation.

## Se connecter, se déconnecter

- `/login` pour la connexion classique.
- Si l'instance propose l'authentification unique, un bouton par fournisseur apparaît sous le
  formulaire (par exemple « Se connecter avec Keycloak »).
- **Mot de passe oublié** : `/forgot`. Saisissez votre adresse ; si un compte existe, un lien
  arrive. Le message affiché est volontairement identique dans les deux cas, pour ne pas
  révéler quelles adresses sont inscrites.
- Déconnexion : menu de compte, en haut à droite.

Un mauvais mot de passe répété verrouille temporairement le compte. Le message de verrouillage
n'apparaît qu'après un mot de passe correct : c'est une protection contre l'énumération des
comptes, pas une brimade.

## S'orienter

| Page | Chemin | À quoi elle sert |
| --- | --- | --- |
| Tableau de bord | `/dashboard` | Vos contenus, vos brouillons, vos cartes, les actions de création |
| Wikis | `/wiki` | Les espaces publics, et le vôtre |
| Quiz | `/quizzes` | Le catalogue des quiz publics |
| Cartes | `/cards` | Vos paquets de révision |
| Compte | `/account` | Profil, mot de passe, adresse, clés d'API |
| Administration | `/admin` | Réservé aux administrateurs et modérateurs |

## Langue, thème, accessibilité

- Le sélecteur de langue, en pied de page, propose douze langues. Le choix est mémorisé par le
  navigateur ; l'arabe bascule toute l'interface en écriture de droite à gauche.
- Le thème suit par défaut le réglage du système (clair ou sombre) et peut être forcé.
- Toute l'interface se pilote au clavier. La touche <kbd>Tab</kbd> avance, <kbd>Maj</kbd> +
  <kbd>Tab</kbd> recule, <kbd>Entrée</kbd> active, et le premier <kbd>Tab</kbd> propose
  « Aller au contenu » pour sauter la navigation.

## Ce que voit un visiteur non connecté

Les wikis et quiz publics se lisent sans compte, y compris les pages de wiki publiées. Un
visiteur ne peut ni écrire, ni jouer à un quiz réservé aux inscrits, ni voir un brouillon.
