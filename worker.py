# /home/AlienScraper/worker.py

import os
import redis
from rq import Worker, Queue # On n'importe plus Connection

# --- Configuration ---
# Nom de la file d'attente que ce worker va écouter
listen = ['scraping-tasks']

# Configuration de la connexion Redis (utilise les valeurs par défaut : localhost:6379)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    print(f"--- Démarrage du Worker RQ ---")
    print(f"Connexion à Redis : {redis_url}")
    print(f"Écoute sur les files d'attente : {', '.join(listen)}")

    try:
        # Vérifier la connexion à Redis avant de démarrer
        conn.ping()
        print("Connexion à Redis réussie.")

        # On crée les objets Queue en leur passant la connexion
        queues = [Queue(name, connection=conn) for name in listen]
        # On crée le Worker avec la liste des queues et la connexion
        worker = Worker(queues, connection=conn)

        # Lance le worker (bloquant)
        worker.work(with_scheduler=True) # with_scheduler=True est utile pour des tâches planifiées plus tard

    except redis.exceptions.ConnectionError as e:
        print(f"\nERREUR : Impossible de se connecter à Redis à l'adresse {redis_url}")
        print(f"Vérifiez que le serveur Redis est lancé et accessible.")
        print(f"Détails de l'erreur : {e}")
    except Exception as e:
        print(f"\nUne erreur inattendue est survenue dans le worker : {e}")

    print("--- Worker RQ arrêté ---")
