---
title: Auto-héberger OpenLearn — Docker, sauvegarde, restauration, mise à jour
description: >-
  Installer OpenLearn sur son serveur : image Docker, SQLite, variables d'environnement,
  sauvegarde cohérente, restauration testée, mise à jour sans perte de données.
permalink: /auto-hebergement/
---

# Auto-héberger OpenLearn

<p class="muted small">Cible : un serveur Linux, Docker, quinze minutes.</p>

## Ce qu'il faut

- Un serveur Linux (amd64 ou arm64), 1 Go de RAM, 2 Go d'espace disque.
- Docker et le plugin `docker compose`.
- Un nom de domaine si l'instance doit être publique (facultatif en réseau local).
- Un serveur SMTP si vous voulez les courriels de vérification et de réinitialisation.

## Démarrage

```bash
git clone https://github.com/codeyourweb/openlearn.git
cd openlearn
cp .env.example .env      # à relire : secret, SMTP, domaine
docker compose up -d --build
```

L'instance écoute sur le port défini par `OL_PORT` (8000 par défaut). La base SQLite et les
médias sont écrits dans le volume `openlearn-data` ; c'est le seul état à sauvegarder.

### Variables importantes

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `OL_ENVIRONMENT` | `production` active les cookies sécurisés et désactive les pages de débogage | `development` |
| `OL_SECRET_KEY` | Signature des sessions | généré au premier démarrage |
| `OL_DEMO_MODE` | Charge le catalogue de démonstration | `false` |
| `OL_AUTH_RATE_LIMIT` | Tentatives de connexion autorisées par fenêtre | `10` |
| `OL_MAIL_HOST`, `OL_MAIL_PORT`, `OL_MAIL_FROM` | Envoi des courriels | vide |
| `OL_AI_BASE_URL`, `OL_AI_MODEL` | Fournisseur compatible OpenAI pour l'assistant | vide |

Une variable non déclarée dans `docker-compose.yml` n'atteint jamais le conteneur : si un
réglage semble sans effet, vérifiez d'abord qu'il est transmis.

## Sauvegarde

La base SQLite s'écrit en continu ; la copier avec `cp` peut produire un fichier incohérent.
Le dépôt fournit un script qui utilise la commande `.backup` de SQLite, archive les médias, et
chiffre l'ensemble si on le lui demande :

```bash
OL_BACKUP_DIR=/var/backups/openlearn ./tools/backup.sh
```

Une sauvegarde quotidienne suffit pour la plupart des usages ; conservez-en plusieurs, sur un
support distinct de la machine.

## Restauration

```bash
docker compose stop app
./tools/restore.sh /var/backups/openlearn/openlearn-2026-11-08.tar.gz
docker compose start app
```

La restauration remplace le volume : elle est destructive par construction. Testez-la au moins
une fois sur une instance jetable avant d'en avoir besoin. Une sauvegarde jamais restaurée n'est
pas une sauvegarde, c'est une intention.

## Mise à jour

```bash
git pull
docker compose up -d --build
```

Les migrations sont **additives** : elles ajoutent des colonnes et des tables, elles n'en
suppriment pas. Un déploiement peut donc être annulé en redémarrant l'image précédente.

Le script `tools/deploy.sh` va plus loin, pour une instance qui compte :

1. il prend un instantané de la base et des médias avant de toucher au service ;
2. il construit la nouvelle image pendant que l'ancienne répond encore ;
3. il bascule, mesure la durée d'indisponibilité, et vérifie la santé ;
4. il compare les compteurs de contenus avant et après, et échoue si l'un a baissé ;
5. il conserve l'image précédente pour un `--rollback` immédiat.

## Derrière un proxy

Placez OpenLearn derrière nginx, Caddy ou Traefik et transmettez `X-Forwarded-For` : la
limitation de débit et le bannissement anti-spam s'appuient sur l'adresse réelle, pas sur celle
du proxy. Si le proxy est sur le même hôte, ajoutez son réseau à la liste d'exemption, sinon
tous les visiteurs partageront la même adresse.

## Courriel

Sans SMTP configuré, l'instance fonctionne : la vérification d'adresse est simplement
indisponible, et l'interface le signale. Pour une instance publique, configurez SPF, DKIM et
DMARC sur le domaine d'envoi — sans quoi vos messages de confirmation finiront en indésirable,
et vos utilisateurs croiront que l'inscription ne fonctionne pas.

## Ce que nous ne fournissons pas

Pas d'image « tout-en-un » avec reverse proxy, base externe et supervision : trop de choix
divergents pour un seul fichier Compose. La documentation décrit les briques ; l'assemblage
reste à votre main, et c'est précisément l'intérêt de l'auto-hébergement.
