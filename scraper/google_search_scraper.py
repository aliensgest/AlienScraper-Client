# /home/AlienScraper/scraper/google_search_scraper.py

import time
import random
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException, StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC # Keep this
from itertools import product
import undetected_chromedriver as uc
from urllib.parse import urlparse, parse_qs, unquote # Importer pour le parsing d'URL
import sys # Importer pour sys.exit (non utilisé actuellement, mais gardé)
from pathlib import Path # Pour la gestion des chemins
from datetime import datetime # Pour l'horodatage des fichiers de débogage
import re # Pour nettoyer les noms de fichiers

# --- Configuration ---
GOOGLE_URL = "https://www.google.com"

# --- Configuration pour les screenshots de débogage (depuis config.py si possible) ---
try:
    from config import BASE_DIR as PROJECT_BASE_DIR # Importer BASE_DIR depuis config.py
    SCREENSHOTS_DIR_GGL = PROJECT_BASE_DIR / "screenshots"
    SCREENSHOTS_DIR_GGL.mkdir(parents=True, exist_ok=True)
except ImportError:
    print("  [Google Search] AVERTISSEMENT: config.py ou BASE_DIR non trouvé. Screenshots sauvegardés localement.")
    SCREENSHOTS_DIR_GGL = Path(".") # Fallback au dossier courant

# La limite de pages sera passée en paramètre depuis le script principal

# --- Initialisation du Navigateur (Gérée par le script principal) ---
# Nous n'avons pas besoin d'initialiser le driver ici.
# Le script principal nous passera une instance de driver déjà initialisée.

# --- Fonctions de Recherche Google ---

def go_to_google(driver):
    """Navigue vers la page d'accueil de Google et gère potentiellement le consentement."""
    if driver:
        try:
            # Définir un page load timeout avant chaque driver.get() important
            driver.set_page_load_timeout(45) # Augmenter si nécessaire, 45s est déjà beaucoup
            driver.get(GOOGLE_URL)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            # print(f"Connecté à {GOOGLE_URL}.") # Désactivé, le script principal affichera les logs globaux
            return True
        except TimeoutException as te:
            print(f"  [Google Search] Timeout lors de la connexion à Google ou attente barre recherche initiale: {te}")
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_context = "go_to_google"
                html_path = SCREENSHOTS_DIR_GGL / f"{timestamp}_TimeoutException_{safe_context}.html"
                png_path = SCREENSHOTS_DIR_GGL / f"{timestamp}_TimeoutException_{safe_context}.png"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                driver.save_screenshot(str(png_path))
                print(f"  [Google Search] Page source et screenshot sauvegardés dans {SCREENSHOTS_DIR_GGL} (go_to_google).")
            except Exception as e_save:
                print(f"  [Google Search] Erreur lors de la sauvegarde de la page source/screenshot: {e_save}")
            return False
        except Exception as e: # Capturer WebDriverException aussi
            print(f"  [Google Search] Erreur lors de la connexion à Google : {e}")
            return False
    return False

