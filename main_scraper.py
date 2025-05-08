# /home/AlienScraper/main_scraper.py

import time
import random
import sys
import os
import csv
import threading
import traceback
from datetime import datetime
from itertools import product # Garder cet import
from pathlib import Path # Importer Path
from urllib.parse import urlparse, urlunparse, parse_qs
import re # Import regex for phone number cleaning
from rq import get_current_job # Importer pour la progression
import json # Pour parser la réponse de l'IA

# --- Import Google Generative AI Library pour Main Scraper ---
try:
    import google.generativeai as genai
    # Assurez-vous que la variable d'environnement GOOGLE_API_KEY est définie
    # ou configurez l'API key directement ici si nécessaire.
    # genai.configure(api_key="YOUR_API_KEY")
    print("[Main Scraper - Gemini API] Google API Key loaded from environment variable.")
    gemini_model_main = genai.GenerativeModel('gemini-1.5-flash') # Modèle pour l'extraction générique
    print("[Main Scraper - Gemini API] Gemini 1.5 Flash model loaded for generic extraction.")
except ImportError:
    print("[Main Scraper - Gemini API] google.generativeai non trouvé. AI generic extraction will be skipped.")
    gemini_model_main = None

# --- Import project modules ---
try:
    import config # Import configuration centralisée
    from scraper import google_search_scraper # Import depuis le sous-dossier

    # Les imports suivants sont dynamiques et gérés ci-dessous,
    # mais on garde les références pour les fonctions ensure_login
    import undetected_chromedriver as uc
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.remote.remote_connection import LOGGER as seleniumLogger
    from selenium.webdriver.common.by import By
    import logging
    # Configure logging for selenium.webdriver.remote.remote_connection
    seleniumLogger.setLevel(logging.WARNING)

    # Import the page scraper modules dynamically to check for their presence and use their login functions
    try:
        from scraper import facebook_page_scraper # Import depuis le sous-dossier
        print("Module facebook AlienScraper imported.")
    except ImportError:
        print("Module facebook_page_scraper not found. Facebook page scraping will be skipped.")
        facebook_page_scraper = None

    try:
        from scraper import instagram_page_scraper # Import depuis le sous-dossier
        print("Module instagram AlienScraper imported.")
    except ImportError:
        print("Module instagram_page_scraper not found. Instagram page scraping will be skipped.")
        instagram_page_scraper = None

except ImportError as e:
    print(f"ERREUR CRITIQUE : Erreur lors de l'importation d'un module principal (config, undetected_chromedriver, selenium, ou scraper): {e}")
    sys.exit(1)

# Importer le module clean
try:
    import clean
    print("Module clean imported.")
except ImportError:
    print("Erreur: Le module clean.py est introuvable. L'option de création de leads ne sera pas disponible.")
    clean = None  # Set to None if import fails

# Importer le module d'extraction de listes
try:
    import extract_leads
    print("Module extract_leads imported.")
except ImportError:
    print("Erreur: Le module extract_leads.py est introuvable. L'option de mise à jour des listes ne sera pas disponible.")
    extract_leads = None # Set to None if import fails


# --- Configuration Globale (Utilisation de config.py) ---
# LEADS_CSV_FINAL_PATH est maintenant défini dans config.py
# BASE_FINAL_CSV_FILE_NAME est maintenant défini dans config.py

FINAL_CSV_HEADERS = [
    "Nom du tiers", "Nom alternatif", "État", "Code client", "Adresse", "Téléphone",
    "Url", "Email", "Client", "Fournisseur", "Date création", "Facebook", "Instagram",
    "Whatsapp", "URL_Originale_Source", "Bio", "Source_Mot_Cle", "Type_Source",
    "Nom_Trouve_Recherche", "Titre_Trouve_Google", "Type_Lien_Google",
    "Statut_Scraping_Detail", "Message_Erreur_Detail",
    "Nombre de Publications", "Nombre de Followers", "Nombre de Suivis" # Add new headers for counts
]

# --- Variables de contrôle pour l'entrée utilisateur (Globales - pour mode autonome) ---
stop_scraping_full = False      # Arrêt complet (qq)
stop_scraping_urls_only = False # Arrêt de la recherche d'URLs pour la combinaison actuelle (q)
skip_combination = False        # Passer à la combinaison suivante (s)
skip_url = False                # Passer à l'URL suivante (u)

# --- Regex for cleaning phone numbers ---
CLEAN_PHONE_REGEX = re.compile(r'[\s().\-+📲📞☎️]') # Use the same regex as in scrapers

# --- Configuration pour les screenshots de débogage ---
# S'assurer que config.SCREENSHOTS_DIR est défini. Sinon, fallback.
if hasattr(config, 'BASE_DIR'): # S'assurer que config.BASE_DIR est disponible
    SCREENSHOTS_DIR = config.BASE_DIR / "screenshots"
else: # Fallback si config.BASE_DIR n'est pas défini (ne devrait pas arriver)
    SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"
    print(f"AVERTISSEMENT: config.BASE_DIR non trouvé, SCREENSHOTS_DIR défini à {SCREENSHOTS_DIR}")

try:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception as e_mkdir:
    print(f"ERREUR: Impossible de créer le dossier de screenshots {SCREENSHOTS_DIR}: {e_mkdir}")


