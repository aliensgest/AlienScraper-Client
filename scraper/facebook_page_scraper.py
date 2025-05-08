# facebook_page_scraper.py

import time
import json
import os
import re
import random # Added for random sleeps
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException, StaleElementReferenceException
from urllib.parse import urlparse, parse_qs
import traceback

# --- Import Google Generative AI Library ---
import google.generativeai as genai
# Make sure GOOGLE_API_KEY environment variable is set for this to work
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # print("[Gemini API] Google API Key loaded from environment variable in FB scraper.") # Too verbose
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        # print("[Gemini API] Gemini 1.5 Flash model loaded in FB scraper.") # Too verbose
    except Exception as e:
        print(f"[FB Scraper - Gemini API] ERROR loading Gemini model: {e}")
        print("[FB Scraper - Gemini API] AI extraction will be skipped in FB scraper.")
        gemini_model = None
else:
    # print("[FB Scraper - Gemini API] WARNING: GOOGLE_API_KEY environment variable not set for FB scraper.") # Too verbose
    # print("[FB Scraper - Gemini API] AI extraction will be skipped in FB scraper.") # Too verbose
    gemini_model = None

# --- Define a local AI extraction function similar to Instagram's ---
def extract_info_with_gemini_fb(text):
    """
    Sends text to Google Gemini API to extract info specific to Facebook pages.
    Returns a dictionary with extracted info or None if an error occurs or model is not loaded.
    """
    if gemini_model is None:
        # print("[FB Scraper - Gemini API] Model not loaded, skipping AI extraction.") # Too verbose
        return None

    # Craft the prompt for the AI model - tailored for Facebook page info
    prompt = f"""
Analyze the following Facebook page text content. Extract the following information:
- Page Name
- Page Type (e.g., Restaurant, Service local, Magasin de vêtements)
- Phone Number(s)
- Email Address(es)
- Website URL(s) (excluding links that clearly point to facebook.com, fb.me, or wa.me)
- Instagram Profile URL(s)
- WhatsApp Link(s) (specifically wa.me links)
- Physical Address(es)
- A concise summary for the Bio/Description (excluding contact info, addresses, generic Facebook phrases like "J'aime", "followers", navigation links, footers).

Return the information in a JSON format with keys like "page_name", "page_type", "phones", "emails", "websites", "instagram_urls", "whatsapp_urls", "addresses", "bio_text". If a type of information is not found, use an empty list for lists or an empty string for text fields (use "Not Found" or "N/A" where appropriate).

Example desirable output format:
{{
  "page_name": "Restaurant XYZ",
  "page_type": "Restaurant",
  "phones": ["+1234567890", "0123456789"],
  "emails": ["contact@example.com"],
  "websites": ["https://www.example.com"],
  "instagram_urls": ["https://www.instagram.com/profil_xyz"],
  "whatsapp_urls": ["https://wa.me/1234567890"],
  "addresses": ["123 Main St, Anytown, CA 91234"],
  "bio_text": "Serving delicious food in a cozy atmosphere."
}}

Analyze the following text:

{text}
"""

    try:
        # Make the API call
        # Use a timeout for the API call in case of issues
        response = gemini_model.generate_content(prompt, request_options={'timeout': 45}) # Increased timeout slightly

        # Extract the text from the response
        response_text = response.text.strip()

        # The model should return JSON, attempt to parse it
        json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
        if json_match:
             json_string = json_match.group(0)
             try:
                 extracted_data = json.loads(json_string)
                 # print(f"[FB Scraper - Gemini API] Successfully extracted data: {extracted_data}") # Too verbose
                 return extracted_data
             except json.JSONDecodeError as json_e:
                 print(f"[FB Scraper - Gemini API] ERROR decoding JSON from AI response: {json_e}")
                 print(f"[FB Scraper - Gemini API] Raw AI response text: {response_text}")
                 return None
        else:
            print("[FB Scraper - Gemini API] WARNING: Could not find JSON object in AI response.")
            print(f"[FB Scraper - Gemini API] Raw AI response text: {response_text}")
            return None

    except Exception as e:
        print(f"[FB Scraper - Gemini API] ERROR during AI API call: {type(e).__name__} - {e}")
        return None


# --- Configuration (spécifique aux pages/connexion FB) ---
LOGIN_URL = "https://www.facebook.com/"
COOKIES_FILE = "facebook_cookies.json"

# --- Regex Definitions (copiées de votre script FB) ---
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX_TEXT_PARSING = re.compile(r'\b(?:\+?\d{1,4}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d+[\s.-]?\d+[\s.-]?\d+[\s.-]?\d*\b')
CLEAN_PHONE_REGEX = re.compile(r'[\s().-]')
WEBSITE_REGEX = re.compile(r'(https?://)?(www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(:\d+)?(\/\S*)?') # Refined Website Regex
ADDRESS_KEYWORDS = ["rue", "avenue", "boulevard", "quartier", "étage", "morocco", "maroc", "casa", "tétouan", "témara", "rabat", "street", "road", "district", "floor", "building", "immeuble", "app", "apt", "appartement", "résidence", "villa", "lot", "cite", "postal code", "code postal", "localisé", "situé"] # Added keywords
INSTAGRAM_REGEX_TEXT = re.compile(r'(?:https?://(?:www\.)?instagram\.com/([\w\.\-]+)(?:/?\b)|@([\w\-]+)\b)', re.IGNORECASE)
WHATSAPP_SPECIFIC_MASK_REGEX = re.compile(r'\+\d{1,4}\s\d{3}-\d{6}', re.IGNORECASE) # +Prefix NNN-NNNNNN
WHATSAPP_LINK_REGEX = re.compile(r'(?:https?://)?(?:api\.whatsapp\.com/send\/?\?phone=)?(?:wa\.me/)?([\d]+)', re.IGNORECASE)
PAGE_TYPE_TEXT_PATTERN = re.compile(r"Page\s*·\s*(.+)", re.IGNORECASE)
TRAILING_SPACE_REGEX = re.compile(r'[\s\xa0]+$') # \xa0 is the non-breaking space