def perform_search(driver, keyword):
    """Trouve la barre de recherche Google et effectue la recherche."""
    print(f"  [Google Search] Effectuer la recherche pour : '{keyword}'")
    consent_clicked = False
    # Le premier bloc try-except semble être le principal, le second est une répétition. Je vais commenter le second.
    try:
        # --- Gestion du Consentement Google ---
        # Attendre un court instant pour voir si un bouton de consentement apparaît
        consent_buttons_selectors = [
            "//button[.//span[contains(text(), 'Tout accepter')]]", # Bouton "Tout accepter" (Français)
            "//button[.//div[contains(text(), 'Accept all')]]",    # Bouton "Accept all" (Anglais)
            "//button[.//div[contains(text(), 'Tout refuser')]]",  # Ou "Tout refuser"
            "//button[.//div[contains(text(), 'Reject all')]]"    # Ou "Reject all"
        ]
        for selector in consent_buttons_selectors:
            try:
                consent_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, selector)))
                if consent_button.is_displayed() and consent_button.is_enabled():
                    print(f"  [Google Search] Bouton de consentement trouvé ({selector}), clic...")
                    # Essayer un clic JavaScript si le clic normal est intercepté
                    try:
                        consent_button.click()
                    except ElementClickInterceptedException:
                        print("  [Google Search] Clic normal intercepté, tentative avec JavaScript.")
                        driver.execute_script("arguments[0].click();", consent_button)
                    consent_clicked = True
                    time.sleep(random.uniform(2, 3)) # Pause plus longue après le clic
                    break # Sortir de la boucle si un bouton est cliqué
                # else: print(f"  [Google Search] Bouton de consentement trouvé ({selector}) mais non visible/activé.") # Debug
            except TimeoutException:
                # print(f"  [Google Search] Bouton de consentement non trouvé avec sélecteur: {selector}") # Debug
                pass # Le bouton n'a pas été trouvé, essayer le suivant
        if not consent_clicked:
            print("  [Google Search] Aucun bouton de consentement évident trouvé ou déjà accepté.")
        # --- Fin Gestion Consentement ---

        # Revenir à Google peut être redondant si le consentement n'a pas redirigé, mais assure l'état
        # driver.get(GOOGLE_URL) # Commenté pour l'instant, voir si nécessaire après clic consentement
        # Si on revient à Google, il faut à nouveau attendre la barre de recherche.
        # Il est peut-être préférable de ne pas recharger et d'attendre la barre de recherche sur la page actuelle.

        # Attendre la barre de recherche après avoir potentiellement géré le consentement
        # Utiliser element_to_be_clickable car cela vérifie aussi la visibilité et l'activation.
        search_box_home = WebDriverWait(driver, 40).until( # Augmenté le délai à 40s
             EC.element_to_be_clickable((By.NAME, "q")) # Le sélecteur NAME "q" est généralement fiable
        )
        search_box_home.clear()
        search_box_home.send_keys(keyword)
        time.sleep(random.uniform(0.5, 1.5))
        search_box_home.send_keys(Keys.RETURN)

        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "search"))) # Attendre que les résultats apparaissent
        # print("  [Google Search] Recherche effectuée avec succès. Page de résultats chargée.") # Désactivé
        return True
    except TimeoutException as te:
        current_url = "Non récupérable"
        page_title = "Non récupérable"
        try:
            current_url = driver.current_url
            page_title = driver.title
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_context = re.sub(r'[^\w\-_\. ]', '_', keyword)[:50] # Nettoyer le mot-clé pour le nom de fichier
            html_path = SCREENSHOTS_DIR_GGL / f"{timestamp}_TimeoutException_perform_search_{safe_context}.html"
            png_path = SCREENSHOTS_DIR_GGL / f"{timestamp}_TimeoutException_perform_search_{safe_context}.png"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            driver.save_screenshot(str(png_path))
            print(f"  [Google Search] Page source et screenshot sauvegardés dans {SCREENSHOTS_DIR_GGL} (perform_search timeout).")
        except Exception as e_save:
            print(f"  [Google Search] Erreur lors de la sauvegarde de la page source/screenshot: {e_save}")

        # Tentative de détection de CAPTCHA
        captcha_detected = False
        page_content_lower = ""
        try:
            # S'assurer que driver.page_source est appelé seulement si nécessaire et géré
            if driver and hasattr(driver, 'page_source'):
                page_content_lower = driver.page_source.lower()
        except Exception:
            pass # Impossible de récupérer la page source, on se basera sur l'URL

        # Indicateurs de CAPTCHA plus robustes
        captcha_indicators_url = ["ipv4.google.com/sorry", "consent.google.com"]
        captcha_indicators_page = [
            "recaptcha", "grecaptcha",
            "nos systèmes ont détecté un trafic inhabituel",
            "our systems have detected unusual traffic",
            "pour continuer, veuillez saisir les caractères",
            "to continue, please type the characters"
        ]

        if any(indicator in current_url.lower() for indicator in captcha_indicators_url) or \
           (page_content_lower and any(indicator in page_content_lower for indicator in captcha_indicators_page)):
            captcha_detected = True
            print(f"  [Google Search] !!! CAPTCHA Google détecté sur {current_url} (Titre: {page_title}). Intervention manuelle ou réessai nécessaire. Abandon de cette recherche. !!!")
        
        print(f"  [Google Search] Erreur (Timeout) dans perform_search: {te}. Impossible de trouver la barre de recherche (CAPTCHA: {captcha_detected}). URL: {current_url}, Titre: {page_title}")
        return False

    except WebDriverException as e:
        print(f"  [Google Search] Erreur WebDriver lors de la recherche pour '{keyword}' : {e}")
        return False
    except Exception as e:
        print(f"  [Google Search] Erreur inattendue lors de la recherche pour '{keyword}' : {e}")
        return False