# --- Function for Moroccan Phone Reformatting ---
def format_phone_to_whatsapp_link(phone_number):
    """
    Cleans a phone number and formats it into a wa.me link, applying Moroccan +212 format heuristic.
    Returns a wa.me link string or "Not Generated" if the input is invalid.
    """
    if not phone_number or not isinstance(phone_number, str) or phone_number in ["Not Found", "N/A", "Not Generated"]:
        return "Not Generated"

    cleaned_phone = CLEAN_PHONE_REGEX.sub('', phone_number).strip()

    # Basic validation: check if it contains at least 7 digits
    if sum(c.isdigit() for c in cleaned_phone) < 7:
         return "Not Generated" # Not enough digits

    # Moroccan +212 formatting heuristic
    if cleaned_phone.startswith('0') and len(cleaned_phone) in [9, 10]: # Common Moroccan 0X XX XX XX XX format
        return f"https://wa.me/212{cleaned_phone[1:]}"
    elif cleaned_phone.startswith('212') and len(cleaned_phone) in [11, 12]: # Already 212XXXXXXXXX format
         return f"https://wa.me/{cleaned_phone}"
    elif cleaned_phone.startswith('+212') and len(cleaned_phone) in [12, 13]: # Already +212XXXXXXXXX format
         return f"https://wa.me/{cleaned_phone.replace('+', '')}" # Remove '+' for wa.me format
    elif re.fullmatch(r'\d{7,15}', cleaned_phone): # Generic international or other formats with enough digits
        return f"https://wa.me/{cleaned_phone}"
    else:
         # Fallback if regex or specific formats don't match, but it contains digits
         return "Not Generated" # Could not format reliably

# --- Function to handle user input in a separate thread (pour mode autonome) ---
def user_input_listener():
    global stop_scraping_full, stop_scraping_urls_only, skip_combination, skip_url
    # The control instructions are now printed in the main thread just before input starts
    while not stop_scraping_full:
        try:
            user_input = input().strip().lower()
            if user_input == 's':
                skip_combination = True
                stop_scraping_urls_only = True # Also stop URL search for current combo when skipping combination
                print("Signalé: Passer à la combinaison suivante...")
            elif user_input == 'u':
                skip_url = True
                print("Signalé: Passer à l'URL suivante...")
            elif user_input == 'q':
                stop_scraping_urls_only = True
                print("Signalé: Arrêt de la recherche d'URLs pour cette combinaison. Passage au scraping détaillé...")
            elif user_input == 'qq':
                stop_scraping_full = True
                stop_scraping_urls_only = True # Also stop URL search for current combo when stopping full
                skip_url = True # Also skip current URL when stopping full
                print("Signalé: Arrêt complet demandé. Sauvegarde en cours...")
        except EOFError: # Handle Ctrl+D or end of input stream
             print("\nEOF detected, stopping listener.")
             stop_scraping_full = True
             stop_scraping_urls_only = True
             skip_url = True
             break
        except Exception as e:
            # Avoid printing stack trace for simple input errors
            print(f"Erreur lors de la lecture de l'entrée utilisateur : {type(e).__name__} - {e}")
            time.sleep(0.1)

