# facebook_search_scraper.py - Version avec UN SEUL TRY/EXCEPT par combinaison

import time
import random
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, parse_qs
import re
import sys
import traceback


# Importer les fonctions de gestion de connexion/cookies/navigation FB
try:
    import scraper.facebook_page_scraper as facebook_page_scraper
except ImportError:
    print("Erreur: Le module facebook_page_scraper.py est introuvable. Assurez-vous qu'il est dans le même dossier.")
    facebook_page_scraper = None

# --- Configuration (spécifique à la recherche FB) ---
SCROLL_PAUSE_TIME = 3
SCROLL_CHECK_COUNT = 3

SEARCH_NAME_PREFIX_REGEX = re.compile(r'^Photo de profil de\s+', re.IGNORECASE)
TRAILING_SPACE_REGEX = re.compile(r'[\s\xa0]+$')
GENERIC_NAME_CHECK_REGEX = re.compile(
    r'^\s*(?:(?:Photo de profil de|Page|Restaurant|Café|Marocain|Hamburgers|followers|J’aime|avis|\d+\.?\d*\s*km|Actuellement ouvert|Notifications)[\s\.\-\·]*)+$',
    re.IGNORECASE,
)

# --- Fonction Principale pour le Scraping de Recherche Facebook ---
def scrape_facebook_search(driver, keyword_combinations, max_results_per_search):
    """
    Prend une instance de driver, une liste de combinaisons de mots-clés,
    et la limite de résultats par recherche.
    Effectue les recherches Facebook et retourne une liste de dictionnaires
    contenant les URLs Facebook (pages/profils) trouvées.
    """
    if not facebook_page_scraper:
        print("  [Facebook Search] Module facebook_page_scraper non chargé. Scraping annulé.")
        return []

    print("\n--- Démarrage du scraping de recherche Facebook ---")

    collected_facebook_urls = []
    seen_urls_facebook_search = set()

    try:
        if not facebook_page_scraper.go_to_facebook_home(driver):
            print("  [Facebook Search] Impossible d'aller sur la page d'accueil Facebook. Scraping annulé.")
            return []
    except Exception as e:
        print(f"  [Facebook Search] Erreur inattendue lors de la navigation initiale vers FB Home: {e}. Scraping annulé.")
        return []

    for i, keyword in enumerate(keyword_combinations):
        print(f"\n  [Facebook Search] Traitement combinaison {i+1}/{len(keyword_combinations)} : '{keyword}'")
        urls_collected_for_keyword = []
        results_collected_for_keyword_count = 0

        try:
            if not facebook_page_scraper.go_to_facebook_home(driver):
                print(f"  [Facebook Search] Impossible de revenir à l'accueil FB pour recherche '{keyword}'. Skip combinaison.")
                time.sleep(random.uniform(3, 7))
                continue

            try:
                search_bar = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '[aria-label="Rechercher sur Facebook"], [aria-label="Search Facebook"]'))
                )
                time.sleep(random.uniform(0.5, 1.5))
                search_bar.click()
                search_input_active = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Rechercher sur Facebook"], input[placeholder="Search Facebook"]'))
                )
                search_input_active.send_keys(keyword)
                search_input_active.send_keys(Keys.ENTER)
                print(f"  [Facebook Search] Recherche lancée pour '{keyword}'.")
            except Exception as e:
                print(f"  [Facebook Search] Erreur lors de l'interaction avec la barre de recherche : {e}. Skip combinaison.")
                time.sleep(random.uniform(5, 10))
                continue

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[role="feed"]'))
                )
                print("  [Facebook Search] Page de résultats de recherche chargée.")
            except TimeoutException:
                print("  [Facebook Search] Timeout lors du chargement page de résultats. Skip combinaison.")
                time.sleep(random.uniform(5, 10))
                continue

            try:
                pages_filter = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//span[text()='Pages'] | //span[text()='Page']"))
                )
                time.sleep(random.uniform(0.5, 1.5))
                pages_filter.click()
                WebDriverWait(driver, 10).until(EC.url_contains("&filter=pages"))
                print("  [Facebook Search] Filtre 'Pages' appliqué.")
            except Exception as e:
                print(f"  [Facebook Search] Avertissement: Filtre 'Pages' non trouvé ou clic échoué ({type(e).__name__}).")

            last_height = driver.execute_script("return document.body.scrollHeight")
            scrolled_count = 0
            no_new_results_count = 0

            while no_new_results_count < SCROLL_CHECK_COUNT and results_collected_for_keyword_count < max_results_per_search:
                try:
                    result_containers = driver.find_elements(By.CSS_SELECTOR, '[role="feed"] div[role="article"]')
                    current_article_count_before_scroll_in_loop = len(result_containers)

                    for container in result_containers:
                        if results_collected_for_keyword_count >= max_results_per_search:
                            break

                        url = None
                        name = "Nom non trouvé"

                        try:
                            link_element = container.find_element(By.CSS_SELECTOR, 'span.xjp7ctv a[role="link"]')
                            url = link_element.get_attribute('href')

                            name_elements = container.find_elements(By.CSS_SELECTOR,
                                'div.x78zum5.xdt5ytf.xz62fqu.x16ldp7u div.xu06os2.x1ok221b span[dir="auto"] span.x1lliihq'
                            )
                            if name_elements:
                                name = name_elements[0].text.strip()
                            else:
                                aria_label = link_element.get_attribute('aria-label')
                                if aria_label:
                                    name = aria_label.strip()
                                elif link_element.text:
                                    name = link_element.text.strip()

                            cleaned_name = TRAILING_SPACE_REGEX.sub('', name).strip()
                            cleaned_name = SEARCH_NAME_PREFIX_REGEX.sub('', cleaned_name).strip()
                            if not cleaned_name or len(cleaned_name) < 2 or GENERIC_NAME_CHECK_REGEX.match(cleaned_name) or cleaned_name.isdigit():
                                name = "Nom non trouvé"

                            # Nettoyer et valider l'URL (Logique existante)
                            if url and "facebook.com/" in url:  # Déjà vérifié si c'est une URL Facebook
                                cleaned_url = None
                                is_valid_page_url = False

                                try:  # Conserver ce bloc try/except pour le parsing de l'URL
                                    parsed_url = urlparse(url)
                                    path = parsed_url.path.strip('/')  # Chemin sans les slashes au début/fin

                                    # --- Filtrage par nombre de slashes pour Facebook ---
                                    slash_count = path.count('/')
                                    MAX_SLASHES_IN_FB_PATH = 1  # Max 1 slash après le domaine (e.g., /nom_page/ ou profile.php)

                                    # Vérifier si le chemin existe ET si le nombre de slashes est inférieur ou égal au seuil
                                    # ET si ce n'est pas une URL mobile (m.facebook.com)
                                    if path and slash_count <= MAX_SLASHES_IN_FB_PATH and not url.startswith("https://m.facebook.com"):
                                        # Gérer spécifiquement les URLs de profil au format /profile.php?id=
                                        if path == 'profile.php':
                                            query_params = parse_qs(parsed_url.query)
                                            if 'id' in query_params and query_params['id']:
                                                cleaned_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{path}?id={query_params['id'][0]}"
                                                is_valid_page_url = True
                                        # Gérer les URLs de page/profil au format /nom_page
                                        elif path and not path.isdigit():  # S'assurer que le chemin n'est pas juste un ID numérique
                                            cleaned_url = f"{parsed_url.scheme}://{parsed_url.netloc}/{path}"
                                            is_valid_page_url = True
                                    # else:
                                        # print(f"      [Facebook Search] URL Facebook filtrée (slashes > {MAX_SLASHES_IN_FB_PATH} ou m.facebook.com): {url}")  # Optionnel

                                except Exception as e_parse:
                                    # print(f"    [Facebook Search] Erreur parsing URL: {url} - {e_parse}")  # Optionnel
                                    cleaned_url = None
                                    is_valid_page_url = False  # Marquer comme non valide si parsing échoue

                                # Si l'URL est valide (format Page/Profil basé sur slashes) et si un nom pertinent a été trouvé
                                if cleaned_url and is_valid_page_url and name != "Nom non trouvé":
                                    if cleaned_url not in seen_urls_facebook_search:
                                        collected_facebook_urls.append({
                                            "name_from_search": name,  # Nom trouvé dans la recherche FB
                                            "url": cleaned_url,  # Utiliser 'url' en minuscule pour la cohérence avec google_search_scraper output
                                            "source_keyword": keyword
                                        })
                                        seen_urls_facebook_search.add(cleaned_url)  # Ajouter à l'ensemble local
                                        urls_collected_for_keyword.append(cleaned_url)  # Ajouter à la liste locale pour cette combinaison
                                        results_collected_for_keyword_count += 1  # Incrémenter le compteur
                        except Exception:
                            pass

                    if results_collected_for_keyword_count >= max_results_per_search:
                        break

                except Exception:
                    pass

                scroll_delay = random.uniform(SCROLL_PAUSE_TIME * 0.8, SCROLL_PAUSE_TIME * 1.2)
                time.sleep(scroll_delay)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                try:
                    WebDriverWait(driver, scroll_delay + 5).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, '[role="feed"] div[role="article"]')) > current_article_count_before_scroll_in_loop
                    )
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    last_height = new_height
                    no_new_results_count = 0
                except TimeoutException:
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        no_new_results_count += 1
                    else:
                        no_new_results_count = 0
                        last_height = new_height

                if no_new_results_count >= SCROLL_CHECK_COUNT:
                    print(f"  [Facebook Search] Arrêt du défilement après {SCROLL_CHECK_COUNT} fois sans nouveau contenu.")
                    break

            print(f"  [Facebook Search] {results_collected_for_keyword_count} URLs collectées pour la combinaison '{keyword}'.")

        except Exception as e:
            print(f"  [Facebook Search] ERREUR PENDANT LE PROCESSUS DE RECHERCHE POUR '{keyword}' : {type(e).__name__} - {e}")
            time.sleep(random.uniform(5, 10))
            pass

    print("\n--- Fin du scraping de recherche Facebook ---")
    print(f"  [Facebook Search] Total de {len(collected_facebook_urls)} URLs Facebook collectées au total.")
    return collected_facebook_urls