def extract_google_results(driver, keyword_combination):
    """
    Analyse la page de résultats Google actuelle, extrait les liens Facebook/Instagram et leurs titres.
    Retourne une liste de dictionnaires { 'title': ..., 'url': ..., 'source_keyword': ..., 'type': ... }.
    """
    # print("  [Google Search] Extraction des résultats de la page actuelle...") # Désactivé, rend le log trop verbeux
    page_results = []

    try:
        # Attendre un élément commun aux pages de résultats pour s'assurer qu'elle est chargée
        WebDriverWait(driver, 10).until(
             EC.presence_of_element_located((By.CSS_SELECTOR, 'div#search, div.g, div.rc')) # Éléments courants
        )
        time.sleep(random.uniform(1, 2)) # Petite pause supplémentaire

        # Sélecteurs CSS pour les conteneurs de résultats principaux
        # --- MODIFICATION : Utiliser un sélecteur plus précis basé sur l'analyse du HTML fourni ---
        result_containers = driver.find_elements(By.CSS_SELECTOR, 'div.tF2Cxc') # Cible les blocs contenant yuRUbf
        # if not result_containers:
        #      print("  [Google Search] Aucun conteneur de résultats standards trouvé sur cette page.") # Désactivé

        for container in result_containers:
            try:
                link_element = None
                url = None
                # Essayer de trouver le lien principal dans le conteneur
                try:
                    # Sélecteur plus spécifique pour le lien principal (souvent dans un h3)
                    link_element = container.find_element(By.CSS_SELECTOR, 'div.yuRUbf > a[href], div > a[href][data-ved]')
                    url = link_element.get_attribute('href')
                except NoSuchElementException:
                     # Essayer un sélecteur plus générique si le premier échoue
                     try:
                          link_element = container.find_element(By.CSS_SELECTOR, 'a[href]:not([role="button"])')
                          url = link_element.get_attribute('href')
                     except NoSuchElementException:
                          pass # Pas de lien trouvé dans ce conteneur

                # Nettoyer les URLs de redirection Google
                if url and "google." in urlparse(url).netloc and "/url?q=" in url:
                     try:
                          parsed_url = urlparse(url)
                          query_params = parse_qs(parsed_url.query)
                          if 'q' in query_params and query_params['q']:
                               url = query_params['q'][0] # Prendre l'URL réelle
                          else:
                               url = None # URL de redirection invalide
                     except Exception:
                          url = None # Échec du parsing

                if url:
                    # --- Vérification si l'URL est une page Facebook ou Instagram (avec filtre de slashes) ---
                    is_facebook = False
                    is_instagram = False
                    cleaned_url_lower = url.lower() # Convertir en minuscules une seule fois

                    # Validation pour Facebook
                    if "facebook.com/" in cleaned_url_lower and \
                       "facebook.com/ads" not in cleaned_url_lower and \
                       "facebook.com/l.php" not in cleaned_url_lower and \
                       not cleaned_url_lower.startswith("https://m.facebook.com"):
                        try:
                            parsed_url_fb = urlparse(url)
                            path_fb = parsed_url_fb.path.strip('/')
                            slash_count_fb = path_fb.count('/')
                            MAX_SLASHES_IN_FB_PATH = 1

                            # Exclure les chemins courants non liés à des profils/pages
                            exclude_fb_segments = ['events', 'groups', 'notes', 'photo', 'video', 'watch', 'marketplace', 'gaming', 'fundraisers', 'login', 'sharer', 'dialog', 'pages', 'stories', 'help', 'settings', 'notifications', 'messages', 'friends', 'bookmarks', 'directory']

                            if path_fb and slash_count_fb <= MAX_SLASHES_IN_FB_PATH and \
                               not path_fb.isdigit() and \
                               not any(segment in path_fb.split('/') for segment in exclude_fb_segments) and \
                               'profile.php?id=' not in url: # Exclure les anciens profils par ID pour l'instant
                                is_facebook = True
                            elif 'profile.php?id=' in url: # Gérer spécifiquement les profils par ID
                                is_facebook = True


                        except Exception as e_parse_fb:
                            pass # Ignorer les erreurs de parsing

                    # Validation pour Instagram
                    elif "instagram.com/" in cleaned_url_lower and \
                         "instagram.com/ads" not in cleaned_url_lower:
                        try:
                            parsed_url_insta = urlparse(url)
                            path_insta = parsed_url_insta.path.strip('/')
                            slash_count_insta = path_insta.count('/')
                            MAX_SLASHES_IN_INSTA_PATH = 1

                            # Exclusions pour Instagram (segments de chemin courants)
                            exclude_insta_segments_startswith = [
                                'p/', 'reel/', 'explore', 'tags', 'locations', 'developer', 'about',
                                'legal', 'api', 'accounts', 'login', 'emails', 'challenge', 'direct', 'stories'
                            ]

                            if path_insta and slash_count_insta <= MAX_SLASHES_IN_INSTA_PATH and \
                               not any(path_insta.startswith(segment) for segment in exclude_insta_segments_startswith) and \
                               '.' not in path_insta: # Exclure les chemins avec des points (fichiers)
                                is_instagram = True

                        except Exception as e_parse_insta:
                            pass # Ignorer les erreurs de parsing

                    # --- Si c'est une URL Facebook OU une URL Instagram (selon les filtres) ---
                    if is_facebook or is_instagram:
                        # Essayer d'extraire un titre significatif
                        title = url # Titre par défaut
                        try:
                            # Essayer le sélecteur h3 le plus courant
                            title_element = link_element.find_element(By.CSS_SELECTOR, 'h3')
                            title_text = title_element.text.strip()
                            if title_text:
                                title = title_text
                            else: # Si h3 est vide, essayer le texte du lien
                                link_text = link_element.text.strip()
                                if link_text:
                                    title = link_text
                        except NoSuchElementException:
                             # Si pas de h3, essayer le texte du lien directement
                             try:
                                 link_text = link_element.text.strip()
                                 if link_text:
                                     title = link_text
                             except Exception:
                                 pass # Garder l'URL comme titre par défaut
                        except Exception:
                             pass # Garder l'URL comme titre par défaut

                        # Ajouter à page_results SEULEMENT si c'est un profil FB ou Insta valide
                        # Vérifier que l'URL n'est pas juste la page d'accueil
                        if url.strip().lower() not in ["https://www.facebook.com/", "https://www.instagram.com/"]:
                            page_results.append({
                                "Titre_Google": title,
                                "URL": url,
                                "Source_Mot_Cle": keyword_combination,
                                "Type_Lien_Google": "Facebook" if is_facebook else "Instagram"
                            })

            except StaleElementReferenceException:
                # print("  [Google Search] Stale element reference, skipping this container.") # Désactivé
                pass # L'élément a disparu, on passe au suivant
            except Exception as e_container:
                # print(f"  [Google Search] Erreur mineure lors du traitement d'un conteneur: {e_container}") # Désactivé
                pass # Ignorer les erreurs mineures pour un seul conteneur

    except TimeoutException:
        print("  [Google Search] Timeout lors de l'attente des conteneurs de résultats sur la page.")
    except Exception as e:
        print(f"  [Google Search] Erreur lors de l'extraction globale des résultats de la page : {e}")

    # print(f"  [Google Search] {len(page_results)} lien(s) Facebook/Instagram extrait(s) de cette page.") # Désactivé
    return page_results