# Regex pour vérifier si un nom extrait ressemble à un type générique
GENERIC_NAME_CHECK_REGEX = re.compile(r'^\s*(?:(?:Photo de profil de|Page|Restaurant|Café|Marocain|Hamburgers|followers|J’aime|avis|\d+\.?\d*\s*km|Actuellement ouvert|Notifications|Guide|Boutique|Magasin)[\s\.\-\·]*)+$', re.IGNORECASE) # Added more generic terms


# --- Fonctions de Gestion de Connexion et Cookies (FB) ---

def save_facebook_cookies(driver, filename=COOKIES_FILE):
    # print(f"  [FB Page Scraper - Login] Saving cookies to {filename}...") # Too verbose
    try:
        with open(filename, 'w') as f:
            cookies = driver.get_cookies()
            serializable_cookies = []
            for cookie in cookies:
                try:
                    # Ensure cookie is serializable by removing non-standard/problematic keys
                    if 'expiry' in cookie and not isinstance(cookie['expiry'], (int, float, type(None))):
                        del cookie['expiry']
                    # samesite can cause issues when adding cookies later
                    if 'samesite' in cookie:
                        del cookie['samesite']
                    # domain should be a string
                    if 'domain' in cookie and not isinstance(cookie['domain'], str):
                         del cookie['domain']

                    # Only add if it has essential keys
                    if 'name' in cookie and 'value' in cookie:
                         serializable_cookies.append(cookie)
                    else:
                         # print(f"    [FB Page Scraper - Login] Skipping cookie with missing name/value: {cookie}") # Too verbose
                         pass

                except Exception as e_cookie:
                    print(f"    [FB Page Scraper - Login] Error processing cookie {cookie.get('name', 'N/A')}: {e_cookie}")
                    pass # Skip this specific cookie


            json.dump(serializable_cookies, f, indent=4) # Use indent for readability
        # print("  [FB Page Scraper - Login] Cookies sauvegardés.") # Too verbose
    except Exception as e:
        print(f"  [FB Page Scraper - Login] Erreur lors de la sauvegarde des cookies : {e}")

def load_facebook_cookies(driver, filename=COOKIES_FILE):
    # print(f"  [FB Page Scraper - Login] Chargement des cookies depuis {filename}...") # Too verbose
    try:
        if not os.path.exists(filename):
            # print(f"  [FB Page Scraper - Login] Fichier de cookies '{filename}' non trouvé.") # Too verbose
            return False
        with open(filename, 'r') as f:
            cookies = json.load(f)
            # Important: Navigate to the domain before adding cookies
            driver.get("https://www.facebook.com/")
            time.sleep(2) # Give it a moment to load the base page
            for cookie in cookies:
                 try:
                     # Build the cookie dictionary, ensuring valid keys and types
                     cookie_dict = {}
                     # List essential keys that are generally required by add_cookie
                     essential_keys = ['name', 'value', 'path', 'domain', 'secure', 'expiry', 'httpOnly', 'isSecure']
                     for key in essential_keys:
                         # Check if key exists and value is not None
                         if key in cookie and cookie[key] is not None:
                             # Handle potential type issues, e.g., expiry needs to be int or float
                             if key == 'expiry' and not isinstance(cookie[key], (int, float)):
                                 # Try converting string expiry to int/float if needed, or skip
                                 try:
                                      cookie_dict[key] = int(cookie[key])
                                 except (ValueError, TypeError):
                                      # print(f"    [FB Page Scraper - Login] Skipping non-numeric expiry for cookie {cookie.get('name', 'N/A')}.") # Too verbose
                                      continue # Skip this cookie if expiry is invalid
                             # Handle domain: it must be a string
                             elif key == 'domain' and not isinstance(cookie[key], str):
                                  # print(f"    [FB Page Scraper - Login] Skipping non-string domain for cookie {cookie.get('name', 'N/A')}.") # Too verbose
                                  continue # Skip if domain is invalid type
                             # Handle boolean values, sometimes represented as strings "True"/"False"
                             elif key in ['secure', 'httpOnly', 'isSecure'] and isinstance(cookie[key], str):
                                 cookie_dict[key] = cookie[key].lower() == 'true' # Convert "True"/"False" string to boolean
                             else:
                                 cookie_dict[key] = cookie[key] # Add other keys directly

                     # Ensure domain is valid for adding by Selenium
                     # Selenium can be picky about the domain, especially with undetected_chromedriver
                     # If domain is missing or looks invalid, try setting a common valid one
                     if 'domain' not in cookie_dict or not cookie_dict['domain'] or '.facebook.com' not in cookie_dict['domain']:
                          cookie_dict['domain'] = '.facebook.com' # Force a valid domain

                     # Ensure essential keys are present after processing
                     if 'name' in cookie_dict and 'value' in cookie_dict and 'domain' in cookie_dict:
                          driver.add_cookie(cookie_dict)
                     else:
                         # print(f"    [FB Page Scraper - Login] Skipping cookie {cookie.get('name', 'N/A')} due to missing essential data after cleaning: {cookie_dict}") # Too verbose
                         pass


                 except Exception as e:
                     print(f"    [FB Page Scraper - Login] Erreur critique lors de l'ajout d'un cookie {cookie.get('name', 'N/A')} : {e}")
                     # traceback.print_exc() # Décommenter pour voir la pile d'appels d'erreur cookie
                     pass # Continue with next cookie


            # print("  [FB Page Scraper - Login] Cookies chargés.") # Too verbose
            driver.refresh() # Refresh after adding cookies to apply them
            # print("  [FB Page Scraper - Login] Page actualisée après chargement des cookies.") # Too verbose
            time.sleep(3) # Give time for the page to load after refresh
            return True
    except FileNotFoundError:
        # print(f"  [FB Page Scraper - Login] Fichier de cookies '{filename}' non trouvé.") # Too verbose
        return False
    except json.JSONDecodeError:
        print(f"  [FB Page Scraper - Login] Erreur de lecture du fichier JSON de cookies '{filename}'. Assurez-vous qu'il est au format JSON valide.")
        return False
    except Exception as e:
        print(f"  [FB Page Scraper - Login] Erreur lors du chargement ou de l'ajout des cookies : {e}")
        traceback.print_exc()
        return False

