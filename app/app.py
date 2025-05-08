# /home/AlienScraper/app/app.py

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, send_from_directory, abort, session # Importer les modules nécessaires
import redis
from rq import Queue
from rq.job import Job
from rq.registry import StartedJobRegistry, FinishedJobRegistry, FailedJobRegistry
import os
import shutil # Pour la suppression de dossiers
import sys
from pathlib import Path # Importer Path explicitement ici aussi
import subprocess # Pour exécuter des commandes shell
from werkzeug.utils import secure_filename # Pour sécuriser les noms de fichiers (même si on vérifie explicitement)

# --- Setup sys.path ---
# Utilise le chemin absolu du dossier parent de ce fichier app.py
app_dir = os.path.dirname(os.path.abspath(__file__))
# Get the absolute path of the parent directory (/home/AlienScraper)
parent_dir = os.path.dirname(app_dir)
# Add the parent directory to sys.path if it's not already there
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir) # Insert at the beginning for priority

print(f"DEBUG: sys.path includes: {parent_dir}") # Add debug print

# --- Import project modules ---
try:
    # Now that parent_dir is in sys.path, we should be able to import directly
    import config
    from main_scraper import run_full_scraping_process
    print("Imports depuis le dossier parent (config, main_scraper) réussis.")
except ImportError as e:
    print(f"ERREUR CRITIQUE lors de l'import depuis le dossier parent : {e}")
    print(f"Vérifiez que les fichiers config.py et main_scraper.py existent dans {parent_dir}.")
    # On pourrait choisir d'arrêter l'application ici si les imports sont critiques
    sys.exit(f"Arrêt dû à une erreur d'import: {e}")
    # Set defaults just in case, although sys.exit should prevent reaching here
    run_full_scraping_process = None # Définir à None pour éviter les erreurs plus tard si l'import échoue
    q = None


# --- Configuration RQ ---
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
try:
    conn = redis.from_url(redis_url)
    conn.ping() # Vérifier la connexion à Redis
    print(f"Connecté à Redis : {redis_url}")
    q = Queue('scraping-tasks', connection=conn) # Utilise la même file que le worker
except redis.exceptions.ConnectionError as e:
    print(f"ERREUR : Impossible de se connecter à Redis à l'adresse {redis_url}")
    print(f"Vérifiez que le serveur Redis est lancé et accessible.")
    print(f"Détails de l'erreur : {e}")
    q = None # Mettre la queue à None si la connexion échoue
except NameError:
    # This might happen if 'conn' wasn't defined due to earlier import errors
    print("ERREUR: La connexion Redis n'a pas pu être initialisée (probablement à cause d'erreurs d'import précédentes).")
    q = None # Mettre la queue à None si la connexion échoue

# Crée une instance de l'application Flask
app = Flask(__name__)

# Clé secrète pour les messages flash (change-la pour quelque chose de plus sécurisé en production)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'une_cle_secrete_par_defaut_tres_difficile_a_deviner')

# --- Constantes pour la gestion des fichiers ---
RESULTS_DIR_PARENT = config.RAW_RESULTS_PARENT_DIR
LISTS_DIR = config.LISTES_OUTPUT_DIR
LEADS_FILE = config.LEADS_CSV_FINAL_PATH
FB_COOKIES = config.BASE_DIR / "facebook_cookies.json"
IG_COOKIES = config.BASE_DIR / "instagram_cookies.json"
ALLOWED_COOKIE_FILENAMES = {'facebook_cookies.json', 'instagram_cookies.json'}
# Définir SCREENSHOTS_DIR_APP pour l'application Flask
if hasattr(config, 'BASE_DIR'):
    SCREENSHOTS_DIR_APP = config.BASE_DIR / "screenshots"
else: # Fallback si config.BASE_DIR n'est pas défini
    # parent_dir est la racine du projet AlienScraper (/home/test/AlienScraper-Client)
    SCREENSHOTS_DIR_APP = Path(parent_dir) / "screenshots"
    print(f"AVERTISSEMENT: config.BASE_DIR non trouvé, SCREENSHOTS_DIR_APP défini à {SCREENSHOTS_DIR_APP}")

