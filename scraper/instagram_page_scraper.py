# instagram_page_scraper.py

import os
import json
import time
import random
import re
import traceback
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException
)

# --- Import Google Generative AI Library ---
import google.generativeai as genai

# --- Regex definitions ---
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX_TEXT_PARSING = re.compile(
    r'(?:(?:\+|00)\d{1,4}[\s.-]?)?[\(\s.-]?\d{1,4}[\)\s.-]?[\d\s.-]{5,}\d|\b\d{7,}\b',
    re.IGNORECASE
)
CLEAN_PHONE_REGEX = re.compile(r'[\s().\-+📲📞☎️]')
LINK_REGEX_IN_TEXT = re.compile(r'(https?://\S+)', re.IGNORECASE)
WHATSAPP_LINK_REGEX = re.compile(r'(https?://(?:www\.)?wa\.me/\S+)', re.IGNORECASE)
FACEBOOK_LINK_REGEX = re.compile(r'(https?://(?:www\.)?facebook\.com/\S+|https?://(?:www\.)?fb\.me/\S+)', re.IGNORECASE)


# Generic text patterns to help identify non-bio content in text blocks
NON_BIO_PATTERNS = [
    re.compile(r'^\d[\s,k\u202f]+\s*(?:publications|followers|suivi\(e\)s)\s*$', re.IGNORECASE), # Counts
    re.compile(r'^(Suivre|Contacter)$', re.IGNORECASE), # Buttons
    re.compile(r'^[A-Z][a-zA-Z\s]+\s*$', re.IGNORECASE), # Lines with mostly capitalized words (potential categories or short headers)
    EMAIL_REGEX,
    PHONE_REGEX_TEXT_PARSING,
    LINK_REGEX_IN_TEXT # General links
]

# Generic name check regex (to avoid misidentifying counts or buttons as names)
GENERIC_NAME_CHECK_REGEX = re.compile(
    r'^(?:Followers|Following|Posts|Publications|Abonnés|Abonnements|Suivre|Contacter|Vérifié|\d[\s,k\u202f]+\s*(?:posts|followers|following|publications|abonnés|abonnements)|Plus)$',
    re.IGNORECASE
)

# Heuristic Address Regex - Attempting to find common address patterns per line
ADDRESS_LINE_HEURISTIC_REGEX = re.compile(
    r'^(?:[\u1f4cd📍][\s]*)?(?:\d+[\s,-])?(?:(?:Rue|Avenue|Blvd|Street|St|Av|Bd)\b[\s,-]?.*?\b)?(?:[\w\s,-]+)?(?:,\s*\d{5,})?(?:,\s*[A-Z][a-zA-Z\s]+)?(?:,\s*(?:Morocco|Maroc))?',
    re.IGNORECASE
)


# --- Configure the Generative AI API ---
# Make sure you have set the GOOGLE_API_KEY environment variable
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        print("[Gemini API] Google API Key loaded from environment variable.")
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        print("[Gemini API] Gemini 1.5 Flash model loaded.")
    except Exception as e:
        print(f"[Gemini API] ERROR loading Gemini model: {e}")
        print("[Gemini API] AI extraction will be skipped.")
        gemini_model = None
else:
    print("[Gemini API] WARNING: GOOGLE_API_KEY environment variable not set.")
    print("[Gemini API] AI extraction will be skipped.")
    gemini_model = None


INSTAGRAM_COOKIES_FILE = "instagram_cookies.json"
INSTAGRAM_LOGIN_URL = "https://www.instagram.com/accounts/login/"

def save_instagram_cookies(driver, filename=INSTAGRAM_COOKIES_FILE):
    """Sauvegarde les cookies Instagram dans un fichier JSON."""
    try:
        with open(filename, 'w') as f:
            cookies = driver.get_cookies()
            json.dump(cookies, f, indent=4)
        print(f"[Instagram Login] Cookies sauvegard\u00e9s dans {filename}.")
    except Exception as e:
        print(f"[Instagram Login] Erreur lors de la sauvegarde des cookies : {e}")

def load_instagram_cookies(driver, filename=INSTAGRAM_COOKIES_FILE):
    """Charge les cookies Instagram depuis un fichier JSON."""
    try:
        if not os.path.exists(filename):
            print(f"[Instagram Login] Fichier de cookies '{filename}' non trouv\u00e9.")
            return False
        with open(filename, 'r') as f:
            cookies = json.load(f)
            driver.get("https://www.instagram.com/")
            time.sleep(2) # Give page a moment to load before adding cookies
            for cookie in cookies:
                # Domain might need adjustment for cookie adding if starting URL is different
                # Let's ensure domain is correct or omit for current domain
                # cookie.pop('domain', None) # Remove domain to let Selenium apply it to current domain
                if 'domain' in cookie:
                    # Simple check to avoid adding cross-domain cookies if not needed
                    if ".instagram.com" in cookie['domain']:
                         driver.add_cookie(cookie)
                    else:
                         # print(f"  [Cookie Load] Skipping cookie for domain: {cookie['domain']}") # Too verbose
                         pass
                else:
                     driver.add_cookie(cookie)


            driver.refresh()
            time.sleep(3) # Give page time to refresh with cookies
        print("[Instagram Login] Cookies charg\u00e9s avec succ\u00e8s.")
        return True
    except Exception as e:
        print(f"[Instagram Login] Erreur lors du chargement des cookies : {e}")
        return False

def is_instagram_logged_in(driver):
    """Vérifie si l'utilisateur est connecté à Instagram."""
    try:
        # Navigate to home page and check for a known logged-in element (like the home icon)
        driver.get("https://www.instagram.com/")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Accueil"], [aria-label="Home"], [role="navigation"] a[href="/"]'))
        )
        # Also check if current URL is not a login/error page
        if any(keyword in driver.current_url.lower() for keyword in ["accounts/login", "error", "consent", "challenge"]):
             print("[Instagram Login] Redirection d\u00e9tect\u00e9e vers la page de connexion malgr\u00e9 la d\u00e9tection d'\u00e9l\u00e9ments.")
             return False
        print("[Instagram Login] Session active d\u00e9tect\u00e9e.")
        return True
    except TimeoutException:
        print("[Instagram Login] Session non active (Timeout sur \u00e9l\u00e9ment de connexion).")
        return False
    except Exception as e:
        print(f"[Instagram Login] Erreur lors de la v\u00e9rification de la session : {e}")
        return False