# --- Fonction Principale pour le Scraping Google ---
def scrape_google_search(driver, keyword_combinations, max_pages_per_search, google_link_types=None):
    """
    Prend une instance de driver, une liste de combinaisons de mots-clés,
    la limite de pages par recherche, et une liste optionnelle de types de liens ('facebook', 'instagram', etc.).
    Effectue les recherches Google et retourne une liste de dictionnaires
    contenant les URLs pertinentes trouvées.
    """
    print("\n--- Démarrage du scraping de recherche Google ---")

    collected_google_urls = []
    seen_urls_google_search = set()

    # --- Préparer les opérateurs 'site:' si des types de liens sont spécifiés ---
    site_operators = ""
    if google_link_types:
        # Créer une chaîne comme "site:facebook.com OR site:instagram.com"
        site_operators_list = [f"site:{link_type.strip()}.com" for link_type in google_link_types if link_type.strip()]
        if site_operators_list:
            site_operators = " OR ".join(site_operators_list)
            print(f"  [Google Search] Utilisation des opérateurs de site : {site_operators}")
    # --- Fin préparation opérateurs 'site:' ---

    if go_to_google(driver):
        for i, keyword_combination in enumerate(keyword_combinations):
            print(f"\n  [Google Search] Traitement combinaison {i+1}/{len(keyword_combinations)} : '{keyword_combination}'")

            # --- Modifier la requête de recherche avec les opérateurs 'site:' ---
            search_query = keyword_combination  # La requête de base est la combinaison
            if site_operators:
                # Ajouter les opérateurs de site à la requête
                search_query = f"{keyword_combination} ({site_operators})"
                print(f"  [Google Search] Requête Google envoyée : '{search_query}'")
            # --- Fin modification requête ---

            success = perform_search(driver, search_query)  # Utiliser la requête modifiée

            if success:
                for page_num in range(1, max_pages_per_search + 1):
                    print(f"    [Google Search] Traitement page {page_num}/{max_pages_per_search}")

                    # --- Sauvegarder le HTML de la première page pour débogage ---
                    # On le fait ici pour être sûr d'avoir le HTML des résultats
                    if page_num == 1:
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_keyword = re.sub(r'[^\w\-_\. ]', '_', keyword_combination)[:50]
                            html_path = SCREENSHOTS_DIR_GGL / f"{timestamp}_GoogleResultsP1_{safe_keyword}.html"
                            with open(html_path, "w", encoding="utf-8") as f:
                                f.write(driver.page_source)
                            print(f"    [Google Search] Code HTML de la page 1 sauvegardé dans {html_path}")
                        except Exception as e_save_html:
                            print(f"    [Google Search] Erreur lors de la sauvegarde du HTML: {e_save_html}")
                    # --- Fin sauvegarde HTML ---

                    current_page_results = extract_google_results(driver, keyword_combination)  # Passer la combinaison originale

                    # Ajouter les résultats uniques de Google à la liste de retour
                    new_urls_found_on_page = 0
                    for result in current_page_results:
                        url_to_check = result.get('URL')
                        if url_to_check and isinstance(url_to_check, str) and url_to_check not in seen_urls_google_search:
                            # Ajouter Type_Source pour identifier la source
                            mutable_result = result.copy()
                            mutable_result['Type_Source'] = 'Google'
                            collected_google_urls.append(mutable_result)
                            seen_urls_google_search.add(url_to_check)
                            new_urls_found_on_page += 1
                    print(f"    [Google Search] {new_urls_found_on_page} nouvelle(s) URL(s) pertinente(s) trouvée(s) sur cette page.")


                    # Logique pour passer à la page suivante
                    if page_num < max_pages_per_search:
                        time.sleep(random.uniform(1, 2))  # Délai avant de chercher le bouton suivant
                        try:
                            # Essayer de scroller un peu pour faire apparaître le bouton
                            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.8);")
                            time.sleep(random.uniform(0.5, 1))

                            # Sélecteur plus robuste pour le lien "Suivant"
                            next_page_link_element = WebDriverWait(driver, 7).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, 'a#pnnext, a[aria-label*="Suivant"], a[aria-label*="Next"]'))
                            ) # Note: Google change parfois ces sélecteurs. 'td.navend a' ou 'a[aria-label="Page suivante"]' sont d'autres options.
                            next_page_url = next_page_link_element.get_attribute('href')

                            if next_page_url:
                                print(f"    [Google Search] Navigation vers page {page_num + 1}")
                                driver.get(next_page_url)
                                # Attendre un élément de la page de résultats suivante
                                WebDriverWait(driver, 15).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, '#search, div.g, div.rc'))
                                )
                                time.sleep(random.uniform(2, 4)) # Pause après chargement
                            else:
                                print(f"    [Google Search] URL 'Suivant' non trouvée (attribut href vide) à la page {page_num}. Arrêt pagination.")
                                break

                        except (TimeoutException, NoSuchElementException):
                            print(f"    [Google Search] Lien 'Suivant' non trouvé ou dernière page atteinte à la page {page_num}. Arrêt pagination.")
                            break
                        except (ElementClickInterceptedException, ElementNotInteractableException):
                             print(f"    [Google Search] Lien 'Suivant' trouvé mais non cliquable (intercepté ou non interactif) à la page {page_num}. Arrêt pagination.")
                             break
                        except Exception as e_next_page:
                            print(f"    [Google Search] Erreur lors du passage page suivante : {type(e_next_page).__name__} - {e_next_page}. Arrêt pagination.")
                            break
                    else:
                        print(f"    [Google Search] Limite de {max_pages_per_search} pages atteinte pour cette combinaison.")

                # Pause entre les combinaisons de mots-clés
                print(f"  [Google Search] Fin du traitement pour '{keyword_combination}'. Pause...")
                time.sleep(random.uniform(4, 7))
            else:
                print(f"  [Google Search] Échec de la recherche initiale pour '{search_query}'. Passage à la combinaison suivante.")
                time.sleep(random.uniform(8, 12)) # Pause plus longue après un échec

        print("\n--- Fin du scraping de recherche Google ---")
        print(f"  [Google Search] Total de {len(collected_google_urls)} URLs pertinentes collectées par ce module.")
        return collected_google_urls

    else:
        print("\n--- Échec de la connexion initiale à Google. Scraping Google annulé. ---")
        return []

# --- Bloc d'exécution autonome (Optionnel pour tester ce script seul) ---
# (Le bloc if __name__ == "__main__": reste commenté car ce module est destiné à être importé)