def is_facebook_logged_in(driver):
    print("  [FB Page Scraper - Login] Vérification de la session Facebook active...")
    try:
        # Navigate to a standard post-login page if not already there or if on a login page
        current_url = driver.current_url
        # Add checks for common login/checkpoint urls
        if "facebook.com" not in current_url or "login" in current_url.lower() or "checkpoint" in current_url.lower() or "recover" in current_url.lower():
             print("  [FB Page Scraper - Login] Not on a standard Facebook page or on a login/checkpoint page, navigating to home...")
             driver.get("https://www.facebook.com/")
             time.sleep(3) # Give it time to redirect or load

        # Look for elements consistently present AFTER login (like the search bar, main feed, or navigation menu)
        # Use a more robust set of selectors for post-login indicators
        WebDriverWait(driver, 20).until(
             EC.visibility_of_any_elements_located((
                  By.CSS_SELECTOR, '[aria-label="Rechercher sur Facebook"], [aria-label="Search Facebook"], ' # Search bar
                  'div[role="feed"], ' # Main feed
                  'div[role="navigation"], ' # Main navigation area
                  'div[aria-label="Accueil"], ' # Home button/link on the left nav
                  'div[data-visualcompletion="loading-state"]' # Look for loading indicators that disappear
             ))
        )

        # Wait for loading indicators to disappear as a sign of page readiness
        try:
             WebDriverWait(driver, 5).until_not(
                  EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-visualcompletion="loading-state"]'))
             )
        except TimeoutException:
             print("  [FB Page Scraper - Login] Loading indicator still present after waiting.")
             pass # Continue anyway, maybe it's a slow load


        # After waiting for elements, re-check the URL to be absolutely sure
        current_url_after_wait = driver.current_url
        if "login" in current_url_after_wait.lower() or "checkpoint" in current_url_after_wait.lower() or "recover" in current_url_after_wait.lower():
             print("  [FB Page Scraper - Login] Still on login or checkpoint page after waiting. Session non active.")
             return False


        print("  [FB Page Scraper - Login] Session Facebook active détectée.")
        return True
    except TimeoutException:
        print("  [FB Page Scraper - Login] Session Facebook non active détectée (Timeout waiting for post-login elements).")
        return False
    except Exception as e:
        print(f"  [FB Page Scraper - Login] Erreur lors de la vérification de la session Facebook : {type(e).__name__} - {e}")
        # Un dernier contrôle par URL en cas d'erreur inattendue
        current_url = driver.current_url
        if "login" in current_url.lower() or "checkpoint" in current_url.lower() or "recover" in current_url.lower():
             print("  [FB Page Scraper - Login] Currently on login or checkpoint page based on URL after error. Session non active.")
             return False
        print("  [FB Page Scraper - Login] Impossible de déterminer l'état de la session FB suite à une erreur.")
        return False


def manual_facebook_login(driver, cookies_filename=COOKIES_FILE):
    """Guide l'utilisateur pour se connecter manuellement à Facebook et sauvegarde les cookies."""
    print("\n--- Connexion Manuelle à Facebook ---")
    print("Session Facebook non active. Veuillez vous connecter manuellement dans la fenêtre du navigateur qui s'est ouverte.")
    driver.get(LOGIN_URL)
    input("Appuyez sur Entrée APRÈS vous être connecté manuellement et que vous voyez votre fil d'actualité ou page d'accueil...")

    try:
        if is_facebook_logged_in(driver):
             print("  [FB Page Scraper - Login] Connexion manuelle réussie détectée. Sauvegarde des cookies.")
             save_facebook_cookies(driver, cookies_filename)
             return True
        else:
             print("  [FB Page Scraper - Login] Échec de la détection de l'interface post-connexion après la connexion manuelle.")
             return False
    except Exception as e:
        print(f"  [FB Page Scraper - Login] Erreur lors de la vérification ou sauvegarde après connexion manuelle : {e}")
        traceback.print_exc()
        return False


def ensure_facebook_login(driver, cookies_filename=COOKIES_FILE):
    """
    Charge les cookies FB, vérifie la session. Si non connecté, demande la connexion manuelle.
    Retourne True si la session est active (après chargement/vérification ou connexion manuelle réussie), False sinon.
    """
    print("  [FB Page Scraper - Login] Assurer la connexion Facebook...")
    session_active = False
    # Try loading cookies first
    if load_facebook_cookies(driver, cookies_filename):
         # If cookies loaded, check if session is active
         session_active = is_facebook_logged_in(driver)
         if session_active:
              print("  [FB Page Scraper - Login] Session active après chargement des cookies.")
              return True # Logged in via cookies
         else:
              print("  [FB Page Scraper - Login] Cookies chargés mais session non active. Connexion manuelle nécessaire.")
    else:
         print("  [FB Page Scraper - Login] Aucun cookie à charger ou erreur de chargement. Connexion manuelle nécessaire.")

    # If session is not active after trying cookies, proceed to manual login
    if not session_active:
        print("  [FB Page Scraper - Login] Procédure de connexion manuelle lancée.")
        session_active = manual_facebook_login(driver, cookies_filename)

    if not session_active:
        print("  [FB Page Scraper - Login] Impossible d'établir une session Facebook active après tentatives.")

    return session_active