def manual_instagram_login(driver, cookies_filename=INSTAGRAM_COOKIES_FILE):
    """Permet une connexion manuelle à Instagram et sauvegarde les cookies."""
    print("[Instagram Login] Veuillez vous connecter manuellement dans le navigateur qui vient de s'ouvrir.")
    try:
        driver.get(INSTAGRAM_LOGIN_URL)
        # Use input to pause execution
        input(">>> Appuyez sur Entrée ICI dans la console après vous être connecté manuellement et que le fil d'actualité s'affiche <<<")
        if is_instagram_logged_in(driver):
            save_instagram_cookies(driver, cookies_filename)
            return True
        else:
             print("[Instagram Login] La connexion manuelle semble avoir \u00e9chou\u00e9 ou n'a pas abouti \u00e0 la page d'accueil.")
             return False
    except Exception as e:
         print(f"[Instagram Login] Erreur lors de la procédure de connexion manuelle : {e}")
         return False


def ensure_instagram_login(driver, cookies_filename=INSTAGRAM_COOKIES_FILE):
    """Assure que l'utilisateur est connecté à Instagram."""
    print("[Instagram Login] Tentative de v\u00e9rifier/charger la session...")
    if load_instagram_cookies(driver, cookies_filename) and is_instagram_logged_in(driver):
        print("[Instagram Login] Utilisateur connect\u00e9 via cookies.")
        return True
    else:
        print("[Instagram Login] Connexion par cookies \u00e9chou\u00e9e ou session expir\u00e9e.")
        # Clean up potential failed login page artifacts before manual login
        try:
            driver.get("about:blank") # Navigate away
            time.sleep(1)
        except Exception:
            pass # Ignore errors here

        success = manual_instagram_login(driver, cookies_filename)
        if success:
             print("[Instagram Login] Connexion manuelle r\u00e9ussie.")
        else:
             print("[Instagram Login] Connexion manuelle \u00e9chou\u00e9e ou ignor\u00e9e.")
        return success