# S'assurer que le dossier existe pour l'application
SCREENSHOTS_DIR_APP.mkdir(parents=True, exist_ok=True)

# Définit une route simple pour la page d'accueil
@app.route('/')
def home():
    # Vérifier le statut Redis
    redis_status = "Indéterminé"
    try:
        if conn and conn.ping():
            redis_status = "Connecté"
        else:
            redis_status = "Déconnecté / Non initialisé"
    except Exception:
        redis_status = "Erreur connexion"

    # Vérifier la présence des cookies
    fb_cookie_exists = FB_COOKIES.exists()
    ig_cookie_exists = IG_COOKIES.exists()

    # Lister les fichiers/dossiers de résultats
    result_files = {
        "leads": LEADS_FILE if LEADS_FILE.exists() else None,
        "lists": sorted([f for f in LISTS_DIR.glob('*.csv')]) if LISTS_DIR.exists() else [],
        "results_dirs": sorted([d for d in RESULTS_DIR_PARENT.glob('Scraping_Results_*') if d.is_dir()], reverse=True) if RESULTS_DIR_PARENT.exists() else []
    }

    # Récupérer les tâches récentes (exemple simple)
    recent_jobs_info = []
    if q:
        try:
            registry = FinishedJobRegistry(queue=q)
            finished_ids = registry.get_job_ids(0, 4) # 5 derniers terminés
            for job_id in finished_ids:
                 job = Job.fetch(job_id, connection=conn)
                 # Vérifier si job n'est pas None (peut arriver si le job a expiré)
                 if job:
                     recent_jobs_info.append({"id": job.id, "status": job.get_status(), "finished_at": job.ended_at})
            # On pourrait ajouter Started et Failed de la même manière
        except Exception as e_rq_fetch:
            print(f"Erreur lors de la récupération des tâches RQ: {e_rq_fetch}")

    last_job_id = session.get('last_job_id')
    # Afficher le formulaire HTML
    return render_template('index.html',
                           redis_status=redis_status,
                           app_version=config.APP_VERSION,
                           fb_cookie_exists=fb_cookie_exists,
                           ig_cookie_exists=ig_cookie_exists,
                           result_files=result_files,
                           recent_jobs=recent_jobs_info,
                           last_job_id=last_job_id)

# Nouvelle route pour démarrer un scraping (pour l'instant avec des données en dur) - Gardée pour test rapide si besoin
@app.route('/start-scrape')
def start_scrape():
    # Vérifier si la connexion Redis et la fonction de scraping sont disponibles
    if not q:
        return jsonify({"error": "Connexion à Redis échouée ou non initialisée. Impossible de mettre la tâche en file d'attente."}), 500
    if not run_full_scraping_process:
         # This check might be redundant if sys.exit was called earlier, but good for safety
         return jsonify({"error": "La fonction de scraping n'a pas pu être importée. Vérifiez les logs serveur."}), 500

    # Pour l'exemple, on utilise des mots-clés fixes
    example_keywords = [["restaurant"], ["Rabat"], ["bio"]]
    example_limit = 2 # Limite de 2 pages pour le test
    # Définir les types de liens à rechercher (si les modules sont dispo)
    # Pour ce test, on suppose qu'on veut chercher FB et Insta
    example_link_types = ['facebook', 'instagram']

    try:
        # Mettre la tâche dans la file d'attente RQ
        # On appelle la fonction run_full_scraping_process importée de main_scraper.py
        job = q.enqueue(run_full_scraping_process,
                        # Ajouter example_link_types aux arguments positionnels
                        args=(example_keywords, example_limit, example_link_types),
                        kwargs={'run_clean_option': True, 'run_extract_option': True}, # Passer les arguments optionnels
                        job_timeout='2h', # Mettre un timeout pour la tâche (ex: 2 heures)
                        result_ttl=86400, # Garder le résultat pendant 1 jour (86400 secondes)
                        job_id=f"scrape_job_{example_keywords[0][0]}_{example_keywords[1][0]}" # Optional: give a predictable ID
                        )

        print(f"Tâche de scraping mise en file d'attente avec l'ID : {job.id}")
        # Retourner l'ID pour le suivi de la progression
        return jsonify({"message": "Tâche de scraping lancée !", "job_id": job.id})
    except Exception as e:
        print(f"Erreur lors de la mise en file d'attente de la tâche : {e}")
        # Log the full traceback for debugging
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur lors de la mise en file d'attente : {e}"}), 500