def go_to_facebook_home(driver):
    """Navigue vers la page d'accueil de Facebook (utilisé par les search/page scrapers si besoin)."""
    try:
        driver.get("https://www.facebook.com/")
        # Attendre un élément de la page d'accueil FB si nécessaire
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Rechercher sur Facebook"], [aria-label="Search Facebook"]')))
        # print("  [FB Page Scraper - Nav] Navigué vers Facebook Home.") # Too verbose
        return True
    except Exception as e:
        print(f"  [FB Page Scraper - Nav] Erreur lors de la navigation vers Facebook Home : {e}")
        return False


# --- Fonctions de Scraping de Pages Détaillées ---

def scrape_facebook_page(driver, page_url, source_info=None):
    """
    Scrape les informations détaillées d'une seule page Facebook.
    Prend l'instance du driver, l'URL de la page, et des infos source optionnelles ({'source_keyword': ..., 'name_from_search': ..., 'Titre_Google': ..., 'Type_Lien_Google': ...}).
    Utilise AI pour extraire les informations de contact, type, adresse, et bio du texte.
    Retourne un dictionnaire contenant les informations extraites.
    """
    print(f"\n  [FB Page Scraper] Scraping info pour URL: {page_url}")

    # Définir les clés du dictionnaire de retour
    # Inclure les champs potentiellement utiles provenant de la recherche Google/FB
    # Ces champs seront ajoutés au dictionnaire de retour si source_info est fourni
    detailed_info = {
        # Champs standard du scraping de page FB
        "URL": page_url, # L'URL réelle de la page scrapée
        "Nom de la Page": "Not Found",
        "Type de Page": "Not Found",
        "Téléphone": "Not Found",
        "Email": "Not Found",
        "Site Web": "Not Found",
        "Adresse": "Not Found",
        "Instagram": "Not Found",
        "WhatsApp": "Not Found",
        "WhatsApp à vérifier": "Not Generated", # This is now generated in main_scraper, but kept for FB scraper fallback

        # Placeholder pour champs Instagram si on utilise ce module pour Insta (mais on aura un module Insta dédié)
        "Nom d'Utilisateur": "N/A (FB)",
        "Nom Complet": "N/A (FB)",
        "Nombre de Publications": "N/A (FB)",
        "Nombre de Followers": "N/A (FB)",
        "Nombre de Suivis": "N/A (FB)",
        "Site Web (Bio)": "N/A (FB)", # Use Site Web field for website from FB
        "Bio": "Not Found", # Use Bio field for description from FB

        "Statut_Scraping_Detail": "Attempting", # Statut du scraping détaillé
        "Message_Erreur_Detail": "", # Message d'erreur spécifique si scraping échoue
        "Full Intro/About Text (from container)": "Not Found (Container not found)" # For debugging/verification
    }

    # Ajouter les infos source passées en paramètre au dictionnaire
    if source_info:
        # On ajoute les clés si elles existent dans source_info, en évitant d'écraser 'URL'
        for key, value in source_info.items():
             if key not in ['URL', 'Statut_Scraping_Detail', 'Message_Erreur_Detail', 'Facebook']: # Don't overwrite key fields
                 # Use .get() to avoid KeyError if a key is missing in source_info
                 # Only copy if our field is default or None/empty
                  if detailed_info.get(key) in ["Not Found", "N/A", "N/A (Insta)", "N/A (FB)", "Not Generated", "", None]:
                       detailed_info[key] = source_info.get(key, "N/A")
        # print(f"    [FB Page Scraper] Added source info: {source_info}") # Too verbose


    # Check if the URL looks like a specific post or photo instead of a main page
    # This is a heuristic check based on common Facebook URL patterns
    parsed_url_check = urlparse(page_url)
    path_check = parsed_url_check.path.strip('/').lower()
    # Check for common post/photo/video indicators and patterns that aren't typical pages
    if any(segment in path_check for segment in ['posts', 'photos', 'videos', 'media']) or \
       path_check.startswith('photo.php') or path_check.startswith('video.php') or \
       re.search(r'fbid=\d+|story_fbid=\d+|v=\d+', parsed_url_check.query.lower()):

       print(f"  [FB Page Scraper] Skipping scraping info for URL that looks like a specific post/photo: {page_url}")
       detailed_info["Statut_Scraping_Detail"] = "Skipped - Looks like Post/Photo URL"
       detailed_info["Message_Erreur_Detail"] = "URL identified as a post/photo, not a main page."
       return detailed_info # Exit function early, keep "Not Found" for most fields


    intro_block_text = ""
    full_page_text = "" # Will store text from a broader area if intro block fails
    page_container_element = None

    try: # TRY block for navigating to and scraping a single page
        # Naviguer vers la page. Ajouter une petite pause avant.
        time.sleep(random.uniform(2, 4))
        driver.get(page_url)

        # --- Robust Wait for Page Load and Anti-detection checks ---
        try:
            # Attente séquentielle pour les deux conditions et d'autres indicateurs de page chargée
            WebDriverWait(driver, 25).until( # Increased wait time
                 EC.visibility_of_any_elements_located((
                      By.CSS_SELECTOR, 'div[role="main"], div[id="pagelet_timeline_profile_content"], [data-testid="profile_cover_photo"], ' # Main page elements
                      '[aria-label="Facebook"], [aria-label="Accueil"]' # Elements that appear after loading
                 ))
            )
             # Wait for loading indicators to disappear
            try:
                WebDriverWait(driver, 5).until_not(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-visualcompletion="loading-state"]'))
                )
            except TimeoutException:
                # print("  [FB Page Scraper] Loading indicator still present after waiting.") # Too verbose
                pass # Continue anyway

            # Final check if the URL redirected to a problematic page AFTER waiting
            current_url_after_wait = driver.current_url
            if "login" in current_url_after_wait.lower() or "checkpoint" in current_url_after_wait.lower() or "notifications" in current_url_after_wait.lower() or "recover" in current_url_after_wait.lower():
                 print(f"  [FB Page Scraper] Warning: Loaded URL looks like a redirect/error page AFTER WAIT: {current_url_after_wait}. Skipping scraping info.")
                 detailed_info["Statut_Scraping_Detail"] = "Redirected to login/checkpoint/error page"
                 detailed_info["Message_Erreur_Detail"] = f"Redirected to {current_url_after_wait} after wait"
                 # On met à jour l'URL dans detailed_info au cas où la redirection a changé l'URL
                 detailed_info["URL"] = current_url_after_wait
                 return detailed_info # Exit function early


        except TimeoutException:
            print(f"  [FB Page Scraper] Timeout waiting for elements or URL check for {page_url}.")
            detailed_info["Statut_Scraping_Detail"] = "Timeout loading page elements"
            detailed_info["Message_Erreur_Detail"] = "Timeout on initial wait for page elements."
            # We still let the function proceed to attempt extraction from whatever loaded.
        except Exception as e_wait:
             print(f"  [FB Page Scraper] Error during initial page wait on {page_url}: {type(e_wait).__name__} - {e_wait}")
             detailed_info["Statut_Scraping_Detail"] = "Error loading page elements"
             detailed_info["Message_Erreur_Detail"] = f"Error on initial wait: {type(e_wait).__name__}"
             # Continue even if wait fails

        # --- Attempt to extract Page Name from the Loaded Page ---
        # Do this early as it's a key piece of information
        try:
            page_name = "Not Found"
            h1_elements = driver.find_elements(By.TAG_NAME, 'h1')
            found_h1_name = False
            for h1_element in h1_elements:
                 if h1_element.is_displayed():
                      try:
                           js_text = driver.execute_script("return arguments[0].textContent;", h1_element).strip()
                           cleaned_js_text = TRAILING_SPACE_REGEX.sub('', js_text)
                           # Improved check for generic H1s
                           if cleaned_js_text and cleaned_js_text != "Gérer la Page" and "Facebook" not in cleaned_js_text and not GENERIC_NAME_CHECK_REGEX.match(cleaned_js_text) and len(cleaned_js_text) > 2:
                                page_name = cleaned_js_text
                                found_h1_name = True
                                break
                      except Exception: pass # Ignore errors with this specific H1 element

            if not found_h1_name:
                 # Fallback to title if no good H1 is found
                 title_name = driver.title.replace(" - Facebook", "").strip()
                 if title_name and title_name != "(2) Facebook" and not title_name.startswith("Loading") and "Facebook" not in title_name and not GENERIC_NAME_CHECK_REGEX.match(title_name) and len(title_name) > 2:
                      page_name = title_name
                 # Further fallback: check meta og:title tag
                 if page_name == "Not Found":
                      try:
                           og_title_element = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
                           og_title_content = og_title_element.get_attribute('content').strip()
                           if og_title_content and og_title_content != "Facebook" and not GENERIC_NAME_CHECK_REGEX.match(og_title_content) and len(og_title_content) > 2:
                                page_name = og_title_content
                      except NoSuchElementException:
                           pass # og:title meta tag not found
                      except Exception:
                           pass # Other error getting og:title


        except Exception as e_name:
             print(f"    [FB Page Scraper] Error during Page Name extraction attempts: {type(e_name).__name__} - {e_name}")
             detailed_info["Message_Erreur_Detail"] += f"; Name extraction error: {type(e_name).__name__}"

        detailed_info["Nom de la Page"] = page_name


        # --- Attempt to extract text from Intro/About block ---
        # Try to find a reliable container for the "Intro" or "About" section
        try:
             # More robust selectors for the intro/about block
             intro_container = WebDriverWait(driver, 10).until(
                  EC.presence_of_element_located((By.CSS_SELECTOR,
                       'div[data-pagelet="ProfileTimeline"] div[role="region"][aria-label*="Intro"], '
                       'div[data-pagelet="ProfileTimeline"] div[role="region"][aria-label*="About"], '
                       'div[data-pagelet="ProfileTimeline"] div[data-testid="profile_card_block"], '
                       'div[data-pagelet="ProfileTimeline"] div.xieb3on, '
                       'div[data-pagelet="ProfileTimeline"] div[class*="profileInfo"], div[class*="aboutSection"], '
                       'div[role="main"] div[role="region"][aria-label*="Intro"], ' # Broader search
                       'div[role="main"] div[role="region"][aria-label*="About"]'
                  ))
             )
             intro_block_text = intro_container.text
             detailed_info["Full Intro/About Text (from container)"] = intro_block_text
             # print(f"    [FB Page Scraper] Extracted Intro/About text (partial display):\n--- Start Intro Text ---\n{intro_block_text[:500]}...\n--- End Intro Text ---")

        except (TimeoutException, NoSuchElementException) as e:
             print(f"  [FB Page Scraper] Intro/About container not found or changed ({type(e).__name__}). Attempting extraction from broader page text.")
             detailed_info["Message_Erreur_Detail"] += f"; Intro block not found: {type(e).__name__}"
             # Fallback: Capture text from a broader area if the specific intro block is missed
             try:
                  # Try to get text from the main content area role="main" or article
                  page_container_element = driver.find_element(By.CSS_SELECTOR, 'div[role="main"], article')
                  full_page_text = page_container_element.text
                  # print(f"    [FB Page Scraper] Extracted broader page text (partial display):\n--- Start Page Text ---\n{full_page_text[:500]}...\n--- End Page Text ---")
             except NoSuchElementException:
                  print("    [FB Page Scraper] Broader page container (role=main or article) also not found.")
                  detailed_info["Message_Erreur_Detail"] += "; Broader page container not found."
                  full_page_text = "" # Ensure it's an empty string if no container is found
             except Exception as e_broad_text:
                  print(f"    [FB Page Scraper] Error extracting broader page text: {type(e_broad_text).__name__}.")
                  detailed_info["Message_Erreur_Detail"] += f"; Broader text error: {type(e_broad_text).__name__}"
                  full_page_text = ""


        # --- Use the extracted text (Intro/About or Full Page) for AI and parsing ---
        text_to_process = intro_block_text if intro_block_text else full_page_text

        # --- Call AI for Extraction (if model is loaded and text is available) ---
        ai_extracted_data = None
        if gemini_model and text_to_process: # Only call AI if model loaded and text is available
             try:
                 print("    [FB Page Scraper] Sending text to AI for info extraction...")
                 ai_extracted_data = extract_info_with_gemini_fb(text_to_process)
                 if ai_extracted_data:
                      # print("    [FB Page Scraper] AI extraction successful.") # Too verbose
                      pass
                 else:
                      print("    [FB Page Scraper] AI extraction returned no data or failed internally.")
                      detailed_info["Message_Erreur_Detail"] += "; AI extraction returned no data."


             except Exception as ai_e:
                 print(f"    [FB Page Scraper] Error during AI extraction process: {type(ai_e).__name__} - {ai_e}")
                 detailed_info["Message_Erreur_Detail"] += f"; AI extraction error: {type(ai_e).__name__}"


        # === Integrate AI Results and Fallback to Regex Parsing ===

        # --- Integrate AI results (if available) ---
        if ai_extracted_data:
            # Page Name (Prioritize H1/Title/Meta, then AI)
            if detailed_info["Nom de la Page"] == "Not Found" and ai_extracted_data.get("page_name"):
                 ai_page_name = ai_extracted_data["page_name"].strip()
                 if ai_page_name and len(ai_page_name) > 1 and not GENERIC_NAME_CHECK_REGEX.match(ai_page_name):
                     detailed_info["Nom de la Page"] = ai_page_name

            # Page Type
            if ai_extracted_data.get("page_type"):
                 ai_page_type = ai_extracted_data["page_type"].strip()
                 if ai_page_type and len(ai_page_type) > 1 and not GENERIC_NAME_CHECK_REGEX.match(ai_page_type):
                      detailed_info["Type de Page"] = ai_page_type

            # Contact Info
            if ai_extracted_data.get("phones"):
                 detailed_info["Téléphone"] = ai_extracted_data["phones"][0] # Take the first phone

            if ai_extracted_data.get("emails"):
                 detailed_info["Email"] = ai_extracted_data["emails"][0] # Take the first email

            if ai_extracted_data.get("websites"):
                 ai_website = ai_extracted_data["websites"][0]
                 if ai_website and not any(domain in ai_website.lower() for domain in ["facebook.com", "fb.me", "wa.me"]):
                      detailed_info["Site Web"] = ai_website # Use Site Web field for the primary website

            # Social Media Links extracted by AI
            if ai_extracted_data.get("instagram_urls"):
                 detailed_info["Instagram"] = ai_extracted_data["instagram_urls"][0]

            if ai_extracted_data.get("whatsapp_urls"):
                 whatsapp_url_ai = ai_extracted_data["whatsapp_urls"][0]
                 if whatsapp_url_ai and "wa.me" in whatsapp_url_ai.lower():
                      detailed_info["WhatsApp"] = whatsapp_url_ai
                      # Update Téléphone from AI WhatsApp number if needed
                      wa_number_match = WHATSAPP_LINK_REGEX.search(detailed_info["WhatsApp"])
                      if wa_number_match:
                           wa_number_digits = CLEAN_PHONE_REGEX.sub('', wa_number_match.group(1))
                           current_phone_digits = CLEAN_PHONE_REGEX.sub('', detailed_info.get("Téléphone", ""))

                           if detailed_info["Téléphone"] == "Not Found" or (wa_number_digits and len(wa_number_digits) > len(current_phone_digits)):
                                detailed_info["Téléphone"] = wa_number_digits

            # Address
            if ai_extracted_data.get("addresses"):
                 detailed_info["Adresse"] = ai_extracted_data["addresses"][0] # Take the first address

            # Bio/Description
            if ai_extracted_data.get("bio_text"):
                 detailed_info["Bio"] = ai_extracted_data["bio_text"]

        else: # AI extraction failed or gemini_model is None
             # print("    [FB Page Scraper] AI extraction failed or not used. Falling back to regex parsing.") # Already logged

            # === Fallback to Regex Parsing (if AI failed or not used) ===
            # This logic remains as a safety net if AI fails to extract certain fields from the text.
            # Note: Page Name is handled *before* the AI call and its fallbacks are kept.

            # Page Type (Fallback if AI didn't find it)
            if detailed_info["Type de Page"] == "Not Found":
                 page_type_match = PAGE_TYPE_TEXT_PATTERN.search(text_to_process)
                 if page_type_match:
                     detailed_info["Type de Page"] = page_type_match.group(1).strip()

            # Email Extraction (Fallback if AI didn't find it)
            if detailed_info["Email"] == "Not Found":
                 email_match = EMAIL_REGEX.search(text_to_process)
                 if email_match:
                     detailed_info["Email"] = email_match.group(0)

            # Phone Extraction (Fallback if AI didn't find it)
            if detailed_info["Téléphone"] == "Not Found":
                 phone_matches = PHONE_REGEX_TEXT_PARSING.findall(text_to_process)
                 found_phone_fallback = "Not Found"
                 for raw_phone in phone_matches:
                      cleaned_phone = CLEAN_PHONE_REGEX.sub('', raw_phone)
                      if sum(c.isdigit() for c in cleaned_phone) >= 7: # Basic validation
                          if found_phone_fallback == "Not Found" or len(cleaned_phone) > len(CLEAN_PHONE_REGEX.sub('', found_phone_fallback)):
                               found_phone_fallback = cleaned_phone # Keep the longest/most complete number found
                 if found_phone_fallback != "Not Found":
                      detailed_info["Téléphone"] = found_phone_fallback

            # WhatsApp Link Extraction (Fallback if AI didn't find it)
            if detailed_info["WhatsApp"] == "Not Found":
                 whatsapp_link_match = WHATSAPP_LINK_REGEX.search(text_to_process)
                 if whatsapp_link_match:
                      whatsapp_url = whatsapp_link_match.group(0)
                      wa_number_raw = whatsapp_link_match.group(1) # Keep raw to handle formatting later
                      detailed_info["WhatsApp"] = whatsapp_url
                      # Update Téléphone from WhatsApp number if not found or shorter
                      current_phone_digits = CLEAN_PHONE_REGEX.sub('', detailed_info.get("Téléphone", ""))
                      wa_number_digits = CLEAN_PHONE_REGEX.sub('', wa_number_raw) # Clean digits for comparison and storage
                      if detailed_info["Téléphone"] == "Not Found" or (wa_number_digits and len(wa_number_digits) > len(current_phone_digits)):
                           detailed_info["Téléphone"] = wa_number_digits

            # Website Extraction (Fallback if AI didn't find it)
            if detailed_info["Site Web"] == "Not Found":
                 website_match = WEBSITE_REGEX.search(text_to_process)
                 if website_match:
                      # Double check if it's a valid domain and not a social media link
                      matched_url = website_match.group(0)
                      if matched_url and not any(domain in matched_url.lower() for domain in ["facebook.com", "fb.me", "wa.me", "instagram.com"]):
                            detailed_info["Site Web"] = matched_url


            # Instagram Link Extraction (Fallback if AI didn't find it)
            if detailed_info["Instagram"] == "Not Found":
                 insta_match = INSTAGRAM_REGEX_TEXT.search(text_to_process)
                 if insta_match:
                     username = insta_match.group(1) if insta_match.group(1) else insta_match.group(2)
                     if username and 1 < len(username) <= 30 and re.fullmatch(r'[\w\.\-]+', username):
                          detailed_info["Instagram"] = f"https://www.instagram.com/{username}/"

            # Address Extraction (Fallback if AI didn't find it) - Use the heuristic line-by-line logic
            if detailed_info["Adresse"] == "Not Found":
                 lines_fallback = text_to_process.splitlines()
                 lines_fallback = [line.strip() for line in lines_fallback if line.strip()]

                 for line in lines_fallback:
                      line_lower = line.lower()
                      # Simple heuristic check
                      looks_like_address_part = (
                           any(keyword in line_lower for keyword in ADDRESS_KEYWORDS) or
                           re.search(r'\b\d+,?\s*(?:rue|av(?:enue)?|boul(?:evard)?|st(?:street)?|rd|road|quar(?:tier)?|immeuble|building|app|apt|appartement|résidence|villa|lot|cite)\b', line_lower) or # Added \b word boundaries
                           re.search(r'\b\d{5,}\b', line_lower) # Check for postal codes
                      )

                      # Add more checks to exclude non-address lines that might contain keywords
                      is_likely_address = False
                      if looks_like_address_part and 10 <= len(line) < 200: # Increased max length slightly
                           # Exclude lines that look like phone numbers or simple generic phrases
                           if not (len(CLEAN_PHONE_REGEX.sub('', line)) >= 7 and re.fullmatch(r'\d+', CLEAN_PHONE_REGEX.sub('', line))): # Exclude clear phone numbers
                                if not GENERIC_NAME_CHECK_REGEX.match(line_lower) and "J'aime" not in line and "followers" not in line: # Exclude some generic FB phrases
                                     is_likely_address = True

                      if is_likely_address:
                            detailed_info["Adresse"] = line
                            break # Take the first plausible address line


            # Bio Text Inference (Fallback if AI didn't find it) - Reusing the logic from Instagram for now, might need FB specific tuning later
            if detailed_info["Bio"] == "Not Found":
                 # For Facebook, the text content is less structured than Instagram's bio field.
                 # Relying solely on text parsing for a coherent 'Bio' might be difficult.
                 # Let's keep it simple for now and rely on AI, or just mark as Not Found if AI fails.
                 pass # No regex fallback for Bio for now, rely on AI.


        # --- Reintroduce WhatsApp to Verify generation (Fallback logic) ---
        # If a phone number was found (by AI or fallback regex) AND no direct WhatsApp link was found (by AI or fallback regex)
        if detailed_info["Téléphone"] != "Not Found" and detailed_info["WhatsApp"] == "Not Found":
            try:
                cleaned_phone_for_whatsapp_verifier = CLEAN_PHONE_REGEX.sub('', detailed_info["Téléphone"])
                if len(cleaned_phone_for_whatsapp_verifier) >= 6 and re.fullmatch(r'\d+', cleaned_phone_for_whatsapp_verifier):
                     # Note: This will generate a simple wa.me link. The formatting to +212 will happen in main_scraper.py
                     detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp_verifier}"
                     # print(f"    [FB Page Scraper] Generated fallback WhatsApp link (to verify): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                else:
                     detailed_info["WhatsApp à vérifier"] = "Invalid Phone Format for WhatsApp"
            except Exception as e:
                detailed_info["WhatsApp à vérifier"] = f"Error Generating: {e}"
                detailed_info["Message_Erreur_Detail"] += f"; WhatsApp verifier gen error: {type(e).__name__}"


        # If we reached here, the scraping attempt was successful (even if no data was found)
        if detailed_info["Statut_Scraping_Detail"] == "Attempting":
             detailed_info["Statut_Scraping_Detail"] = "Success"

        # print(f"  [FB Page Scraper] Scraping terminé pour {page_url}. Statut: {detailed_info['Statut_Scraping_Detail']}. Nom trouvé: {detailed_info['Nom de la Page']}") # Too verbose


    except Exception as e: # Catch any other unexpected error during the process
         print(f"  [FB Page Scraper] Une erreur inattendue s'est produite lors du scraping de {page_url}: {type(e).__name__} - {e}")
         detailed_info["Statut_Scraping_Detail"] = f"Unexpected Error: {type(e).__name__}"
         detailed_info["Message_Erreur_Detail"] = f"Overall error: {type(e).__name__} - {e}"
         traceback.print_exc() # Keep traceback for unexpected errors

    # Ensure all fields have a value, even if "Not Found"
    for key in detailed_info.keys():
         if detailed_info.get(key) is None or detailed_info.get(key) == "": # Also check for empty string
             # Set defaults based on the field type and expected values
             if key in ["Nom de la Page", "Type de Page", "Téléphone", "Email", "Site Web", "Adresse", "Instagram", "WhatsApp", "Bio"]:
                  detailed_info[key] = "Not Found"
             # Preserve N/A for fields specific to other platforms
             elif key in ["Nom d'Utilisateur", "Nom Complet", "Nombre de Publications", "Nombre de Followers", "Nombre de Suivis", "Site Web (Bio)"]:
                  pass # Keep default N/A (FB)
             elif key == "WhatsApp à vérifier":
                  # Keep "Not Generated" or "Invalid..." if set, otherwise default to "Not Generated"
                  if detailed_info.get(key) is None or detailed_info.get(key) == "":
                       detailed_info[key] = "Not Generated"
             elif key == "Statut_Scraping_Detail":
                 # If it's already an error, keep it. Otherwise, mark as success if not explicitly set.
                 if detailed_info[key] == "Attempting":
                     detailed_info[key] = "Completed" # Page was processed, even if data is missing
             # Message_Erreur_Detail should not be overwritten if an error occurred
             # Full Intro/About Text (from container) default is handled on creation

    # Final check to set default status if it's still "Attempting" and no error occurred
    if detailed_info["Statut_Scraping_Detail"] == "Attempting":
         # If we reached here, it means the initial wait succeeded, but maybe container wasn't found or other issues.
        if detailed_info["Message_Erreur_Detail"] and "Intro block not found" in detailed_info["Message_Erreur_Detail"]:
             # Status is already set to Error/Critical Element Not Found
             detailed_info["Statut_Scraping_Detail"] = "Partial Success - Intro Block Not Found"
        else:
             # Page loaded, but maybe no data was found. Mark as Completed.
             detailed_info["Statut_Scraping_Detail"] = "Completed"


    return detailed_info

