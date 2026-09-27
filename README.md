# ARCADIA — Café · Billard royal

Application de caisse (POS) monopage pour un café avec salle de billard (tables royales). Interface en français, montants en DH.

## Lancer
Ouvrir `index.html` dans un navigateur (Chrome/Edge conseillé). Aucun serveur ni installation : toutes les données sont enregistrées **localement** sur l'appareil (localStorage). Pensez à exporter une sauvegarde JSON régulièrement (Réglages).

- **PIN gérant par défaut : `1234`** — à changer dans Réglages.
- Réglages › « Générer un historique démo » crée 14 jours de ventes fictives pour tester les rapports.

## Onglets
| Onglet | Contenu |
|---|---|
| Tableau de bord | CA du jour (billard / café), non encaissé, tables en direct, alertes, meilleures ventes, derniers tickets |
| Billard | Chrono par table royale, pause/reprise, durée prévue, consommations, changement de table, réservation, encaissement |
| Commandes | Prise de commande : comptoir, tables salle, tables billard ; recherche, catégories, contrôle du stock |
| Tickets | Historique (shift / journée / tout), duplicata, annulation avec motif (gérant) |
| Stock | Niveaux, seuils, réception de marchandise, ajustement d'inventaire, mouvements |
| Caisse & shifts | Ouverture/clôture journée (rapport X/Z), shifts avec responsable, fond de caisse, dépenses, comptage et écart |
| Rapports 🔒 | CA par jour, heures d'affluence, catégories, tables (DH/h réel), employés, top produits, paiements, export CSV |
| Équipe | Employés et rôles, CA du jour par personne, journal d'activité |
| Réglages 🔒 | Tarifs et tranches de facturation billard, tables, alertes, PIN, sauvegarde/restauration |

## Règles métier
- Facturation billard : tranches de 5 min (réglable), minimum 15 min, arrondi au DH supérieur ; tarif par table (Royale 40 DH/h, VIP 60 DH/h par défaut).
- Vente impossible sans journée **et** shift ouverts, ni sans employé sélectionné sur l'appareil.
- Validation gérant requise pour : remise > 10 %, note offerte, annulation de ticket, retrait d'un article servi depuis plus de 2 min, sortie de caisse > 500 DH, annulation d'une partie commencée.
- Le mode gérant se reverrouille automatiquement après 10 min d'inactivité.
- Tickets thermiques 80 mm (police JetBrains Mono) via l'impression du navigateur.