# --- Fonction pour sauvegarder la liste de dictionnaires en CSV (Globale) ---
def save_results_to_csv(results_list, base_filename, headers):
    """
    Sauvegarde une liste de dictionnaires dans un fichier CSV, avec déduplication basée sur 'URL_Originale_Source'.
    Utilise config.RAW_RESULTS_PARENT_DIR.
    """
    print(f"\n[Main - Save CSV] Sauvegarde de {len(results_list)} entrées uniques dans un fichier CSV...")

    if not results_list:
        print("[Main - Save CSV] Aucune donnée à sauvegarder.")
        return

    seen_keys = set()
    unique_results = []

    # Vérification et déduplication des résultats
    for idx, result in enumerate(results_list):
        # Ensure result is a dictionary and has a string 'URL_Originale_Source'
        if isinstance(result, dict) and 'URL_Originale_Source' in result and isinstance(result['URL_Originale_Source'], str) and result['URL_Originale_Source'].strip():
            # Use strip() on the URL for more robust deduplication
            cleaned_original_url = result['URL_Originale_Source'].strip()
            if cleaned_original_url not in seen_keys:
                unique_results.append(result)
                seen_keys.add(cleaned_original_url)
            # else: print(f"[Main - Save CSV] Doublon ignoré : {result.get('URL_Originale_Source')}")  # Optionnel
        else:
            print(f"[Main - Save CSV] Avertissement: Entrée {idx+1} ne contient pas une 'URL_Originale_Source' valide ou est de type incorrect : {result}")

    print(f"[Main - Save CSV] {len(unique_results)} entrées uniques après filtrage interne à la sauvegarde.")

    if not unique_results:
        print("[Main - Save CSV] Aucune entrée unique valide à sauvegarder après filtrage.")
        return

    # Création du dossier de résultats (utilise config.py)
    today_date_str = datetime.now().strftime("Scraping_Results_%d%m%Y")
    results_folder_path = config.RAW_RESULTS_PARENT_DIR / today_date_str # Utilise le dossier parent défini dans config.py

    if not results_folder_path.exists():
        try:
            results_folder_path.mkdir(parents=True, exist_ok=True)
            print(f"[Main - Save CSV] Création du dossier de résultats : {results_folder_path}")
        except OSError as e:
            print(f"[Main - Save CSV] Erreur lors de la création du dossier de résultats {results_folder_path}: {e}")
            results_folder_path = config.BASE_DIR # Fallback to base directory from config

    # Génération du chemin final pour le fichier CSV (utilise config.py)
    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    final_filepath = results_folder_path / f"{config.BASE_FINAL_CSV_FILE_NAME}_{timestamp}.csv" # Utilise le nom de base défini dans config.py

    # Écriture des résultats dans le fichier CSV
    try:
        with open(final_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            # Ensure headers match the keys in the dictionaries in unique_results
            # Use the full FINAL_CSV_HEADERS list
            writer = csv.DictWriter(csvfile, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(unique_results)
        print(f"[Main - Save CSV] Fichier CSV sauvegardé : {final_filepath}")
    except Exception as e:
        print(f"[Main - Save CSV] Erreur lors de la sauvegarde du fichier CSV : {e}")
        traceback.print_exc()

# --- Fonction pour générer les combinaisons ---
def generate_keyword_combinations(keywords_lists):
    # Ensure that if a list is empty, it's treated as containing a single empty string for product
    # This handles cases where a category was left blank.
    processed_lists = [lst if lst else [""] for lst in keywords_lists]
    # Generate combinations, filter out empty strings from the combination if they come from an empty input
    # and join them with a space. Ensure the final combination string is not just whitespace.
    combinations = [" ".join(filter(None, combo)).strip() for combo in product(*processed_lists)]
    # Filter out any combinations that result in empty strings or only whitespace after joining
    valid_combinations = [combo for combo in combinations if combo]
    return valid_combinations


# --- Fonction utilitaire pour sauvegarder les infos de débogage ---
def save_debug_info(driver, error_type, context_name="general"):
    """Sauvegarde un screenshot et le code source de la page en cas d'erreur."""
    if not driver:
        print("    [Debug Save] Driver non disponible, impossible de sauvegarder les infos de débogage.")
        return

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Nettoyer context_name pour l'utiliser dans un nom de fichier
        safe_context = re.sub(r'[^\w\-_\. ]', '_', str(context_name))[:50] # Limiter la longueur
        
        screenshot_filename = f"{timestamp}_{error_type}_{safe_context}.png"
        html_filename = f"{timestamp}_{error_type}_{safe_context}.html"
        
        # Utiliser SCREENSHOTS_DIR défini globalement
        screenshot_path = SCREENSHOTS_DIR / screenshot_filename
        html_path = SCREENSHOTS_DIR / html_filename

        current_url_debug = "unknown_url"
        try:
            current_url_debug = driver.current_url
            driver.save_screenshot(str(screenshot_path))
            print(f"    [Debug Save] Screenshot sauvegardé : {screenshot_path}")
        except Exception as e_ss:
            print(f"    [Debug Save] Erreur lors de la sauvegarde du screenshot : {e_ss}")

        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"    [Debug Save] Code source HTML sauvegardé : {html_path}")
        except Exception as e_html:
            print(f"    [Debug Save] Erreur lors de la sauvegarde du code HTML : {e_html}")
        print(f"    [Debug Save] URL actuelle lors de l'erreur: {current_url_debug}")
    except Exception as e_debug:
        print(f"    [Debug Save] Erreur majeure dans save_debug_info : {e_debug}")

# --- Interface utilisateur pour les mots-clés (pour mode autonome) ---
def get_keywords_input_main():
    print("\n--- Entrée des Mots-clés ---")
    keyword_categories = [
        "Qu'est-ce que vous recherchez (ex: restaurant, café, magasin)",
        "Où vous voulez chercher (ville, région, ex: Rabat, Casablanca)",
        "Mots-clés additionnels (ex: 2024, 2025, livraison, bio)"
    ]

    keywords_lists = []
    for description in keyword_categories:
        # Corrected input prompt format
        user_input = input(f"{description} (séparés par des virgules, laissez vide si non utilisé) : ").strip()
        keywords = [kw.strip() for kw in user_input.split(',') if kw.strip()]
        keywords_lists.append(keywords if keywords else []) # Use empty list if input is empty

    print("---------------------------------")
    return keywords_lists

# --- Utility function to clean URLs ---
def clean_url(url):
    """
    Cleans a URL by removing query parameters and fragments, preserving scheme, netloc, and path.
    Handles common social media URL structures.
    Returns the cleaned URL string or "Not Found" if the input is invalid.
    """
    if not url or not isinstance(url, str) or url in ["Not Found", "N/A", "N/A (Insta)", "N/A (FB)", "Not Generated"]:
        return "Not Found"

    try:
        parsed_url = urlparse(url)
        scheme = parsed_url.scheme
        netloc = parsed_url.netloc
        path = parsed_url.path.strip('/') # Remove leading/trailing slashes initially

        # Specific cleaning based on domain
        if "instagram.com" in netloc.lower():
             path_segments = [segment for segment in path.split('/') if segment]
             if path_segments:
                 # Assume the first segment after the domain is the username
                 path = '/' + path_segments[0] + '/' # Add trailing slash back for convention
             else:
                  path = '/' # Root Instagram URL (unlikely for a profile)

        elif "facebook.com" in netloc.lower():
             # Handle profile.php?id=... specifically by preserving the id query parameter
             if parsed_url.path.lower().strip('/') == 'profile.php' and 'id' in parse_qs(parsed_url.query):
                 query_params = parse_qs(parsed_url.query)
                 query = f"?id={query_params['id'][0]}" if query_params['id'] else ""
                 path = parsed_url.path # Keep original path /profile.php
                 # Reconstruct with preserved query
                 cleaned_url = urlunparse((scheme, netloc, path, '', query, ''))
                 return cleaned_url.strip() # Return early for this specific case

             # For other Facebook URLs (pages, groups), just remove query and fragment
             path = parsed_url.path # Keep the full path

        elif "wa.me" in netloc.lower():
             # Keep only the number part in the path
             path_segments = [segment for segment in path.split('/') if segment]
             if path_segments:
                 path = '/' + path_segments[0] # Should be just the number
             else:
                  path = '/' # Should not happen for a valid wa.me link

        elif not path: # If path is empty after strip, use '/'
             path = '/'
        else: # Add leading and trailing slashes back to the path for consistency unless it's a file (like .html)
             # Heuristic: Add trailing slash if it doesn't look like a file path
             if '.' not in path.split('/')[-1]:
                  path = '/' + path + '/'
             else:
                  path = '/' + path # Just add leading slash for file paths


        # Reconstruct the URL without query parameters and fragment, but keep cleaned path
        cleaned_url = urlunparse((scheme, netloc, path, '', '', '')) # scheme, netloc, path, params, query, fragment

        return cleaned_url.strip()

    except Exception:
        # If parsing or cleaning fails, return "Not Found"
        return "Not Found"


# --- Fonction pour mapper les données collectées au format CSV final ---
def map_data_to_final_format(detailed_data):
    """
    Mappe le dictionnaire de données détaillé (collecté par les page scrapers)
    et les informations source au format des en-têtes CSV finaux.
    Assure que toutes les clés attendues sont présentes.
    Nettoie les URLs et formate le numéro de téléphone en lien WhatsApp.
    """
    # Initialiser le dictionnaire final avec des valeurs par défaut
    # Use "Not Found" or "N/A" consistently where appropriate
    final_row = {header: "Not Found" for header in FINAL_CSV_HEADERS}

    # Valeurs par défaut pour certains champs
    final_row["État"] = "Prospect"
    final_row["Code client"] = "" # Keep as empty string
    final_row["Client"] = 2 # Keep as number 2
    final_row["Fournisseur"] = 0 # Keep as number 0
    final_row["Date création"] = datetime.now().strftime("%d/%m/%Y")

    # Transfer and map data from detailed_data dictionary
    # Use .get() with a default value to handle missing keys gracefully
    final_row["URL_Originale_Source"] = detailed_data.get("URL_Originale_Source", "N/A")
    final_row["Source_Mot_Cle"] = detailed_data.get("Source_Mot_Cle", "N/A")
    final_row["Type_Source"] = detailed_data.get("Type_Source", "N/A")
    final_row["Nom_Trouve_Recherche"] = detailed_data.get("Nom_Trouve_Recherche", "N/A")
    final_row["Titre_Trouve_Google"] = detailed_data.get("Titre_Trouve_Google", "N/A")
    final_row["Type_Lien_Google"] = detailed_data.get("Type_Lien_Google", "N/A")

    # Map status and error messages, providing defaults if missing
    final_row["Statut_Scraping_Detail"] = detailed_data.get("Statut_Scraping_Detail", "Unknown Status")
    final_row["Message_Erreur_Detail"] = detailed_data.get("Message_Erreur_Detail", "")

    # Mappage des champs spécifiques
    final_row["Nom du tiers"] = (
        detailed_data.get("Nom de la Page") or
        detailed_data.get("Nom_AI") or
        detailed_data.get("Nom Complet") or
        detailed_data.get("Nom_Trouve_Recherche") or
        detailed_data.get("Titre_Trouve_Google") or
        "Nom Inconnu"
    )

    final_row["Nom alternatif"] = (
        detailed_data.get("Nom d'Utilisateur") or
        (detailed_data.get("Nom_Trouve_Recherche") if final_row["Nom du tiers"] != detailed_data.get("Nom_Trouve_Recherche") else "Not Found")
    )

    final_row["Adresse"] = detailed_data.get("Adresse", "Not Found")
    if final_row["Adresse"] == "Not Found": final_row["Adresse"] = detailed_data.get("Adresse_AI", "Not Found")
    final_row["Téléphone"] = detailed_data.get("Téléphone", "Not Found")
    if final_row["Téléphone"] == "Not Found": final_row["Téléphone"] = detailed_data.get("Telephone_AI", "Not Found")
    final_row["Email"] = detailed_data.get("Email", "Not Found")
    if final_row["Email"] == "Not Found": final_row["Email"] = detailed_data.get("Email_AI", "Not Found")
    final_row["Bio"] = detailed_data.get("Bio", "N/A")
    if final_row["Bio"] == "N/A": final_row["Bio"] = detailed_data.get("Bio_AI", "N/A")

    # Mappage du champ "Url" (Site Web)
    final_row["Url"] = (
        detailed_data.get("Site Web") or
        detailed_data.get("Site Web (Bio)") or
        "Not Found"
    )

    # Mappage des réseaux sociaux
    url_originale = detailed_data.get('URL_Originale_Source', '').lower()
    final_row["Facebook"] = (
        detailed_data.get("URL_Originale_Source") if "facebook.com" in url_originale else
        detailed_data.get("Facebook", "Not Found")
    )
    if final_row["Facebook"] == "Not Found": final_row["Facebook"] = detailed_data.get("Facebook_AI", "Not Found")
    final_row["Instagram"] = (
        detailed_data.get("URL_Originale_Source") if "instagram.com" in url_originale else
        detailed_data.get("Instagram", "Not Found")
    )
    if final_row["Instagram"] == "Not Found": final_row["Instagram"] = detailed_data.get("Instagram_AI", "Not Found")

    # === Mappage du champ WhatsApp ===
    whatsapp_verifier_fb = detailed_data.get("WhatsApp à vérifier")
    whatsapp_fb = detailed_data.get("WhatsApp")

    if whatsapp_verifier_fb not in ["Not Generated", "Invalid Phone Format for WhatsApp", "N/A (Insta)", "N/A (FB)", None]:
        final_row["Whatsapp"] = whatsapp_verifier_fb
    elif whatsapp_fb not in ["Not Found", "N/A (Insta)", "N/A (FB)", None]:
        final_row["Whatsapp"] = whatsapp_fb
    else:
        final_row["Whatsapp"] = detailed_data.get("WhatsApp_AI", "Not Found")

    # Mappage des compteurs (followers, etc.)
    final_row["Nombre de Publications"] = detailed_data.get("Nombre de Publications", "N/A")
    final_row["Nombre de Followers"] = detailed_data.get("Nombre de Followers", "N/A")
    final_row["Nombre de Suivis"] = detailed_data.get("Nombre de Suivis", "N/A")

    return final_row

# --- Fonction d'extraction AI pour les URLs génériques ---
def extract_info_with_ai(driver, url, model, source_info):
    """
    Tente d'extraire des informations d'une URL générique en utilisant l'IA (Gemini).
    Retourne un dictionnaire avec les données extraites et un statut.
    """
    print(f"    [AI Extract] Tentative d'extraction AI pour : {url}")
    if not model:
        print("    [AI Extract] Modèle AI non disponible. Skip.")
        return {
            "Statut_Scraping_Detail": "Skipped - AI Model Unavailable",
            "Message_Erreur_Detail": "Gemini model not loaded in main_scraper.",
            **source_info
        }

    extracted_data_ai = {}
    status = "Error - AI Extraction Failed"
    error_message = "Unknown AI extraction error."

    try:
        driver.get(url)
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import NoSuchElementException
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script('return document.readyState') == 'complete'
        )
        time.sleep(random.uniform(2, 4))

        try:
            body_text = driver.find_element(By.TAG_NAME, 'body').text
            page_title = driver.title
            max_chars = 15000
            content_for_ai = f"Title: {page_title}\n\nBody Text (first {max_chars} chars):\n{body_text[:max_chars]}"
        except NoSuchElementException:
            print("    [AI Extract] Impossible de trouver le body de la page.")
            error_message = "Could not find body element."
            content_for_ai = None

        if content_for_ai:
            prompt = f"""
            Analyse le contenu textuel suivant extrait de l'URL {url}.
            Identifie les informations de contact et de profil pertinentes pour un prospect commercial.
            Si le site semble trop complexe (ex: nécessite login, CAPTCHA, structure très dynamique difficile à analyser statiquement) ou si aucune information pertinente n'est trouvée, réponds SEULEMENT avec le mot : COMPLEX.
            Sinon, extrais les informations suivantes et retourne-les dans un format JSON valide contenant UNIQUEMENT les clés suivantes (utilise "Not Found" si une info n'est pas trouvée) :
            - "Nom_AI": Le nom de l'entreprise, de la personne ou de la page.
            - "Telephone_AI": Le numéro de téléphone principal.
            - "Email_AI": L'adresse email de contact principale.
            - "Adresse_AI": L'adresse physique si disponible.
            - "SiteWeb_AI": Un lien vers un site web principal s'il est différent de l'URL analysée ou mentionné explicitement.
            - "Facebook_AI": URL de la page Facebook si mentionnée.
            - "Instagram_AI": URL du profil Instagram si mentionné.
            - "WhatsApp_AI": Numéro ou lien WhatsApp si mentionné.
            - "Bio_AI": Une courte description ou bio si disponible.

            Contenu à analyser :
            ---
            {content_for_ai}
            ---
            Réponds SEULEMENT avec le JSON ou le mot COMPLEX.
            """
            print("    [AI Extract] Appel de l'API Gemini...")
            response = model.generate_content(prompt)
            response_text = response.text.strip()
            print(f"    [AI Extract] Réponse brute de l'IA: {response_text[:100]}...")

            if response_text == "COMPLEX":
                print("    [AI Extract] L'IA a jugé le site complexe ou sans informations pertinentes.")
                status = "Skipped - AI Judged Complex"
                error_message = "AI determined the site is complex or lacks relevant info."
            else:
                try:
                    # --- NETTOYAGE de la réponse AI ---
                    # Retirer les blocs de code Markdown potentiels (```json ... ```)
                    cleaned_response_text = response_text.strip()
                    if cleaned_response_text.startswith("```json"):
                        cleaned_response_text = cleaned_response_text[7:]
                    if cleaned_response_text.endswith("```"):
                        cleaned_response_text = cleaned_response_text[:-3]
                    ai_json_data = json.loads(cleaned_response_text.strip()) # Parser la chaîne nettoyée
                    extracted_data_ai = ai_json_data
                    status = "Success - AI Extraction"
                    error_message = ""
                    print("    [AI Extract] Informations extraites par l'IA.")
                except json.JSONDecodeError:
                    print("    [AI Extract] Erreur: La réponse de l'IA n'est pas un JSON valide et n'est pas 'COMPLEX'.")
                    error_message = "AI response was not valid JSON or 'COMPLEX'."
                    status = "Error - AI Invalid Response"
                except Exception as e_parse:
                    print(f"    [AI Extract] Erreur lors du parsing de la réponse JSON de l'IA : {e_parse}")
                    error_message = f"Error parsing AI JSON response: {e_parse}"
                    status = "Error - AI Response Parsing Failed"

    except WebDriverException as e_nav:
        print(f"    [AI Extract] Erreur WebDriver lors de la navigation ou de l'extraction de contenu pour {url}: {e_nav}")
        error_message = f"WebDriver error accessing page: {type(e_nav).__name__}"
        if driver: # 'driver' est passé à extract_info_with_ai
            save_debug_info(driver, f"AI_WebDriver_{type(e_nav).__name__}", url)
        status = "Error - AI Page Load Failed"
    except Exception as e_ai_call:
        print(f"    [AI Extract] Erreur lors de l'appel à l'API Gemini pour {url}: {e_ai_call}")
        if hasattr(e_ai_call, 'prompt_feedback') and hasattr(e_ai_call.prompt_feedback, 'block_reason'):
             error_message = "AI content blocked (safety filters)."
             status = "Error - AI Content Blocked"
        else:
             if driver: # 'driver' est passé à extract_info_with_ai
                 save_debug_info(driver, f"AI_API_{type(e_ai_call).__name__}", url)
             error_message = f"Error calling AI API: {type(e_ai_call).__name__}"
             status = "Error - AI API Call Failed"

    final_data = {**source_info, **extracted_data_ai}
    final_data["Statut_Scraping_Detail"] = status
    final_data["Message_Erreur_Detail"] = error_message

    return final_data