# --- Bloc d'exécution autonome (Optionnel pour tester ce script seul) ---
# if __name__ == "__main__":
#      print("Exécution de facebook_page_scraper.py en mode autonome (pour test).")
#      # Ce test nécessite un navigateur et une connexion FB
#
#      # Simulation d'une URL FB à scraper
#      test_url_fb = input("Entrez une URL de page Facebook à tester (ou laissez vide pour skipper) : ").strip()
#
#      if not test_url_fb:
#           print("Aucune URL fournie pour le test. Fin.")
#           sys.exit(0)
#      elif "facebook.com" not in test_url_fb.lower():
#          print("L'URL ne semble pas être une URL Facebook valide. Fin.")
#          sys.exit(0)
#
#      driver_test = None
#      try:
#           from selenium.webdriver.chrome.service import Service
#           from selenium.webdriver.chrome.options import Options
#
#           options = Options()
#           # options.add_argument("--headless") # Uncomment for headless mode
#           options.add_argument("--no-sandbox")
#           options.add_argument("--disable-dev-shm-usage")
#           options.add_argument("--window-size=1920,1080")
#           options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36")
#           options.add_argument("--lang=fr") # Set language to French for Facebook
#
#           # Utiliser undetected_chromedriver pour le test car les pages FB peuvent le nécessiter
#           if uc: # Check if undetected_chromedriver was imported successfully
#               try:
#                    driver_test = uc.Chrome(options=options)
#                    print("Navigateur Chrome furtif initialisé pour test FB Page Scraper.")
#               except Exception as uc_error:
#                    print(f"Could not initialize undetected_chromedriver: {uc_error}. Falling back to standard Chrome.")
#                    # Fallback to standard Chrome if uc fails
#                    service = Service()
#                    driver_test = webdriver.Chrome(service=service, options=options)
#                    print("Navigateur Chrome standard initialisé pour test FB Page Scraper (Fallback).")
#           else:
#               # Fallback if uc module was not imported at all
#               from selenium.webdriver.chrome.service import Service
#               service = Service()
#               driver_test = webdriver.Chrome(service=service, options=options)
#               print("Navigateur Chrome standard initialisé pour test FB Page Scraper (No uc module).")
#
#           if driver_test:
#                # Tenter d'assurer la connexion FB
#                session_ok = ensure_facebook_login(driver_test)
#
#                if session_ok:
#                     print("\n--- Test scraping page Facebook ---")
#                     # Simuler des infos source
#                     source_info_fb = {'source_keyword': 'test-keyword', 'Nom_Trouve_Recherche': 'Test Page Name', 'Titre_Trouve_Google': 'Test Google Title', 'Type_Lien_Google': 'Facebook', 'URL_Originale_Source': test_url_fb}
#                     fb_data = scrape_facebook_page(driver_test, test_url_fb, source_info_fb)
#                     print("\nRésultats Scraping FB :")
#                     # Sort keys alphabetically for consistent output (optional)
#                     for key in sorted(fb_data.keys()):
#                          print(f"- {key}: {fb_data[key]}")
#
#                else:
#                     print("\nSkip test scraping page Facebook car la connexion a échoué.")
#
#      except Exception as e:
#           print(f"\nERREUR LORS DU TEST AUTONOME FB PAGE SCRAPER : {type(e).__name__} - {e}")
#           traceback.print_exc() # Show traceback for test errors
#      finally:
#           if driver_test:
#                # Ensure driver is quit cleanly
#                try:
#                     driver_test.quit()
#                     print("Navigateur de test FB Page Scraper fermé.")
#                except Exception as e_quit:
#                     print(f"Error closing test browser: {e_quit}")
#
#      print("\nFin du test autonome de facebook_page_scraper.py.")