# --- Function to call the Gemini API for extraction ---
def extract_info_with_gemini(text):
    """
    Sends text to Google Gemini API to extract contact, names, counts, and bio information.
    Returns a dictionary with extracted info or None if an error occurs or model is not loaded.
    """
    if gemini_model is None:
        # print("[Gemini API] Model not loaded, skipping AI extraction.") # Already printed on load failure
        return None

    # Craft the prompt for the AI model
    prompt = f"""
Analyze the following Instagram profile text. Extract the following information:
- Usernames (e.g., @profile_name)
- Full Names (the bold name, usually near the username)
- Number of Posts/Publications
- Number of Followers
- Number of Following
- Phone Number(s)
- Email Address(es)
- Website URL(s) (excluding links that clearly point to instagram.com, facebook.com, fb.me, or wa.me)
- Facebook Page URL(s)
- WhatsApp Link(s) (specifically wa.me links)
- Physical Address(es)
- The main descriptive text for the Bio (excluding counts like "publications", "followers", "suivi(e)s", usernames, full names, buttons like "Suivre" or "Contacter", highlights names, footer links like "Meta", "À propos", "Blog", etc., and excluding the extracted Address lines).

Return the information in a JSON format with keys like "usernames", "full_names", "posts_count", "followers_count", "following_count", "phones", "emails", "websites", "facebook_urls", "whatsapp_urls", "addresses", "bio_text". If a type of information is not found, use an empty list for lists or an empty string for bio_text or count fields (use "N/A" for counts if not found). Ensure numbers in counts are returned as strings without commas, points, or spaces.

Example desirable output format:
{{
  "usernames": ["@profile_name"],
  "full_names": ["Profile Full Name"],
  "posts_count": "123",
  "followers_count": "4567",
  "following_count": "890",
  "phones": ["+1234567890", "0123456789"],
  "emails": ["contact@example.com"],
  "websites": ["https://www.example.com"],
  "facebook_urls": ["https://www.facebook.com/pagename"],
  "whatsapp_urls": ["https://wa.me/1234567890"],
  "addresses": ["123 Main St, Anytown, CA 91234"],
  "bio_text": "We sell amazing products! Free shipping available."
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
        # Handle cases where the model might wrap JSON in markdown or include extra text
        json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
        if json_match:
             json_string = json_match.group(0)
             try:
                 extracted_data = json.loads(json_string)
                 # print(f"[Gemini API] Successfully extracted data: {extracted_data}") # Too verbose for logs
                 return extracted_data
             except json.JSONDecodeError as json_e:
                 print(f"[Gemini API] ERROR decoding JSON from AI response: {json_e}")
                 print(f"[Gemini API] Raw AI response text: {response_text}")
                 return None
        else:
            print("[Gemini API] WARNING: Could not find JSON object in AI response.")
            print(f"[Gemini API] Raw AI response text: {response_text}")
            return None

    except Exception as e:
        print(f"[Gemini API] ERROR during AI API call: {e}")
        # Handle specific API errors if needed
        return None


def scrape_instagram_page(driver, page_url, source_info=None):
    """
    Scrape les informations d'une page/profil Instagram, y compris la bio et les liens associés.
    Utilise AI pour extraire les informations de contact, noms, compteurs et bio du texte, avec des fallbacks.
    """
    print(f"\n  [Insta Page Scraper] Scraping info pour URL: {page_url}")

    detailed_info = {
        "Nom d'Utilisateur": "Not Found",
        "Nom Complet": "Not Found",
        "Bio": "Not Found",
        "Téléphone": "Not Found",
        "Email": "Not Found",
        "Site Web": "Not Found", # Primary website link (dedicated element, then fallback from AI/Regex)
        "Adresse": "N/A (Insta)", # Address extracted by AI or heuristic
        "Instagram": page_url,
        "Facebook": "Not Found", # Facebook link found by AI or regex
        "WhatsApp": "Not Found", # WhatsApp link found by AI or regex
        "WhatsApp à vérifier": "Not Generated", # WhatsApp link generated from found phone number
        "URL": page_url, # Standardized URL field for CSV
        "Nombre de Publications": "N/A",
        "Nombre de Followers": "N/A",
        "Nombre de Suivis": "N/A",
        "Site Web (Bio)": "Not Found", # General website link found by AI or regex in text
        "Statut_Scraping_Detail": "Attempting",
        "Message_Erreur_Detail": "",
        "Full Header Text (from container)": "Not Found (Container not found)" # For debugging/verification
    }

    if source_info:
        detailed_info['URL_Originale_Source'] = source_info.get('URL_Originale_Source', page_url)
        # Copy other info from source_info, prioritizing scraped data if found later
        for key, value in source_info.items():
             # Only copy if our field is default or None/empty and key is relevant
             if key not in ['URL', 'URL_Originale_Source', 'Instagram', 'Statut_Scraping_Detail', 'Message_Erreur_Detail']:
                  if detailed_info.get(key) in ["Not Found", "N/A", "N/A (Insta)", "N/A (FB)", "Not Generated", "", None]:
                      detailed_info[key] = value # Copy existing info
    else:
         detailed_info['URL_Originale_Source'] = page_url


    profile_container_element = None
    full_text_area = ""

    try: # Main try block for scraping the page
        time.sleep(random.uniform(2, 4))
        driver.get(page_url)

        # === Wait for dynamically loaded content ===
        try:
            print("    [Insta Page Scraper] Tentative d'attendre l'\u00e9l\u00e9ment du nom d'utilisateur (apr\u00e8s chargement dynamique)...")
            # Wait for the h2 element that contains the username, or main content area
            WebDriverWait(driver, 20).until(
                 EC.presence_of_element_located((By.CSS_SELECTOR, 'main h2, header h2, div[role="main"] h2, article h2, main article, main, header[role="banner"]'))
            )
            print("    [Insta Page Scraper] Élément clé ou conteneur détecté.")
            time.sleep(random.uniform(3, 5)) # Additional wait for other elements to render

            # Find the main profile container element AFTER dynamic load
            try:
                profile_container_element = driver.find_element(By.CSS_SELECTOR, 'main article')
                # print("    [Insta Page Scraper] Conteneur 'main article' trouvé.") # Too verbose
            except NoSuchElementException:
                try:
                    profile_container_element = driver.find_element(By.CSS_SELECTOR, 'main')
                    # print("    [Insta Page Scraper] Conteneur 'main' trouvé (fallback).") # Too verbose
                except NoSuchElementException:
                    try:
                        profile_container_element = driver.find_element(By.CSS_SELECTOR, 'header[role="banner"]')
                        # print("    [Insta Page Scraper] Conteneur 'header[role=\"banner\"]' trouvé (fallback).") # Too verbose
                    except NoSuchElementException:
                         print("    [Insta Page Scraper] Aucun conteneur principal spécifique trouvé. Utilisation du corps de la page (moins fiable).")
                         profile_container_element = driver.find_element(By.CSS_SELECTOR, 'body') # Final fallback


            # Extract both text and HTML from the found container
            full_text_area = profile_container_element.text
            # page_content_html = profile_container_element.get_attribute('outerHTML') # Keep this commented unless needed later
            detailed_info['Full Header Text (from container)'] = full_text_area # Keep for text analysis (Gemini)
            # print(f"    [Insta Page Scraper] Extracted full text from container (partial display):\n--- Start Full Text ---\n{full_text_area[:500]}...\n--- End Full Text ---")


        except TimeoutException:
            print(f"  [Insta Page Scraper] Timeout lors de l'attente des éléments clés pour {page_url}. La page n'a peut-\u00eatre pas fini de charger ou n'est pas accessible.")
            detailed_info["Statut_Scraping_Detail"] = "Timeout on dynamic load wait"
            detailed_info["Message_Erreur_Detail"] = "Timeout waiting for key elements after dynamic load."
            # Check for login/error pages if a timeout occurs
            current_url_after_timeout = driver.current_url
            if any(keyword in current_url_after_timeout.lower() for keyword in ["accounts/login", "error", "consent", "challenge"]):
                 detailed_info["Statut_Scraping_Detail"] = "Redirected/Inaccessible after timeout"
                 detailed_info["Message_Erreur_Detail"] = f"Redirected to {current_url_after_timeout} after timeout - might require login or page is private/non-existent."
                 # Attempt to check for "Page Not Found" indicator specifically
                 try:
                    driver.find_element(By.XPATH, "//*[contains(text(), 'Sorry, this page isn\'t available.')] | //*[contains(text(), 'Désolé, cette page n\'est pas disponible.')]")
                    detailed_info["Statut_Scraping_Detail"] = "Page Not Found after timeout"
                    detailed_info["Message_Erreur_Detail"] = "Instagram page not found (404) after timeout."
                    print("    [Insta Page Scraper] Confirmed: Page Not Found.")
                 except NoSuchElementException:
                    pass # Not a 404, must be login/consent etc.

            return detailed_info # Exit function early

        except NoSuchElementException:
             # This catch might be redundant due to TimeoutException in the wait, but good to have
             print(f"  [Insta Page Scraper] NoSuchElementException g\u00e9n\u00e9rale lors de l'attente ou de la recherche initiale d'un \u00e9l\u00e9ment cl\u00e9 pour {page_url}.")
             detailed_info["Statut_Scraping_Detail"] = "Critical Element Not Found"
             detailed_info["Message_Erreur_Detail"] = "Could not find a critical element (like username or main container)."
             return detailed_info # Exit function early

        # Check for redirection again after finding a potential container
        current_url_after_load = driver.current_url
        if any(keyword in current_url_after_load.lower() for keyword in ["accounts/login", "error", "consent", "challenge"]):
            print(f"  [Insta Page Scraper] Redirection d\u00e9tect\u00e9e pour {page_url} -> {current_url_after_load} APRES d\u00e9tection d'un conteneur. Probablement non connect\u00e9 ou page inaccessible.")
            detailed_info["Statut_Scraping_Detail"] = "Redirected/Inaccessible after container find"
            detailed_info["Message_Erreur_Detail"] = f"Redirected to {current_url_after_load} after finding container - might require login or page is private/non-existent."
             # Attempt to check for "Page Not Found" indicator specifically
            try:
                driver.find_element(By.XPATH, "//*[contains(text(), 'Sorry, this page isn\'t available.')] | //*[contains(text(), 'Désolé, cette page n\'est pas disponible.')]")
                detailed_info["Statut_Scraping_Detail"] = "Page Not Found after container find"
                detailed_info["Message_Erreur_Detail"] = "Instagram page not found (404) after finding container."
                print("    [Insta Page Scraper] Confirmed: Page Not Found.")
            except NoSuchElementException:
                 pass # Not a 404, must be login/consent etc.
            return detailed_info # Exit function early


        # --- Use the comprehensive extracted text for AI and parsing ---
        # full_text_area is already defined from the container text extraction

        # --- Call AI for Extraction (if model is loaded and text is available) ---
        ai_extracted_data = None
        if gemini_model and full_text_area: # Only call AI if model loaded and text is available
             try:
                 print("    [Insta Page Scraper] Sending text to AI for contact, names, counts and bio extraction...")
                 ai_extracted_data = extract_info_with_gemini(full_text_area)
                 if ai_extracted_data:
                      print("    [Insta Page Scraper] AI extraction successful.")
                 else:
                      print("    [Insta Page Scraper] AI extraction returned no data or failed internally.")
                      detailed_info["Message_Erreur_Detail"] += "; AI extraction returned no data."

             except Exception as ai_e:
                 print(f"    [Insta Page Scraper] Error during AI extraction process: {type(ai_e).__name__} - {ai_e}")
                 detailed_info["Message_Erreur_Detail"] += f"; AI extraction error: {type(ai_e).__name__}"


        # === Integrate AI Results and Fallback to Regex Parsing ===

        # --- Integrate AI results (if available) ---
        if ai_extracted_data:
            # Names
            if ai_extracted_data.get("usernames"):
                # Ensure the username extracted by AI matches the URL or looks valid
                first_ai_username = ai_extracted_data["usernames"][0].replace('@', '').strip()
                url_username_match = re.search(r"instagram\.com/([\w\.\-]+)/?", page_url, re.IGNORECASE)
                if url_username_match and first_ai_username.lower() == url_username_match.group(1).lower():
                     detailed_info["Nom d'Utilisateur"] = "@" + first_ai_username
                elif re.match(r'^[\w\.\-]+$', first_ai_username) and 1 < len(first_ai_username) <= 30: # Basic format check
                    detailed_info["Nom d'Utilisateur"] = "@" + first_ai_username
                # else: print(f"    [Insta Page Scraper] AI username '{first_ai_username}' does not match URL or seems invalid. Ignoring.") # Too verbose

            if ai_extracted_data.get("full_names"):
                 first_ai_full_name = ai_extracted_data["full_names"][0].strip()
                 # Basic validation: check length and ensure it doesn't look like a generic term or username
                 if first_ai_full_name and len(first_ai_full_name) > 1 and not GENERIC_NAME_CHECK_REGEX.match(first_ai_full_name) and first_ai_full_name.lower() != detailed_info["Nom d'Utilisateur"].replace('@','').lower():
                     detailed_info["Nom Complet"] = first_ai_full_name


            # Counts (Ensure they are numeric or N/A)
            detailed_info["Nombre de Publications"] = str(ai_extracted_data.get("posts_count", "N/A")).strip() or "N/A"
            detailed_info["Nombre de Followers"] = str(ai_extracted_data.get("followers_count", "N/A")).strip() or "N/A"
            detailed_info["Nombre de Suivis"] = str(ai_extracted_data.get("following_count", "N/A")).strip() or "N/A"

            # Clean up counts that might contain non-digits but were extracted (e.g. "10k")
            for count_field in ["Nombre de Publications", "Nombre de Followers", "Nombre de Suivis"]:
                 count_value = detailed_info[count_field]
                 if count_value != "N/A":
                      cleaned_count = re.sub(r'[\s,kK\u202f\.]', '', count_value).strip()
                      if cleaned_count.isdigit():
                           detailed_info[count_field] = cleaned_count
                      elif re.match(r'^\d+k$', cleaned_count, re.IGNORECASE): # Handle 'k' notation
                           try:
                                num_part = cleaned_count[:-1]
                                detailed_info[count_field] = str(int(float(num_part) * 1000)) # Convert '10k' to '10000'
                           except ValueError:
                                detailed_info[count_field] = "N/A"
                      else:
                           detailed_info[count_field] = "N/A"


            # Contact Info (Phones, Emails, Websites, Facebook, WhatsApp, Addresses)
            if ai_extracted_data.get("phones"):
                # AI might return a list, take the first one for the main field
                detailed_info["Téléphone"] = ai_extracted_data["phones"][0]
                 # Generate WhatsApp to verify from AI phone
                cleaned_phone_for_whatsapp = CLEAN_PHONE_REGEX.sub('', detailed_info["Téléphone"])
                if len(cleaned_phone_for_whatsapp) >= 6 and re.fullmatch(r'\d+', cleaned_phone_for_whatsapp):
                     # *** Apply Moroccan number reformatting here ***
                     if cleaned_phone_for_whatsapp.startswith('0') and len(cleaned_phone_for_whatsapp) in [9, 10]: # Common Moroccan formats
                         detailed_info["WhatsApp à vérifier"] = f"https://wa.me/212{cleaned_phone_for_whatsapp[1:]}"
                         # print(f"    [Insta Page Scraper] Generated WhatsApp from AI phone (reformatted): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     elif cleaned_phone_for_whatsapp.startswith('212') and len(cleaned_phone_for_whatsapp) in [11, 12]: # Already +212 or 212
                          detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp}"
                          # print(f"    [Insta Page Scraper] Generated WhatsApp from AI phone (+212): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     elif cleaned_phone_for_whatsapp.startswith('+212') and len(cleaned_phone_for_whatsapp) in [12, 13]: # Already +212
                          detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp.replace('+','')}" # Remove '+' for wa.me
                          # print(f"    [Insta Page Scraper] Generated WhatsApp from AI phone (+212): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     else:
                         detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp}" # Keep as is if format is different
                         # print(f"    [Insta Page Scraper] Generated WhatsApp from AI phone (generic format): {detailed_info['WhatsApp à vérifier']}") # Too verbose

                else:
                     detailed_info["WhatsApp à vérifier"] = "Invalid Phone Format for WhatsApp"


            if ai_extracted_data.get("emails"):
                detailed_info["Email"] = ai_extracted_data["emails"][0] # Take the first email

            if ai_extracted_data.get("websites"):
                 # AI might return a list, take the first one as primary website
                 ai_website = ai_extracted_data["websites"][0]
                 if ai_website and not any(domain in ai_website.lower() for domain in ["instagram.com", "facebook.com", "fb.me", "wa.me"]):
                      detailed_info["Site Web"] = ai_website
                      # Also set Site Web (Bio) if it's still Not Found
                      if detailed_info["Site Web (Bio)"] == "Not Found":
                           detailed_info["Site Web (Bio)"] = ai_website

            if ai_extracted_data.get("facebook_urls"):
                detailed_info["Facebook"] = ai_extracted_data["facebook_urls"][0] # Take the first Facebook URL

            if ai_extracted_data.get("whatsapp_urls"):
                whatsapp_url_ai = ai_extracted_data["whatsapp_urls"][0]
                if whatsapp_url_ai and "wa.me" in whatsapp_url_ai.lower():
                     detailed_info["WhatsApp"] = whatsapp_url_ai
                     # Update Téléphone from AI WhatsApp number if Téléphone wasn't found yet or AI phone was less specific
                     wa_number_match = WHATSAPP_LINK_REGEX.search(detailed_info["WhatsApp"])
                     if wa_number_match:
                          wa_number_digits = CLEAN_PHONE_REGEX.sub('', wa_number_match.group(1))
                          current_phone_digits = CLEAN_PHONE_REGEX.sub('', detailed_info.get("Téléphone", ""))

                          if detailed_info["Téléphone"] == "Not Found" or (wa_number_digits and len(wa_number_digits) > len(current_phone_digits)):
                               detailed_info["Téléphone"] = wa_number_digits
                               detailed_info["WhatsApp à vérifier"] = detailed_info["WhatsApp"] # WhatsApp verifier should be the direct link if found

            if ai_extracted_data.get("addresses"):
                # AI might return a list, take the first one as the main address
                 detailed_info["Adresse"] = ai_extracted_data["addresses"][0]


            if ai_extracted_data.get("bio_text"):
                 detailed_info["Bio"] = ai_extracted_data["bio_text"]

        else: # AI extraction failed or gemini_model is None
            # print("    [Insta Page Scraper] AI extraction failed or not used. Falling back to regex parsing.") # Already logged

            # --- Fallback to Regex Parsing (if AI failed or not used) ---
            # This logic remains as a safety net if AI fails to extract certain fields from the text.

            # Names (Fallback if AI didn't find them) - Try extracting from the page title if AI failed for names
            if detailed_info["Nom d'Utilisateur"] == "Not Found" or detailed_info["Nom Complet"] == "Not Found":
                 try:
                     page_title = driver.title.strip()
                     if page_title and " - Instagram" in page_title:
                          # Titles are typically "Nom Complet (@NomUtilisateur) • Instagram photos and videos"
                          title_match = re.search(r"^(.*?)\s*\((@[\w\.\-]+)\)\s*•\s*Instagram", page_title)
                          if title_match:
                               title_full_name = title_match.group(1).strip()
                               title_username = title_match.group(2).strip()

                               if detailed_info["Nom Complet"] == "Not Found" and title_full_name and len(title_full_name) > 1 and not GENERIC_NAME_CHECK_REGEX.match(title_full_name):
                                    detailed_info["Nom Complet"] = title_full_name
                                    # print(f"    [Insta Page Scraper] Full Name found via title fallback: {detailed_info['Nom Complet']}")

                               if detailed_info["Nom d'Utilisateur"] == "Not Found" and title_username and re.match(r'^@[\w\.\-]+$', title_username) and 1 < len(title_username.replace('@','')) <= 30:
                                     detailed_info["Nom d'Utilisateur"] = title_username
                                     # print(f"    [Insta Page Scraper] Username found via title fallback: {detailed_info['Nom d\'Utilisateur']}")

                          # Handle simpler title formats like "NomUtilisateur • Instagram photos and videos"
                          elif detailed_info["Nom d'Utilisateur"] == "Not Found":
                               title_match_simple = re.search(r"^([\w\.\-]+)\s*•\s*Instagram", page_title, re.IGNORECASE)
                               if title_match_simple:
                                    simple_username = title_match_simple.group(1).strip()
                                    if simple_username and re.match(r'^[\w\.\-]+$', simple_username) and 1 < len(simple_username) <= 30:
                                         detailed_info["Nom d'Utilisateur"] = "@" + simple_username
                                         # print(f"    [Insta Page Scraper] Username found via simple title fallback: {detailed_info['Nom d\'Utilisateur']}")


                 except Exception as e_title:
                      # print(f"    [Insta Page Scraper] Error during title parsing for names: {e_title}") # Too verbose
                      pass # Continue


            # Counts (Fallback if AI didn't find them) - Use the text regex fallback
            if detailed_info["Nombre de Publications"] == "N/A": # Check if still N/A default
                 # print("    [Insta Page Scraper] Attempting to extract counts from text (fallback)...") # Already logged
                 # Look for number followed by specific keywords
                 counts_text_match = re.search(
                     r'(\d[\s,kK\u202f\.]*)\s*(?:publications|posts).*?(\d[\s,kK\u202f\.]*)\s*(?:followers|abonn(?:é|e)s|abonnements).*?(\d[\s,kK\u202f\.]*)\s*(?:suivi\(e\)s|following)',
                     full_text_area, re.IGNORECASE | re.DOTALL
                 )
                 if counts_text_match:
                      detailed_info["Nombre de Publications"] = re.sub(r'[\s,kK\u202f\.]', '', counts_text_match.group(1)).strip() or "N/A"
                      detailed_info["Nombre de Followers"] = re.sub(r'[\s,kK\u202f\.]', '', counts_text_match.group(2)).strip() or "N/A"
                      detailed_info["Nombre de Suivis"] = re.sub(r'[\s,kK\u202f\.]', '', counts_text_match.group(3)).strip() or "N/A"
                      # print(f"    [Insta Page Scraper] Counts found via text regex (fallback): Posts={detailed_info['Nombre de Publications']}, Followers={detailed_info['Nombre de Followers']}, Following={detailed_info['Nombre de Suivis']}") # Too verbose

            # Email Extraction (Fallback if AI didn't find it)
            if detailed_info["Email"] == "Not Found":
                 email_match = EMAIL_REGEX.search(full_text_area)
                 if email_match:
                     detailed_info["Email"] = email_match.group(0)
                     # print(f"    [Insta Page Scraper] Email found via fallback regex: {detailed_info['Email']}") # Too verbose

            # Phone Extraction (Fallback if AI didn't find it)
            if detailed_info["Téléphone"] == "Not Found":
                 phone_matches = PHONE_REGEX_TEXT_PARSING.findall(full_text_area)
                 found_phone_fallback = "Not Found"
                 for raw_phone in phone_matches:
                      cleaned_phone = CLEAN_PHONE_REGEX.sub('', raw_phone)
                      if sum(c.isdigit() for c in cleaned_phone) >= 7: # Basic validation
                          if found_phone_fallback == "Not Found" or len(cleaned_phone) > len(CLEAN_PHONE_REGEX.sub('', found_phone_fallback)):
                               found_phone_fallback = cleaned_phone # Keep the longest/most complete number found
                 if found_phone_fallback != "Not Found":
                      detailed_info["Téléphone"] = found_phone_fallback
                      # print(f"    [Insta Page Scraper] T\u00e9l\u00e9phone found via fallback regex: {detailed_info['Téléphone']}") # Too verbose


            # WhatsApp Link Extraction (Fallback if AI didn't find it)
            if detailed_info["WhatsApp"] == "Not Found":
                 whatsapp_link_match = WHATSAPP_LINK_REGEX.search(full_text_area)
                 if whatsapp_link_match:
                      whatsapp_url = whatsapp_link_match.group(0)
                      wa_number_raw = whatsapp_link_match.group(1) # Keep raw to handle formatting later
                      detailed_info["WhatsApp"] = whatsapp_url
                      # Update Téléphone from WhatsApp number if not found or shorter
                      current_phone_digits = CLEAN_PHONE_REGEX.sub('', detailed_info.get("Téléphone", ""))
                      wa_number_digits = CLEAN_PHONE_REGEX.sub('', wa_number_raw) # Clean digits for comparison and storage
                      if detailed_info["Téléphone"] == "Not Found" or (wa_number_digits and len(wa_number_digits) > len(current_phone_digits)):
                           detailed_info["Téléphone"] = wa_number_digits
                           # print(f"    [Insta Page Scraper] Téléphone updated from WA link fallback: {detailed_info['Téléphone']}") # Too verbose

                      # Ensure WhatsApp à vérifier is set from the link
                      if detailed_info["WhatsApp à vérifier"] == "Not Generated":
                           detailed_info["WhatsApp à vérifier"] = detailed_info["WhatsApp"] # Use the direct link if found

                      # print(f"    [Insta Page Scraper] WhatsApp (wa.me) link found via fallback regex: {detailed_info['WhatsApp']}") # Too verbose


            # Facebook Link Extraction (Fallback if AI didn't find it)
            if detailed_info["Facebook"] == "Not Found":
                 facebook_link_match = FACEBOOK_LINK_REGEX.search(full_text_area)
                 if facebook_link_match:
                      detailed_info["Facebook"] = facebook_link_match.group(0)
                      # print(f"    [Insta Page Scraper] Facebook link found via fallback regex: {detailed_info['Facebook']}") # Too verbose


            # Other Links in text (Fallback for Site Web and Site Web (Bio) if AI didn't find them)
            if detailed_info["Site Web"] == "Not Found": # Only perform fallback if main Site Web is still Not Found
                 generic_links_found_fallback = LINK_REGEX_IN_TEXT.findall(full_text_area)
                 processed_generic_links_fallback = [
                      link.strip() for link in generic_links_found_fallback
                      if "instagram.com" not in link.lower()
                      and "facebook.com" not in link.lower()
                      and "fb.me" not in link.lower()
                      and "wa.me" not in link.lower()
                      and re.match(r'^https?://', link.strip(), re.IGNORECASE) # Ensure it looks like a full URL
                 ]

                 if processed_generic_links_fallback:
                      # print(f"    [Insta Page Scraper] Found {len(processed_generic_links_fallback)} generic links in fallback text.") # Too verbose
                      detailed_info["Site Web (Bio)"] = processed_generic_links_fallback[0]

                      main_website_link_fallback = None
                      for link in processed_generic_links_fallback:
                           # Basic regex to find links that look like main websites
                           if re.match(r'^https?://(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[\w.-]*)?$', link):
                                main_website_link_fallback = link
                                break

                      if main_website_link_fallback:
                           detailed_info["Site Web"] = main_website_link_fallback
                           # print(f"    [Insta Page Scraper] Using inferred main website link for primary Site Web in fallback: {detailed_info['Site Web']}") # Too verbose
                      else:
                           detailed_info["Site Web"] = processed_generic_links_fallback[0]
                           # print(f"    [Insta Page Scraper] Using first generic link for primary Site Web in fallback (no clear main website found): {detailed_info['Site Web']}") # Too verbose


            # Bio Text Inference (Fallback if AI didn't find it) - Use the previous heuristic line-by-line logic
            if detailed_info["Bio"] == "Not Found":
                 # print("    [Insta Page Scraper] Attempting to isolate Bio from fallback parsed text (line-by-line)...") # Too verbose
                 lines_fallback = full_text_area.split('\n')
                 cleaned_bio_lines_fallback = []

                 start_index_fallback = 0
                 # Find the first line that doesn't look like a name, count, or button
                 for i, line in enumerate(lines_fallback):
                      stripped_line = line.strip()
                      if stripped_line and not GENERIC_NAME_CHECK_REGEX.match(stripped_line) and \
                         detailed_info["Nom d'Utilisateur"].replace('@','') != stripped_line.replace('@','') and \
                         detailed_info["Nom Complet"] != stripped_line and \
                         "Suivre" not in stripped_line and "Contacter" not in stripped_line:
                           start_index_fallback = i
                           break

                 lines_to_process_for_bio_fallback = lines_fallback[start_index_fallback:]

                 for line in lines_to_process_for_bio_fallback:
                      stripped_line = line.strip()
                      if not stripped_line: continue

                      # Exclude lines that match known non-bio patterns and links (using all extracted link fields)
                      is_non_bio_line = False
                      for pattern in NON_BIO_PATTERNS:
                          if pattern.search(stripped_line):
                               is_non_bio_line = True
                               break
                      if is_non_bio_line: continue

                      # Exclude link text (using all extracted link fields)
                      is_link_line = False
                      all_found_links = []
                      if detailed_info["Site Web"] != "Not Found": all_found_links.append(detailed_info["Site Web"])
                      if detailed_info["Site Web (Bio)"] != "Not Found": all_found_links.append(detailed_info["Site Web (Bio)"])
                      if detailed_info["WhatsApp"] != "Not Found": all_found_links.append(detailed_info["WhatsApp"])
                      if detailed_info["Facebook"] != "Not Found": all_found_links.append(detailed_info["Facebook"])

                      for link in all_found_links:
                           if link.strip() and link.strip() in stripped_line:
                                is_link_line = True
                                break
                      if is_link_line: continue

                      # Attempt to identify potential address lines (Fallback) - Still heuristic, exclude them from bio
                      address_match_fallback = ADDRESS_LINE_HEURISTIC_REGEX.match(stripped_line)
                      if address_match_fallback:
                           continue # Exclude address lines from bio

                      # If it's not a known non-bio line or link, consider it part of the bio.
                      cleaned_bio_lines_fallback.append(stripped_line)

                 final_bio_text_fallback = '\n'.join(cleaned_bio_lines_fallback).strip()

                 # Remove Username and Full Name again if they somehow got included
                 if detailed_info["Nom d'Utilisateur"] != "Not Found":
                      final_bio_text_fallback = re.sub(r'^@?' + re.escape(detailed_info["Nom d'Utilisateur"].replace('@','')) + r'\b\n?', "", final_bio_text_fallback, flags=re.MULTILINE | re.IGNORECASE).strip()
                      final_bio_text_fallback = re.sub(r'@?' + re.escape(detailed_info["Nom d'Utilisateur"].replace('@','')) + r'\b', '', final_bio_text_fallback, flags=re.IGNORECASE).strip()

                 if detailed_info["Nom Complet"] != "Not Found":
                      final_bio_text_fallback = final_bio_text_fallback.replace(detailed_info["Nom Complet"], "", 1).strip()

                 # Clean up remaining common prefixes/suffixes/characters and generic terms
                 cleaned_lines_final_pass = []
                 for line in final_bio_text_fallback.split('\n'):
                     stripped_line = line.strip()
                     if stripped_line and len(stripped_line) > 1 and not GENERIC_NAME_CHECK_REGEX.match(stripped_line) and \
                        "Suivi(e) par" not in stripped_line and "PUBLICATIONS" not in stripped_line and \
                        "REELS" not in stripped_line and "IDENTIFIÉ(E)" not in stripped_line and \
                        "Meta" not in stripped_line and "À propos" not in stripped_line and \
                        "Blog" not in stripped_line and "Emplois" not in stripped_line and \
                        "Aide" not in stripped_line and "API" not in stripped_line and \
                        "Confidentialité" not in stripped_line and "Conditions" not in stripped_line and \
                        "Lieux" not in stripped_line and "Instagram Lite" not in stripped_line and \
                        "Threads" not in stripped_line and "Importation des contacts et non-utilisateurs" not in stripped_line and \
                        "Meta Verified" not in stripped_line and "Français" not in stripped_line and \
                        not stripped_line.isdigit(): # Exclude lines that are just numbers
                         cleaned_lines_final_pass.append(stripped_line)

                 final_bio_text_fallback = '\n'.join(cleaned_lines_final_pass).strip()


                 final_bio_text_fallback = final_bio_text_fallback.replace("plus", "").replace("...", "").strip()


                 if final_bio_text_fallback and len(final_bio_text_fallback) > 5: # Check for minimal length after cleaning
                      detailed_info["Bio"] = final_bio_text_fallback
                      # print("    [Insta Page Scraper] Bio text inferred from fallback parsed text.") # Too verbose
                 else:
                      # print("    [Insta Page Scraper] Inferred bio from fallback was empty or seemed generic after cleaning.") # Too verbose
                      detailed_info["Bio"] = "Not Found"


            # Address Extraction (Fallback if AI didn't find it) - Use the heuristic line-by-line logic
            # If detailed_info["Adresse"] is still the default "N/A (Insta)" after AI
            if detailed_info["Adresse"] == "N/A (Insta)":
                 # print("    [Insta Page Scraper] Attempting to extract Address from fallback parsed text (line-by-line)...") # Too verbose
                 lines_fallback = full_text_area.split('\n')
                 found_addresses_fallback = []

                 for line in lines_fallback:
                      stripped_line = line.strip()
                      if not stripped_line: continue

                      # Attempt to identify potential address lines (Fallback) - Still heuristic
                      address_match_fallback = ADDRESS_LINE_HEURISTIC_REGEX.match(stripped_line)
                      if address_match_fallback and len(stripped_line) > 5: # Add min length check
                           found_addresses_fallback.append(stripped_line)
                           # print(f"      [Insta Page Scraper] Potential address line found (fallback heuristic): {stripped_line}") # Too verbose
                           break # Take only the first potential address line found

                 if found_addresses_fallback:
                      detailed_info["Adresse"] = found_addresses_fallback[0]
                      # print(f"    [Insta Page Scraper] Main Address set from first found fallback line: {detailed_info['Adresse']}") # Too verbose
                 else:
                      detailed_info["Adresse"] = "N/A (Insta)"


            # Ensure WhatsApp à vérifier is generated if Téléphone is found by fallback
            if detailed_info["WhatsApp"] == "Not Found" and detailed_info["WhatsApp à vérifier"] == "Not Generated" and detailed_info["Téléphone"] != "Not Found":
                cleaned_phone_for_whatsapp = CLEAN_PHONE_REGEX.sub('', detailed_info["Téléphone"])
                if len(cleaned_phone_for_whatsapp) >= 6 and re.fullmatch(r'\d+', cleaned_phone_for_whatsapp):
                     # *** Apply Moroccan number reformatting here (Fallback) ***
                     if cleaned_phone_for_whatsapp.startswith('0') and len(cleaned_phone_for_whatsapp) in [9, 10]: # Common Moroccan formats
                         detailed_info["WhatsApp à vérifier"] = f"https://wa.me/212{cleaned_phone_for_whatsapp[1:]}"
                         # print(f"    [Insta Page Scraper] Generated WhatsApp from fallback phone (reformatted): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     elif cleaned_phone_for_whatsapp.startswith('212') and len(cleaned_phone_for_whatsapp) in [11, 12]: # Already +212 or 212
                          detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp}"
                          # print(f"    [Insta Page Scraper] Generated WhatsApp from fallback phone (+212): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     elif cleaned_phone_for_whatsapp.startswith('+212') and len(cleaned_phone_for_whatsapp) in [12, 13]: # Already +212
                          detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp.replace('+','')}" # Remove '+' for wa.me
                          # print(f"    [Insta Page Scraper] Generated WhatsApp from fallback phone (+212): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                     else:
                         detailed_info["WhatsApp à vérifier"] = f"https://wa.me/{cleaned_phone_for_whatsapp}" # Keep as is if format is different
                         # print(f"    [Insta Page Scraper] Generated WhatsApp from fallback phone (generic format): {detailed_info['WhatsApp à vérifier']}") # Too verbose
                else:
                     detailed_info["WhatsApp à vérifier"] = "Invalid Phone Format for WhatsApp"


        detailed_info["Statut_Scraping_Detail"] = "Success" # If we reached here, it means we successfully loaded and processed the page, even if data is "Not Found" or "N/A"
        # print(f"  [Insta Page Scraper] Scraping termin\u00e9 pour {page_url}. Statut: Success.")


    except StaleElementReferenceException:
        print(f"  [Insta Page Scraper] StaleElementReferenceException lors du scraping de {page_url}.")
        detailed_info["Statut_Scraping_Detail"] = "Error"
        detailed_info["Message_Erreur_Detail"] = "Stale element reference during scraping (likely due to page changes during scraping)."
        traceback.print_exc()
    except NoSuchElementException:
         # This should be caught by specific find_element blocks, but as a general catch
         print(f"  [Insta Page Scraper] NoSuchElementException g\u00e9n\u00e9rale lors du scraping de {page_url}.")
         detailed_info["Statut_Scraping_Detail"] = "Error finding element"
         detailed_info["Message_Erreur_Detail"] = "Could not find a required element."
         traceback.print_exc()
    except TimeoutException:
        # This should ideally be caught by the specific waits, but kept as a general catch
        print(f"  [Insta Page Scraper] TimeoutException g\u00e9n\u00e9rale lors du scraping de {page_url}.")
        detailed_info["Statut_Scraping_Detail"] = "Timeout (General)"
        detailed_info["Message_Erreur_Detail"] = "A general timeout occurred during scraping."
        traceback.print_exc()
    except ElementClickInterceptedException:
         print(f"  [Insta Page Scraper] ElementClickInterceptedException lors du scraping de {page_url}. Un overlay bloque peut-\u00eatre l'interaction.")
         detailed_info["Statut_Scraping_Detail"] = "Error"
         detailed_info["Message_Erreur_Detail"] = "Element click intercepted. An overlay might be present."
         traceback.print_exc()
    except Exception as e:
        print(f"  [Insta Page Scraper] Une erreur inattendue s'est produite lors du scraping de {page_url}: {type(e).__name__} - {e}")
        detailed_info["Statut_Scraping_Detail"] = "Error"
        detailed_info["Message_Erreur_Detail"] = f"Unexpected error: {type(e).__name__} - {e}"
        traceback.print_exc()

    # Ensure all fields have a value, even if "Not Found", "N/A", etc.
    for key in detailed_info.keys():
         if detailed_info.get(key) is None or detailed_info.get(key) == "":
             # Set defaults based on the field type and expected values
             if key in ["Téléphone", "Email", "Site Web", "WhatsApp", "Nom d'Utilisateur", "Nom Complet", "Bio", "Site Web (Bio)", "Facebook"]:
                  detailed_info[key] = "Not Found"
             elif key in ["WhatsApp à vérifier"]:
                  detailed_info[key] = "Not Generated"
             elif key in ["Nombre de Publications", "Nombre de Followers", "Nombre de Suivis"]:
                  detailed_info[key] = "N/A" # Keep N/A if counts weren't found
             elif key == "Adresse":
                 if detailed_info[key] is None or detailed_info[key] == "": # Check if it's still None or empty string
                      detailed_info[key] = "N/A (Insta)"
             elif key == "Statut_Scraping_Detail":
                 # If it's already an error status, keep it. Otherwise, mark as completed if not set to Success.
                 if detailed_info[key] == "Attempting":
                      detailed_info[key] = "Completed" # Page was processed, even if data is missing
             # Message_Erreur_Detail should not be overwritten if an error occurred


    # Final check to set default status if it's still "Attempting" and no error occurred
    if detailed_info["Statut_Scraping_Detail"] == "Attempting":
        # If we reached here, it means the initial wait succeeded, but maybe container wasn't found or other issues.
        # Let's differentiate between successful page load/partial scrape and critical failure.
        if detailed_info["Message_Erreur_Detail"] and "Critical Element Not Found" in detailed_info["Message_Erreur_Detail"]:
             # Status is already set to Error/Critical Element Not Found
             pass
        else:
             # Page loaded, but maybe no data was found. Mark as Completed.
             detailed_info["Statut_Scraping_Detail"] = "Completed"


    # Add Full Header Text to message error detail if it was not found, for debugging
    # This might be redundant now that we try to get container first
    # if detailed_info.get("Full Header Text (from container)") == "Not Found (Container not found)" and "Critical Element Not Found" in detailed_info["Statut_Scraping_Detail"]:
    #      detailed_info["Message_Erreur_Detail"] = f"Main container text not extracted. {detailed_info['Message_Erreur_Detail']}"


    return detailed_info

# --- Bloc d'exécution autonome (Optionnel pour tester ce script seul) ---
if __name__ == "__main__":
    print("Exécution de instagram_page_scraper.py en mode autonome (pour test).")
    test_url_insta = input("Entrez une URL de profil Instagram à tester (laissez vide pour ignorer) : ").strip()

    if not test_url_insta:
        print("Aucune URL fournie pour le test. Fin.")
    elif not test_url_insta.startswith("http"):
         print("L'URL doit commencer par http ou https. Fin.")
    elif "instagram.com" not in test_url_insta.lower():
         print("L'URL ne semble pas être une URL Instagram valide. Fin.")
    else:
        driver_test = None
        try:
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options

            # Setup Chrome options for a smoother experience (optional)
            options = Options()
            # options.add_argument("--headless") # Uncomment for headless mode (no browser window) - Note: Headless can sometimes be detected/blocked
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            # options.add_argument("--disable-gpu") # Often recommended for headless
            options.add_argument("--window-size=1920,1080") # Set a consistent window size
            # options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36") # Use a common user agent
            # Use undetected_chromedriver's options structure
            options.add_argument("--lang=en") # Set language to English potentially for more consistent element finding


            # Use undetected_chromedriver for the test as it's more robust for Instagram
            try:
                 driver_test = uc.Chrome(options=options)
                 print("Navigateur Chrome furtif initialisé pour test Insta Page Scraper.")
            except Exception as uc_error:
                 print(f"Could not initialize undetected_chromedriver: {uc_error}. Falling back to standard Chrome.")
                 # Fallback to standard Chrome if uc fails
                 service = Service()
                 driver_test = webdriver.Chrome(service=service, options=options)
                 print("Navigateur Chrome standard initialisé pour test Insta Page Scraper (Fallback).")


            if driver_test:
                # Ensure login before scraping a profile
                print("\n--- Tentative de connexion à Instagram ---")
                if ensure_instagram_login(driver_test):
                    print("Connexion Instagram r\u00e9ussie ou contourn\u00e9e.")
                    print(f"\n--- Lancement du scraping pour : {test_url_insta} ---")
                    # Pass source_info for the test to simulate main scraper call
                    source_info_test = {'URL_Originale_Source': test_url_insta, 'Source_Mot_Cle': 'test-keyword', 'Type_Source': 'Test'}
                    insta_data = scrape_instagram_page(driver_test, test_url_insta, source_info_test)
                    print("\nR\u00e9sultats Scraping Insta :")
                    # Sort keys alphabetically for consistent output
                    for key in sorted(insta_data.keys()):
                        print(f"- {key}: {insta_data[key]}")
                else:
                    print("\nERREUR : Connexion Instagram non \u00e9tablie. Impossible de scraper le profil.")

        except Exception as e:
            print(f"\nERREUR LORS DU TEST AUTONOME INSTA PAGE SCRAPER : {type(e).__name__} - {e}")
            traceback.print_exc()
        finally:
            if driver_test:
                # Ensure driver is quit cleanly
                try:
                     driver_test.quit()
                     print("\nNavigateur de test Insta Page Scraper ferm\u00e9.")
                except Exception as e_quit:
                     print(f"\nError closing test browser: {e_quit}")

    print("\n--- Fin du test autonome de instagram_page_scraper.py ---")