# --- Fonction encapsulant le processus complet de scraping ---
def run_full_scraping_process(keywords_input_lists, google_pages_limit=5, google_allowed_link_types=None, run_clean_option=False, run_extract_option=False):
    """
    Exécute l'ensemble du processus de scraping : recherche Google, scraping détaillé,
    sauvegarde, et options de nettoyage/extraction.
    """
    # --- DEBUG PRINT ---
    print(f"DEBUG: Entrée dans run_full_scraping_process. google_allowed_link_types = {google_allowed_link_types}")
    # --- FIN DEBUG PRINT ---
    # --- Récupérer la tâche RQ actuelle ---
    job = get_current_job()
    # ---
    print("--- AlienScraper© : Application de Scraping Multi-Sources ---")

    # --- 1. Configuration Initiale (Mots-clés & Sources) ---
    # Ne pas appeler get_keywords_input_main() si les mots-clés sont déjà fournis
    # keywords_input_lists = get_keywords_input_main() # On commente cette ligne
    all_combinations = generate_keyword_combinations(keywords_input_lists)

    if not all_combinations:
        print("Aucune combinaison de mots-clés valide générée. Fin du processus.")
        # Utiliser return au lieu de sys.exit pour que le worker RQ puisse terminer proprement
        return

    print(f"\n{len(all_combinations)} combinaisons de mots-clés générées.")
    print("-----------------------------------------------")

    # --- 2. Source de recherche (Fixée à Google) ---
    sources_to_use = ['google']
    print("\nSource de recherche : Google (automatiquement sélectionné)")
    # Vérifier si le module Google est disponible
    if 'google' in sources_to_use and not google_search_scraper:
        print("ERREUR CRITIQUE : google_search_scraper.py n'a pas pu être importé. Le script ne peut pas continuer.")
        # Utiliser return au lieu de sys.exit
        return
    print("-----------------------------")

    # --- 3. Utiliser les options passées en paramètres ---
    print("\n--- Configuration des Limites et Filtres de Recherche (Utilisation des paramètres) ---")
    print(f"Limite de pages Google : {google_pages_limit}")

    if google_allowed_link_types:
        print(f"\nRecherche Google configurée par défaut pour les types de liens : {', '.join(google_allowed_link_types)}")
        print("(Basé sur les modules de scraping Facebook/Instagram disponibles)")
    else: # Alignement corrigé
        print("\nAucun module de scraping spécifique (Facebook/Instagram) n'est disponible. La recherche Google inclura tous les types de liens.")
        # google_allowed_link_types = None # Pas besoin de réassigner, il est déjà None ou vide

    print("-----------------------------") # Alignement corrigé

    # input("Appuyez sur Entrée pour initialiser le navigateur et démarrer le processus...") # Commenté pour l'exécution non interactive

    # --- 4. Initialisation du Navigateur et Connexions ---
    driver = None
    collected_urls_from_search = []
    seen_urls_overall = set()

    try:
        # Spécifier explicitement le chemin de l'exécutable Chromium pour Linux
        options = uc.ChromeOptions()
        
        # Options recommandées pour les environnements headless/VM/XVFB
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu') # Important pour XVFB
        options.add_argument('--window-size=1920,1080') # Peut aider au rendu
        # options.add_argument('--headless=new') # À ne PAS utiliser avec XVFB
        # Options supplémentaires pour la stabilité / furtivité
        options.add_argument('--start-maximized') # Peut aider avec XVFB si window-size ne suffit pas
        options.add_argument('--disable-extensions') # Désactiver les extensions qui pourraient interférer
        options.add_argument('--disable-popup-blocking') # Peut être utile pour certains sites
        options.add_argument('--ignore-certificate-errors') # À utiliser avec prudence
        options.add_argument('--lang=fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7') # Préférer le français
        options.add_argument('--disable-blink-features=AutomationControlled') # uc le fait déjà, mais pour être sûr
        options.add_argument(f"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/11{random.randint(0,9)}.0.0.0 Safari/537.36") # Randomiser un peu plus

        # Vérifie si ce chemin est correct sur ton système avec 'which chromium-browser'
        # Essayez d'abord google-chrome si vous l'avez installé, sinon chromium-browser
        chromium_path_chrome = "/usr/bin/google-chrome" 
        chromium_path_chromium = "/usr/bin/chromium-browser"

        # Vérifier si le fichier existe avant de l'utiliser
        if Path(chromium_path_chrome).is_file():
            print(f"Utilisation de Google Chrome trouvé à {chromium_path_chrome}")
            driver = uc.Chrome(browser_executable_path=chromium_path_chrome, options=options)
        elif Path(chromium_path_chromium).is_file():
            print(f"Utilisation de Chromium Browser trouvé à {chromium_path_chromium}")
            driver = uc.Chrome(browser_executable_path=chromium_path_chromium, options=options)
        else:
            print(f"ERREUR: Exécutable Chrome/Chromium non trouvé à {chromium_path_chrome} ou {chromium_path_chromium}. Tentative sans chemin spécifique.")
            driver = uc.Chrome(options=options) # Laisse uc essayer de le trouver

        print("Navigateur Chrome furtif initialisé par main_scraper.")

        # Connexion Facebook (nécessaire pour scraper des pages FB trouvées par Google)
        if facebook_page_scraper and 'google' in sources_to_use:
            print("\nTentative d'assurer la connexion Facebook...")
            # S'assurer que COOKIES_FILE utilise config.py
            fb_cookies_path = config.BASE_DIR / "facebook_cookies.json"
            session_active_fb = facebook_page_scraper.ensure_facebook_login(driver, fb_cookies_path)
            if not session_active_fb:
                print("Attention : Connexion Facebook échouée ou non établie. Le scraping des pages Facebook pourrait être limité.")
        else:
            print("\nSkip tentative d'assurer la connexion Facebook (module non importé ou pas de source Google choisie).")

        # Connexion Instagram (nécessaire pour scraper des pages Insta trouvées par Google)
        if instagram_page_scraper and 'google' in sources_to_use:
            print("\nTentative d'assurer la connexion Instagram...")
            # S'assurer que INSTAGRAM_COOKIES_FILE utilise config.py
            insta_cookies_path = config.BASE_DIR / "instagram_cookies.json"
            session_active_insta = instagram_page_scraper.ensure_instagram_login(driver, insta_cookies_path)
            if not session_active_insta:
                print("Attention : Connexion Instagram échouée ou non établie. Le scraping des pages Instagram pourrait être limité.")
        else:
            print("\nSkip tentative d'assurer la connexion Instagram (module non importé ou pas de source Google choisie).")

        # --- 5. Lancer les Search Scrapers ---
        collected_urls_from_search = []
        seen_urls_overall = set()

        if not sources_to_use:
            print("Aucune source de recherche valide sélectionnée. Skip la phase de recherche.")
        else:

            # Lancer Google Search si sélectionné
            if 'google' in sources_to_use and google_search_scraper:
                print("\nLancement du scraping de recherche Google...")
                # Utiliser les variables configurées
                google_urls = google_search_scraper.scrape_google_search(
                    driver,
                    all_combinations,
                    google_pages_limit,
                    google_allowed_link_types # Utiliser la variable configurée
                )
                # --- Mettre à jour le statut après la recherche Google ---
                if job:
                    job.meta['progress'] = 10 # Exemple: 10% après la recherche
                    job.meta['status_message'] = f"{len(google_urls)} URLs trouvées par Google. Démarrage scraping détaillé..."
                    job.save_meta()
                # ---
                for item in google_urls:
                    item['Type_Source'] = 'Google'
                    if item.get('URL') and isinstance(item['URL'], str) and item['URL'] not in seen_urls_overall:
                        collected_urls_from_search.append(item)
                        seen_urls_overall.add(item['URL'])

                print(f"\nTotal URLs collectées via Google Search : {len(google_urls)}. Total URLs globales après Google : {len(collected_urls_from_search)}")
                time.sleep(random.uniform(1, 2))

                # Note: Les contrôles stop_scraping_full etc. ne sont pas gérés dans ce mode non interactif

        print("\n--- Fin des phases de recherche ---")
        print(f"Total d'URLs uniques collectées toutes sources confondues : {len(collected_urls_from_search)}")
        print("-------------------------------------")

        # --- 6. Scraping des Pages Détaillées ---
        final_detailed_prospects = []
        seen_urls_detailed_scraped = set()

        if collected_urls_from_search:
            print("\n--- Démarrage du scraping des pages détaillées ---")

            random.shuffle(collected_urls_from_search)
            print("URLs à scraper mélangées pour le scraping détaillé.")

            total_urls_to_scrape_detail = len(collected_urls_from_search)

            for idx, url_item in enumerate(collected_urls_from_search):
                # Note: Les contrôles stop_scraping_full / skip_url ne sont pas gérés ici

                url_to_scrape = url_item.get('URL')
                source_info = url_item

                if source_info.get('URL_Originale_Source') is None:
                    source_info['URL_Originale_Source'] = url_to_scrape

                if not url_to_scrape or url_to_scrape in seen_urls_detailed_scraped:
                    continue

                print(f"\n  [Main] Scraping détaillé {idx+1}/{total_urls_to_scrape_detail} : {url_to_scrape}")

                detailed_data = None

                try:
                    if "facebook.com" in url_to_scrape.lower() and facebook_page_scraper:
                        detailed_data = facebook_page_scraper.scrape_facebook_page(driver, url_to_scrape, source_info)

                    elif "instagram.com" in url_to_scrape.lower() and instagram_page_scraper:
                        detailed_data = instagram_page_scraper.scrape_instagram_page(driver, url_to_scrape, source_info)

                    else:
                        print(f"  [Main] Type d'URL non pris en charge par les scrapers spécifiques. Tentative AI pour : {url_to_scrape}")
                        detailed_data = extract_info_with_ai(driver, url_to_scrape, gemini_model_main, source_info)

                except Exception as e_page_scraper_call:
                    print(f"  [Main] ERREUR lors de l'appel du page scraper pour {url_to_scrape} : {type(e_page_scraper_call).__name__} - {e_page_scraper_call}")
                    if driver: # S'assurer que le driver existe
                         save_debug_info(driver, f"PageScraper_{type(e_page_scraper_call).__name__}", url_to_scrape)
                    detailed_data = {
                        "URL_Originale_Source": url_to_scrape,
                        "Statut_Scraping_Detail": "Error Calling Page Scraper",
                        "Message_Erreur_Detail": f"Error calling scraper: {type(e_page_scraper_call).__name__} - {e_page_scraper_call}"
                    }
                    # Ajouter les infos source au dictionnaire d'erreur
                    for key, value in source_info.items():
                        if key != 'URL' and key != 'URL_Originale_Source':
                            detailed_data[key] = source_info.get(key, "N/A")

                if detailed_data:
                    final_row_formatted = map_data_to_final_format(detailed_data)
                    final_detailed_prospects.append(final_row_formatted)
                    seen_urls_detailed_scraped.add(url_to_scrape)

                # --- Mettre à jour le statut APRÈS chaque tentative de scraping détaillé ---
                if job:
                    progress_percent = (idx + 1) * 85 // total_urls_to_scrape_detail + 10 # Progression de 10% à 95% pendant le détail
                    job.meta['progress'] = progress_percent
                    job.meta['status_message'] = f"Scraping détaillé {idx+1}/{total_urls_to_scrape_detail}: {url_to_scrape}"
                    job.save_meta()
                # ---

                time.sleep(random.uniform(3, 6))

            print(f"\n  [Main] {len(final_detailed_prospects)} URLs traitées pour le scraping détaillé et ajoutées à la liste finale.")
            print("\n--- Fin du scraping des pages détaillées ---")
            print(f"Total de prospects avec infos détaillées collectées : {len(final_detailed_prospects)}")
            print("---------------------------------------------")

        else:
            print("\nAucune URL collectée par les search scrapers. Skip la phase de scraping détaillé.")

        # --- 7. Sauvegarde Finale ---
        # Utilise le nom de base et les headers définis globalement (via config.py implicitement pour le nom)
        save_results_to_csv(final_detailed_prospects, config.BASE_FINAL_CSV_FILE_NAME, FINAL_CSV_HEADERS)

    except Exception as e:
        print(f"\nERREUR CRITIQUE GLOBALE dans main_scraper : {type(e).__name__} - {e}")
        traceback.print_exc()
        if driver: # S'assurer que le driver existe
            save_debug_info(driver, f"CRITICAL_{type(e).__name__}", "global_exception")
        # Important: Arrêter l'exécution ici si une erreur critique survient
        # Le finally s'exécutera quand même avant que la fonction ne retourne
        # --- Mettre à jour le statut en cas d'erreur critique ---
        if job:
            job.meta['progress'] = 100 # Marquer comme terminé même si erreur
            job.meta['status_message'] = f"ERREUR CRITIQUE: {type(e).__name__}"
            job.save_meta()
        # ---
        return # Ou raise e pour que RQ marque le job comme échoué

    finally:
        if driver:
            print("\nFermeture du navigateur...")
            try:
                # Vérifier si le processus du driver existe et n'est pas terminé
                if hasattr(driver, 'service') and driver.service.process and driver.service.process.poll() is None:
                    driver.quit()
                    print("Navigateur fermé.")
                else:
                    print("Navigateur déjà fermé ou processus introuvable.")
            except Exception as e_quit:
                print(f"Erreur lors de la fermeture du navigateur : {e_quit}")

        print("\n--- Processus de Scraping Terminé (dans la fonction) ---")

    # --- Mettre à jour le statut avant clean/extract ---
    if job:
        job.meta['progress'] = 95 # Presque terminé avant les étapes finales
        job.meta['status_message'] = "Scraping terminé. Lancement nettoyage/extraction..."
        job.save_meta()
    # ---

    # --- 9. Option de création de leads (après la fermeture du navigateur) ---
    if run_clean_option and clean:
        print("\n--- Création de Leads ---")
        # Assurez-vous que clean.consolidate_and_filter_leads utilise config.LEADS_CSV_FINAL_PATH
        if job: # Mettre à jour le statut pendant le nettoyage
             job.meta['status_message'] = "Nettoyage et consolidation des leads..."
             job.save_meta()
        # ---
        clean.consolidate_and_filter_leads()
    else:
        reason = "option désactivée" if not run_clean_option else "module clean.py non chargé"
        print(f"\nSkip l'option de création de leads ({reason}).")

    # --- 10. Option de mise à jour des listes extraites (après la fermeture du navigateur) ---
    # Utilise config.LEADS_CSV_FINAL_PATH
    if run_extract_option and extract_leads and config.LEADS_CSV_FINAL_PATH.exists():
        print("\n--- Mise à jour des Listes Extraites ---")
        try:
            print(f"Lancement de la mise à jour des listes depuis {config.LEADS_CSV_FINAL_PATH}...")
            if job: # Mettre à jour le statut pendant l'extraction
                 job.meta['status_message'] = "Extraction des listes (emails, téléphones...)..."
                 job.save_meta()
            # ---
            # Passe le chemin depuis config.py
            extract_leads.main(input_file_path=config.LEADS_CSV_FINAL_PATH)
        except Exception as e_extract:
            print(f"Erreur lors de la mise à jour des listes : {e_extract}")
            traceback.print_exc()
    else:
        reason = "option désactivée" if not run_extract_option else ("module extract_leads.py non chargé" if not extract_leads else f"fichier {config.LEADS_CSV_FINAL_PATH.name} introuvable")
        print(f"\nSkip l'option de mise à jour des listes ({reason}).")

    # --- Mettre à jour le statut final ---
    if job:
        job.meta['progress'] = 100
        job.meta['status_message'] = "Processus complet terminé."
        job.save_meta()
    # ---
    # Message final de la fonction
    print("\n--- Fonction run_full_scraping_process terminée ---")


