# immich-legacy-frame

**Transformez un vieil iPad en cadre photo pour votre album [Immich](https://immich.app), vidéos comprises.**

🇬🇧 [Read in English](README.md)

Les vieux iPad (iPad 2, iPad 3, iPad mini 1…) sont bloqués sur iOS 9, et leur Safari
n'arrive plus à faire tourner les applis web modernes. La plupart des cadres photo ne
marchent pas du tout dessus, ou se contentent des photos. Celui-ci a été écrit pour eux :

- 📷 **Photos et 🎬 vidéos** d'un album Immich, dans un ordre aléatoire
- 🐢 **Vidéos fluides sur du vieux matériel** : elles sont converties en arrière-plan dans
  un format 720p léger que la vieille puce décode sans peine (vos originaux dans Immich ne
  sont jamais modifiés)
- 🖼️ **Cadrage intelligent** : les photos dans le même sens que l'écran le remplissent ;
  les autres (une photo paysage sur un cadre vertical, par exemple) s'affichent en entier
  sur un fond flou
- 🗓️ **Encart avec la date** (et le lieu quand Immich le connaît), horloge en option
- 🔐 **Votre clé d'API reste sur votre serveur** : l'appareil ne parle qu'à ce petit relais
- 🪶 Un seul petit conteneur, sans autre dépendance que Python et ffmpeg

Testé avec un iPad 3 (iOS 9.3.5) et Immich v3.3.5. Devrait marcher sur tout appareil avec
Safari 9 ou plus récent, donc aussi sur les iPad, téléphones et navigateurs récents.

## Démarrage rapide

Il faut Docker avec Compose, sur une machine qui peut joindre votre serveur Immich.

1. **Récupérez le code**
   ```bash
   git clone https://github.com/Taralom-prog/immich-legacy-frame.git
   cd immich-legacy-frame
   cp .env.example .env
   ```
2. **Créez une clé d'API** dans Immich : *Paramètres du compte → Clés d'API → Nouvelle
   clé*. Utilisez une clé dédiée au cadre, de préférence restreinte et en lecture seule :
   elle doit pouvoir lire les albums et les médias, faire des recherches, voir les
   miniatures et télécharger les originaux (pour convertir les vidéos). Au démarrage, les
   journaux indiquent si la clé et l'album fonctionnent.
3. **Trouvez l'identifiant de l'album** : ouvrez l'album dans Immich, c'est la dernière
   partie de l'adresse : `https://immich.exemple/albums/`**`1b2c3d4e-0000-4000-8000-…`**
4. **Remplissez `.env`** : `IMMICH_URL`, `IMMICH_API_KEY`, `ALBUM_ID`, et `LANGUAGE=fr`.
   Le reste a des valeurs par défaut raisonnables.
5. **Lancez-le**
   ```bash
   docker compose up -d
   docker compose logs -f     # pour suivre la conversion des vidéos
   ```
6. Sur le vieil appareil, ouvrez **`http://<ip-de-la-machine-docker>:5050`** dans Safari
   et **touchez l'écran une fois**.

## Préparer le vieil appareil

- **Touchez l'écran une fois après chaque (re)chargement.** iOS 9 refuse de lancer une
  vidéo qui n'a pas été démarrée par un toucher. Le premier toucher autorise les vidéos
  tant que la page reste ouverte. Les touchers suivants passent à l'élément suivant.
- **Pas de mise en veille** : *Réglages → Général → Verrouillage auto → Jamais*, et
  laissez-le branché.
- **Plein écran** : dans Safari, *Partager → Sur l'écran d'accueil*, puis ouvrez le cadre
  depuis cette icône.
- **Mode kiosque** : *Réglages → Général → Accessibilité → Accès guidé*, puis triple-clic
  sur le bouton principal quand le cadre est affiché.

## Réglages

Tous les réglages sont dans `.env` (voir les commentaires de `.env.example`, et le tableau
détaillé du [README anglais](README.md#configuration)). Appliquez les changements avec
`docker compose up -d`.

## Place disque et processeur

- **Disque** : environ 9 Mo par vidéo en moyenne dans `./cache`, jusqu'à ~25 Mo pour une
  vidéo coupée à 60 s (par exemple 1 300 vidéos ≈ 11 Go). Pendant la conversion,
  l'original est téléchargé dans `./cache/tmp` : gardez aussi de la place pour votre plus
  grosse vidéo. Les vidéos retirées de l'album sont supprimées du cache à la vérification
  suivante. Changer un réglage de conversion reconvertit toutes les vidéos,
  automatiquement.
- **Processeur** : la première conversion d'un gros album prend du temps (environ
  10 s par vidéo sur 2 cœurs d'un petit serveur). Ensuite, seules les nouvelles vidéos
  sont converties.

## En cas de problème

`docker compose logs -f` affiche les messages du serveur et ceux du cadre (lignes qui
commencent par `frame>`). Le tableau de dépannage complet est dans le
[README anglais](README.md#troubleshooting).

## Sécurité

- Toute personne qui peut joindre le port 5050 voit les photos et vidéos de l'album, sans
  se connecter. Gardez-le sur votre réseau local, ne l'exposez pas sur Internet.
- Seul l'album est accessible : le cadre refuse tout autre média, même si la clé d'API
  pourrait le voir.
- La clé d'API n'est utilisée que par le serveur, elle n'est jamais envoyée à l'appareil.
- Le conteneur abandonne les droits root au démarrage (`PUID`/`PGID`).
- L'encart peut afficher le lieu des photos sur un écran posé dans une pièce commune :
  mettez `SHOW_PLACE=false` si vous préférez éviter.

## Licence

[MIT](LICENSE). Ce projet n'est pas affilié à Immich.
