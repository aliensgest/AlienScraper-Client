from pathlib import Path

# --- Version ---
APP_VERSION = "2025 V2"
# --- Chemins Principaux ---
# Chemin de base du projet (le dossier où se trouve ce fichier config.py)
# __file__ est le chemin de ce fichier config.py
# .resolve() rend le chemin absolu
# .parent donne le dossier parent (donc /home/AlienScraper)
BASE_DIR = Path(__file__).resolve().parent

# Chemin vers le fichier leads.csv final (dans le dossier de base)
LEADS_CSV_FINAL_PATH = BASE_DIR / "leads.csv"

# Chemin vers le dossier où les listes extraites sont sauvegardées (sous-dossier 'listes')
LISTES_OUTPUT_DIR = BASE_DIR / "listes"

# Chemin vers le dossier où les résultats bruts sont sauvegardés (directement dans le dossier de base pour les sous-dossiers Scraping_Results_*)
RAW_RESULTS_PARENT_DIR = BASE_DIR

# --- Noms de Fichiers ---
BASE_FINAL_CSV_FILE_NAME = "collected_prospects_detailed" # Utilisé dans main_scraper