# --- Bloc d'exécution pour le lancement direct en ligne de commande ---
if __name__ == "__main__":
    print("--- Lancement de main_scraper.py en mode autonome ---")

    # --- Récupérer les paramètres via input() pour le mode autonome ---
    keywords_input_lists_main = get_keywords_input_main()

    # --- Options Google ---
    google_pages_limit_main = 5
    while True:
        pages_limit_input = input(f"Combien de pages Google ? (Défaut: {google_pages_limit_main}) : ").strip()
        if not pages_limit_input: break
        try:
            limit = int(pages_limit_input)
            if limit > 0: google_pages_limit_main = limit; break
            else: print("Nombre positif requis.")
        except ValueError: print("Entrée invalide.")

    # --- Types de liens Google (basé sur modules dispo) ---
    google_allowed_link_types_main = []
    if facebook_page_scraper: google_allowed_link_types_main.append('facebook')
    if instagram_page_scraper: google_allowed_link_types_main.append('instagram')
    if not google_allowed_link_types_main: google_allowed_link_types_main = None

    # --- Options Clean / Extract ---
    run_clean_main = input("Exécuter le nettoyage/consolidation (clean.py) après ? (oui/non) : ").strip().lower() in ['oui', 'o', 'yes', 'y']
    run_extract_main = input("Exécuter l'extraction des listes (extract_leads.py) après ? (oui/non) : ").strip().lower() in ['oui', 'o', 'yes', 'y']

    # --- Démarrer le listener pour les commandes utilisateur (q, qq, s, u) ---
    # Note: Ce listener n'affectera pas l'exécution via RQ
    print("\nCommandes pendant la recherche Google : 'q'=arrêter recherche URLs, 's'=passer combinaison, 'qq'=arrêter tout")
    print("Commandes pendant le scraping détaillé : 'u'=passer URL, 'qq'=arrêter tout")
    input_thread = threading.Thread(target=user_input_listener, daemon=True)
    input_thread.start()

    input("\nAppuyez sur Entrée pour démarrer le processus de scraping autonome...")

    # --- Appeler la fonction principale avec les paramètres collectés ---
    run_full_scraping_process(
        keywords_input_lists=keywords_input_lists_main,
        google_pages_limit=google_pages_limit_main,
        google_allowed_link_types=google_allowed_link_types_main,
        run_clean_option=run_clean_main,
        run_extract_option=run_extract_main
    )

    # S'assurer que le script attend la fin du thread d'input si nécessaire (optionnel)
    # stop_scraping_full = True # Signaler la fin au thread d'input
    # input_thread.join(timeout=1) # Attendre brièvement que le thread se termine

    print("\n--- Fin du script autonome ---")