# Nouvelle route pour gérer la soumission du formulaire
@app.route('/scrape', methods=['GET', 'POST'])
def scrape_keywords():
    if request.method == 'POST':
        # Vérifier si la connexion Redis et la fonction de scraping sont disponibles
        if not q:
            flash("Erreur: Connexion à Redis échouée. Impossible de lancer la tâche.", "error")
            return redirect(url_for('home'))
        if not run_full_scraping_process:
            flash("Erreur: Fonction de scraping non disponible.", "error")
            return redirect(url_for('home'))

        # Récupérer les données du formulaire
        kw1_input = request.form.get('kw1', '')
        kw2_input = request.form.get('kw2', '')
        kw3_input = request.form.get('kw3', '')
        limit_input = request.form.get('limit', '2')
        run_clean = request.form.get('clean') == 'yes'
        run_extract = request.form.get('extract') == 'yes'

        # Convertir les entrées en listes de mots-clés
        keywords_lists = [
            [kw.strip() for kw in kw1_input.split(',') if kw.strip()],
            [kw.strip() for kw in kw2_input.split(',') if kw.strip()],
            [kw.strip() for kw in kw3_input.split(',') if kw.strip()]
        ]
        # S'assurer qu'il y a au moins une liste vide si l'entrée était vide
        keywords_lists = [lst if lst else [] for lst in keywords_lists]

        # Valider la limite de pages
        try:
            google_pages_limit = int(limit_input)
            if google_pages_limit < 1: google_pages_limit = 1 # Minimum 1 page
        except ValueError:
            google_pages_limit = 2 # Valeur par défaut si invalide

        # Déterminer les types de liens (comme dans main_scraper)
        google_allowed_link_types = ['facebook', 'instagram'] # Ajuste si nécessaire

        try:
            # Enqueuer la tâche avec les données du formulaire
            job_id_suffix = f"{keywords_lists[0][0]}_{keywords_lists[1][0]}" if keywords_lists[0] and keywords_lists[1] else "custom"
            job = q.enqueue(run_full_scraping_process,
                            args=(keywords_lists, google_pages_limit, google_allowed_link_types),
                            kwargs={'run_clean_option': run_clean, 'run_extract_option': run_extract},
                            job_timeout='2h', result_ttl=86400,
                            job_id=f"scrape_job_{job_id_suffix}_{os.urandom(4).hex()}" # ID unique
                            )
            flash(f"Tâche de scraping lancée avec succès ! ID: {job.id}", "success")
            session['last_job_id'] = job.id # Stocker l'ID de la tâche dans la session
        except Exception as e:
            flash(f"Erreur lors du lancement de la tâche : {e}", "error")

        return redirect(url_for('home')) # Rediriger vers la page d'accueil après soumission

    # Si méthode GET, afficher simplement le formulaire (redirection vers home)
    return redirect(url_for('home'))

# --- Routes pour la gestion des screenshots ---
@app.route('/screenshots')
def list_screenshots():
    if not SCREENSHOTS_DIR_APP.exists():
        flash("Le dossier des captures d'écran n'a pas pu être trouvé ou créé.", "warning")
        return render_template('screenshots.html', files=[])

    try:
        all_files = list(SCREENSHOTS_DIR_APP.glob('*.png')) + list(SCREENSHOTS_DIR_APP.glob('*.html'))
        sorted_files = sorted(all_files, key=lambda f: f.stat().st_mtime, reverse=True)
        
        files_info = []
        for f_path in sorted_files:
            files_info.append({
                'name': f_path.name,
                'size': f_path.stat().st_size,
                'modified': datetime.fromtimestamp(f_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
        return render_template('screenshots.html', files=files_info)
    except Exception as e:
        flash(f"Erreur lors du listage des fichiers de débogage : {e}", "error")
        return render_template('screenshots.html', files=[])

@app.route('/screenshots/<path:filename>')
def download_screenshot(filename):
    # Sécurité: s'assurer que le fichier est bien dans SCREENSHOTS_DIR_APP
    # et qu'il n'y a pas de tentative de path traversal.
    safe_dir = SCREENSHOTS_DIR_APP.resolve()
    file_path = (safe_dir / filename).resolve()
    
    if not file_path.is_file() or safe_dir not in file_path.parents:
        abort(404, "Fichier non trouvé ou accès non autorisé.")
    return send_from_directory(safe_dir, filename, as_attachment=True)

@app.route('/delete_screenshot/<path:filename>', methods=['POST'])
def delete_screenshot(filename):
    safe_dir = SCREENSHOTS_DIR_APP.resolve()
    file_path = (safe_dir / filename).resolve()

    if not file_path.is_file() or safe_dir not in file_path.parents:
        flash("Fichier non trouvé ou non autorisé.", "error")
    else:
        try:
            file_path.unlink()
            flash(f"Fichier {filename} supprimé.", "success")
        except Exception as e:
            flash(f"Erreur lors de la suppression de {filename}: {e}", "error")
    return redirect(url_for('list_screenshots'))

@app.route('/delete_all_screenshots', methods=['POST'])
def delete_all_screenshots():
    deleted_count = 0
    error_count = 0
    if not SCREENSHOTS_DIR_APP.exists():
        flash("Dossier des screenshots non trouvé.", "error")
        return redirect(url_for('list_screenshots'))
        
    for item in SCREENSHOTS_DIR_APP.glob('*'):
        if item.is_file() and (item.name.endswith('.png') or item.name.endswith('.html')):
            try:
                item.unlink()
                deleted_count += 1
            except Exception:
                error_count +=1
    
    if error_count > 0:
        flash(f"{deleted_count} fichier(s) supprimé(s). {error_count} erreur(s) rencontrée(s).", "warning")
    elif deleted_count > 0:
        flash(f"Tous les {deleted_count} fichiers de débogage ont été supprimés.", "success")
    else:
        flash("Aucun fichier de débogage à supprimer.", "info")
    return redirect(url_for('list_screenshots'))


# --- Fin Routes Screenshots ---

# Route pour obtenir le statut d'une tâche RQ
@app.route('/job-status/<job_id>')
def job_status(job_id):
    if not q:
        return jsonify({"error": "Redis non connecté"}), 500
    try:
        job = Job.fetch(job_id, connection=conn)
        if job:
            status = job.get_status()
            meta = job.meta or {}
            progress = meta.get('progress', 0)
            status_message = meta.get('status_message', status) # Utilise le message meta ou le statut RQ
            return jsonify({
                "id": job.id,
                "status": status,
                "progress": progress,
                "status_message": status_message,
                "result": job.result if status == 'finished' else None,
                "error": job.exc_info if status == 'failed' else None
            })
        elif session.get('last_job_id') == job_id: # Si la tâche n'est plus dans RQ mais était la dernière
            session.pop('last_job_id', None) # Nettoyer la session
            return jsonify({"status": "expired_or_unknown", "status_message": "Tâche non trouvée ou expirée."}), 404
        else:
            return jsonify({"status": "not_found", "status_message": "Tâche non trouvée."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route pour supprimer les données
@app.route('/delete-data', methods=['POST'])
def delete_data():
    target = request.form.get('target')
    target_path_str = request.form.get('path') # Pour les dossiers spécifiques

    try:
        if target == 'leads' and LEADS_FILE.exists():
            LEADS_FILE.unlink()
            flash(f"Fichier {LEADS_FILE.name} supprimé.", "success")
        elif target == 'lists' and LISTS_DIR.exists():
            shutil.rmtree(LISTS_DIR)
            # Recréer le dossier vide après suppression
            LISTS_DIR.mkdir(exist_ok=True) # Utiliser exist_ok=True pour éviter erreur si déjà recréé
            flash(f"Contenu du dossier {LISTS_DIR.name} supprimé.", "success")
        elif target == 'all_results' and RESULTS_DIR_PARENT.exists():
            deleted_count = 0
            for item in RESULTS_DIR_PARENT.glob('Scraping_Results_*'):
                if item.is_dir():
                    shutil.rmtree(item)
                    deleted_count += 1
                # Supprimer aussi les CSV bruts à la racine du dossier parent (si pertinent)
                # elif item.is_file() and item.name.startswith(config.BASE_FINAL_CSV_FILE_NAME):
                #     item.unlink()
                #     deleted_count += 1
            flash(f"{deleted_count} dossier(s) de résultats supprimés.", "success")
        elif target == 'specific_result_dir' and target_path_str:
            # Sécurité: Vérifier que le chemin est bien dans le dossier parent attendu
            target_path = Path(target_path_str).resolve()
            if target_path.is_dir() and target_path.parent == RESULTS_DIR_PARENT.resolve() and target_path.name.startswith("Scraping_Results_"):
                 shutil.rmtree(target_path)
                 flash(f"Dossier {target_path.name} supprimé.", "success")
            else:
                 flash(f"Chemin de dossier invalide ou non autorisé : {target_path_str}", "error")
        else:
            flash("Cible de suppression invalide ou non trouvée.", "error")
    except Exception as e:
        flash(f"Erreur lors de la suppression : {e}", "error")
        import traceback
        traceback.print_exc() # Afficher l'erreur complète dans les logs serveur

    return redirect(url_for('home'))

# Route pour supprimer les cookies
@app.route('/manage-cookies', methods=['POST'])
def manage_cookies():
    target = request.form.get('target')
    try:
        if target == 'facebook' and FB_COOKIES.exists():
            FB_COOKIES.unlink()
            flash("Cookies Facebook supprimés.", "success")
        elif target == 'instagram' and IG_COOKIES.exists():
            IG_COOKIES.unlink()
            flash("Cookies Instagram supprimés.", "success")
        else:
            flash(f"Fichier cookie '{target}' non trouvé ou cible invalide.", "warning")
    except Exception as e:
        flash(f"Erreur lors de la suppression des cookies '{target}': {e}", "error")

    return redirect(url_for('home'))

# Route pour importer (uploader) les cookies
@app.route('/upload-cookies', methods=['POST'])
def upload_cookies():
    # Vérifier si la requête POST contient la partie fichier
    if 'cookie_file' not in request.files:
        flash('Aucun fichier sélectionné dans la requête.', 'error')
        return redirect(url_for('home'))

    file = request.files['cookie_file']

    # Si l'utilisateur ne sélectionne pas de fichier, le navigateur
    # soumet une partie vide sans nom de fichier.
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('home'))

    if file:
        # Utiliser le nom de fichier original pour vérifier s'il est autorisé
        filename = file.filename
        if filename in ALLOWED_COOKIE_FILENAMES:
            # Le chemin de sauvegarde est le dossier de base du projet (config.BASE_DIR)
            save_path = config.BASE_DIR / filename
            try:
                file.save(save_path)
                flash(f'Fichier cookie "{filename}" importé avec succès.', 'success')
            except Exception as e:
                flash(f'Erreur lors de la sauvegarde du fichier "{filename}": {e}', 'error')
        else:
            flash(f'Nom de fichier non autorisé : "{filename}". Seuls {", ".join(ALLOWED_COOKIE_FILENAMES)} sont acceptés.', 'error')

    return redirect(url_for('home'))

# Route pour annuler une tâche RQ
@app.route('/cancel-job/<job_id>', methods=['POST'])
def cancel_job(job_id):
    if not q:
        flash("Erreur: Connexion à Redis échouée.", "error")
        return redirect(url_for('home'))
    try:
        job = Job.fetch(job_id, connection=conn)
        if job:
            if job.is_queued or job.is_started or job.is_deferred:
                job.cancel() # Tente d'annuler la tâche
                # RQ ne met pas immédiatement le statut à 'canceled'.
                # Le worker doit traiter l'annulation.
                flash(f"Demande d'annulation envoyée pour la tâche {job_id}.", "info")
                if session.get('last_job_id') == job_id: # Si c'est la tâche active dans l'UI
                    job.meta['status_message'] = "Annulation demandée par l'utilisateur..."
                    job.save_meta()
            else:
                flash(f"La tâche {job_id} ne peut pas être annulée (statut: {job.get_status()}).", "warning")
        else:
            flash(f"Tâche {job_id} non trouvée.", "error")
    except Exception as e:
        flash(f"Erreur lors de l'annulation de la tâche {job_id}: {e}", "error")
    return redirect(url_for('home'))

# Route pour redémarrer les services
@app.route('/restart_services', methods=['POST'])
def restart_services():
    # IMPORTANT: Nécessite une configuration sudoers pour l'utilisateur exécutant Flask.
    # Ex: your_flask_user ALL=(ALL) NOPASSWD: /bin/systemctl restart alienscraper-app.service, /bin/systemctl restart alienscraper-worker.service
    commands_to_run = [
        {"cmd": ["sudo", "systemctl", "restart", "alienscraper-worker.service"], "name": "alienscraper-worker.service"},
        {"cmd": ["sudo", "systemctl", "restart", "alienscraper-app.service"], "name": "alienscraper-app.service"} # App en dernier
    ]
    
    all_successful = True
    for item in commands_to_run:
        service_name = item["name"]
        command = item["cmd"]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                flash(f"Service {service_name} redémarré avec succès.", "success")
            else:
                all_successful = False
                error_details = result.stderr.strip() if result.stderr else "Aucun détail d'erreur."
                flash(f"Échec du redémarrage de {service_name}. Code: {result.returncode}. Erreur: {error_details}", "error")
        except subprocess.TimeoutExpired:
            all_successful = False
            flash(f"Timeout lors du redémarrage de {service_name}.", "error")
        except Exception as e:
            all_successful = False
            flash(f"Erreur inattendue lors de la tentative de redémarrage de {service_name}: {str(e)}", "error")

    # La redirection peut être affectée si alienscraper-app.service est redémarré.
    # L'utilisateur pourrait avoir besoin de rafraîchir manuellement.
    return redirect(url_for('home'))

# Route pour télécharger les fichiers CSV
@app.route('/download/<path:filename>')
def download_file(filename):
    # Sécurité : Définir les répertoires autorisés pour le téléchargement
    allowed_directories = {
        'leads': config.BASE_DIR, # Pour leads.csv à la racine
        'lists': config.LISTES_OUTPUT_DIR # Pour les fichiers dans /listes
    }

    # Déterminer le répertoire et le nom de fichier demandé
    if filename == LEADS_FILE.name:
        directory = allowed_directories['leads']
    elif (LISTS_DIR / filename).exists():
        directory = allowed_directories['lists']
    else:
        return abort(404) # Fichier non trouvé ou non autorisé

    return send_from_directory(directory, filename, as_attachment=True)

# Permet de lancer l'application directement avec 'python app/app.py'
if __name__ == '__main__':
    # host='0.0.0.0' rend l'app accessible depuis d'autres machines sur le réseau
    # debug=True active le mode débogage (recharge auto, messages d'erreur détaillés) - NE PAS UTILISER EN PRODUCTION sur un serveur public
    # Utiliser debug=False pour la production ou le test sur serveur
    # Make sure the port is an integer
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
