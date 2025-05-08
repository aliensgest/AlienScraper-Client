# clean.py

import os
import csv
import glob
import json # Needed to parse AI response
import re   # Needed for regex parsing/cleaning
import traceback # For error logging
import time # For potential retries or delays
import sys # To exit if not run autonomously or confirmed

# --- Import Google Generative AI Library ---
import google.generativeai as genai

# --- Configuration ---
LEADS_CSV_FILE = "leads.csv"
RESULTS_FOLDER_PATTERN = "Scraping_Results_*"

# --- En-têtes pour le fichier Leads CSV (Format Final Simplifié) ---
# Keep the same headers as the detailed CSV for now, filter later if needed
# Using the same headers as main_scraper's FINAL_CSV_HEADERS is safer
# Assume main_scraper.py defines FINAL_CSV_HEADERS, but for standalone clean.py, define a standard set
LEADS_CSV_HEADERS = [
    "Nom du tiers", "Nom alternatif", "État", "Code client", "Adresse", "Téléphone",
    "Url", "Email", "Client", "Fournisseur", "Date création", "Facebook", "Instagram",
    "Whatsapp", "URL_Originale_Source", "Bio", "Source_Mot_Cle", "Type_Source",
    "Nom_Trouve_Recherche", "Titre_Trouve_Google", "Type_Lien_Google",
    "Statut_Scraping_Detail", "Message_Erreur_Detail",
    "Nombre de Publications", "Nombre de Followers", "Nombre de Suivis", # Keep these from detailed headers
    "Type de Page" # Add Page Type header if it's not already there
]
# Ensure Type de Page is in headers if it wasn't included in the default block
if "Type de Page" not in LEADS_CSV_HEADERS:
    LEADS_CSV_HEADERS.append("Type de Page")


# --- Configure the Generative AI API ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        print("[Clean - Gemini API] Google API Key loaded from environment variable.")
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        print("[Clean - Gemini API] Gemini 1.5 Flash model loaded.")
    except Exception as e:
        print(f"[Clean - Gemini API] ERROR loading Gemini model: {e}")
        print("[Clean - Gemini API] AI consolidation will be skipped.")
        gemini_model = None
else:
    print("[Clean - Gemini API] WARNING: GOOGLE_API_KEY environment variable not set.")
    print("[Clean - Gemini API] AI consolidation will be skipped.")
    gemini_model = None

# --- Regex for cleaning phone numbers (needed here for post-AI check) ---
CLEAN_PHONE_REGEX = re.compile(r'[\s().\-+📲📞☎️]') # Use the same regex as in scrapers

# --- Function for Moroccan Phone Reformatting (needed here for post-AI check) ---
def format_phone_to_whatsapp_link(phone_number):
    """
    Cleans a phone number and formats it into a wa.me link, applying Moroccan +212 format heuristic.
    Returns a wa.me link string or "Not Generated" if the input is invalid.
    """
    if not phone_number or not isinstance(phone_number, str) or phone_number in ["Not Found", "N/A", "Not Generated", ""]:
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


# --- Function to process and consolidate entries with AI ---
def consolidate_with_gemini(list_of_entries):
    """
    Sends a list of prospect entries to Google Gemini API to identify duplicates
    and consolidate information into unique records. Applies specific formatting rules.
    Returns a list of consolidated dictionaries or the original list if AI fails/not loaded.
    """
    if gemini_model is None or not list_of_entries:
        print("[Clean - Gemini API] Model not loaded or no entries to process. Skipping AI consolidation.")
        return list_of_entries # Return original list if AI is not available or list is empty

    print(f"[Clean - Gemini API] Sending {len(list_of_entries)} entries to AI for consolidation and cleaning...")

    # Craft the prompt for the AI model
    # Added emphasis on strict JSON format and escaping special characters.
    prompt = f"""
Analyze the following list of prospect entries, provided as a JSON string. Each entry is a dictionary with fields like 'Nom du tiers', 'Téléphone', 'Adresse', 'Facebook', 'Instagram', 'Whatsapp', 'URL_Originale_Source', etc.

Identify entries that correspond to the same real-world entity (person, business, page, etc.) based on similarity in names, URLs (Facebook, Instagram, Website, Whatsapp), phone numbers, email addresses, and addresses. Consider entries with similar names and/or locations and/or contact info as potential duplicates.

For each group of entries that belong to the same entity, create ONE consolidated entry.
In the consolidated entry, merge the information from all entries in the group, applying these rules and formats:

- **Prioritization:** For each field, choose the most complete and specific value available among the entries in the group. Prioritize real data over placeholder values ("Not Found", "N/A", "N/A (Insta)", "N/A (FB)", "Not Generated", "Nom Inconnu", "Pas encore évalué (0 avis)", empty strings, None). If multiple real values exist (e.g., multiple phone numbers), choose the one that seems most descriptive or longest (e.g., for 'Adresse', 'Bio'). For URLs, prefer URLs that look like profile/page links over generic domain links if multiple are present.
- **'Nom du tiers'**: Choose the most specific and descriptive name found. Avoid generic terms like "Page", "Boutique", "Magasin" if a proper name is available.
- **'Nom alternatif'**: If an Instagram username (@...) is present and different from the 'Nom du tiers', use that. Otherwise, use another alternative name found if it's different from the 'Nom du tiers' and not a generic term. Use "N/A" if no suitable alternative is found.
- **'Téléphone'**: Extract and standardize phone numbers. **Format all extracted Moroccan phone numbers to '+212NNNNNNNNN' format.** If a number doesn't seem Moroccan or standard international, keep the extracted format or the most common format found in the entries. Use "Not Found" if no phone is identified.
- **'Whatsapp'**: **Format all WhatsApp links to 'https://wa.me/+212NNNNNNNNN' if they are Moroccan numbers, or 'https://wa.me/NNNNNNNNN' for other valid numbers.** If a wa.me link is directly found and seems valid, prioritize it. If a valid phone number is found but no direct wa.me link, create the wa.me link from the phone number. Use "Not Found" if no WhatsApp link or valid phone is identified.
- **'Url' (Website):** Prioritize URLs that look like main websites (e.g., domain.com) over social media links or very specific deep links. Use "Not Found" if no valid website URL is identified.
- **'Facebook', 'Instagram':** Extract and clean the main profile/page URL. Remove query parameters like '?locale=...', '?__d=...'. For Facebook, keep 'profile.php?id=...' format if applicable.
- **'Adresse':** Choose the most complete address. Standardize formatting if possible. Use "N/A" if no address is identified.
- **'Bio'**: Consolidate and summarize the descriptive text, removing noise, generic phrases, and redundant contact info already in dedicated fields. **Ensure all string values within the JSON output, especially in the 'Bio', are properly escaped according to JSON rules (e.g., backslashes, quotes, newlines, and complex Unicode characters).** Use "N/A" if no descriptive text is found.
- **'Nombre de Publications', 'Nombre de Followers', 'Nombre de Suivis'**: Extract the numbers, clean them (remove commas, 'k', spaces), and keep as string digits. Use "N/A" if not found.
- **'URL_Originale_Source'**: Create a LIST of all unique original source URLs that contributed to this consolidated entry.
- **'Statut_Scraping_Detail'**: Summarize the statuses (e.g., "Success", "Partial Success; Errors on some entries"). If all entries were 'Skipped - Looks like Post/Photo URL' or 'Error', you can reflect that.
- **'Message_Erreur_Detail'**: Combine error messages if any, separating them (e.g., "Error A; Error B").

**Filtering:** After creating the consolidated entries, **exclude** any consolidated entry that corresponds to a group where **ALL** original entries had a 'Statut_Scraping_Detail' of "Skipped - Looks like Post/Photo URL", "Redirected to login/checkpoint/error page", "Error Calling Page Scraper", or "Critical Element Not Found". This ensures we filter out invalid/failed scraping attempts.

Return the list of **filtered and consolidated** entries as a JSON list of dictionaries. **The output must be ONLY the JSON list, nothing before or after, and it must be strictly valid JSON.**

Analyze the following list of prospect entries (provided as a JSON string):

{json.dumps(list_of_entries, indent=2)}
"""

    try:
        # Make the API call with retries in case of transient errors or timeouts
        max_retries = 5 # Increased retries
        for attempt in range(max_retries):
            try:
                response = gemini_model.generate_content(prompt, request_options={'timeout': 150}) # Increased timeout again
                response_text = response.text.strip()

                # Attempt to isolate the JSON list part more robustly
                # Look for the first [ and the last ]
                first_bracket = response_text.find('[')
                last_bracket = response_text.rfind(']') # Use rfind to get the last one

                if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
                    json_string = response_text[first_bracket : last_bracket + 1]
                    # Clean common prefix/suffix markdown like ```json\n or ```
                    json_string = json_string.replace('```json\n', '').replace('```', '').strip()

                    # Further heuristic cleaning for problematic characters if simple parsing fails
                    # This is risky, but might help with unexpected characters
                    # Use a more targeted approach if possible
                    # Example: Replace common unescaped Unicode or control characters if they cause errors
                    # BE CAREFUL: This might corrupt valid data if not done correctly.
                    # Let's try a very basic approach first: remove non-ASCII and non-standard JSON characters
                    # This might remove emojis, which is not ideal, but might make JSON parsing work.
                    # A better approach is to ensure the AI escapes them. Let's trust the AI prompt more.
                    # If JSONDecodeError still occurs with specific characters, we might need to add
                    # specific replacements based on the error message (e.g., for \ud83d\udc40).
                    # For now, let's just keep the basic markdown cleanup and assume the AI handles escaping.


                    try:
                        # Try loading JSON with a more permissive parser if possible, or just standard
                        # Standard json.loads is usually best if the input string is corrected.
                        consolidated_data = json.loads(json_string)
                        print(f"[Clean - Gemini API] Successfully consolidated {len(list_of_entries)} entries into {len(consolidated_data)} unique entities.")
                        return consolidated_data
                    except json.JSONDecodeError as json_e:
                        print(f"[Clean - Gemini API] ERROR decoding JSON list from AI response (Attempt {attempt+1}/{max_retries}): {json_e}")
                        print(f"[Clean - Gemini API] Raw AI response text (extracted JSON string): {json_string}") # Show the extracted part
                        # If JSON decode fails, retry
                        time.sleep(10 * (attempt + 1)) # Longer wait before retrying
                        continue # Try the next attempt
                else:
                    print(f"[Clean - Gemini API] WARNING: Could not find JSON list object ([...]) in AI response (Attempt {attempt+1}/{max_retries}).")
                    print(f"[Clean - Gemini API] Raw AI response text: {response_text}")
                    # If JSON list is not found, retry
                    time.sleep(10 * (attempt + 1)) # Longer wait before retrying
                    continue # Try the next attempt

            except Exception as e_api:
                print(f"[Clean - Gemini API] ERROR during AI consolidation API call (Attempt {attempt+1}/{max_retries}): {type(e_api).__name__} - {e_api}")
                time.sleep(10 * (attempt + 1)) # Longer wait before retrying
                continue # Try the next attempt

        print(f"[Clean - Gemini API] Failed to get a valid response after {max_retries} attempts. Returning original list.")
        return list_of_entries # Return original list if all retries fail

    except Exception as e_outer:
        print(f"[Clean - Gemini API] CRITICAL ERROR during AI consolidation process: {type(e_outer).__name__} - {e_outer}")
        return list_of_entries # Return original list on critical error


# --- Function to consolidate and filter leads ---
def consolidate_and_filter_leads():
    print("\n--- D\u00e9marrage de la consolidation et du filtrage des leads ---")

    # We will load existing leads and combine them with new entries before AI consolidation
    existing_leads_data = []

    # --- Charger les données existantes de leads.csv (if file exists) ---
    if os.path.exists(LEADS_CSV_FILE):
        print(f"Chargement des leads existants depuis '{LEADS_CSV_FILE}'...")
        try:
            with open(LEADS_CSV_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                # Convert orderedDict to dict
                existing_leads_data = [dict(row) for row in reader]
            print(f"{len(existing_leads_data)} leads existants chargés.")
        except Exception as e:
            print(f"Erreur lors du chargement de '{LEADS_CSV_FILE}' : {e}. Le fichier sera ignoré.")
            existing_leads_data = []


    # --- Read data from all recent results CSVs ---
    all_result_entries = []
    result_folders = glob.glob(RESULTS_FOLDER_PATTERN)
    if not result_folders:
        print(f"Aucun dossier de r\u00e9sultats correspondant au pattern '{RESULTS_FOLDER_PATTERN}' trouvé.")

    all_result_files = []
    for folder in result_folders:
        csv_files_in_folder = glob.glob(os.path.join(folder, "*.csv"))
        all_result_files.extend(csv_files_in_folder)

    if not all_result_files and not existing_leads_data:
        print("Aucun fichier de résultats et aucun lead existant à traiter.")
        return # Exit if no data to process

    if not all_result_files and existing_leads_data:
        print("Aucun nouveau fichier de r\u00e9sultats trouv\u00e9.")
        # Even if no new files, consolidate existing ones in case AI finds new duplicates
        # Or simply save existing if AI is not available
        if gemini_model:
             print("[Clean] Re-consolidating existing leads with AI...")
             all_entries_for_consolidation = existing_leads_data
        else:
             # If no new files and no AI, just save existing leads without changes
             print("[Clean] No new results and AI not available. Saving existing leads without changes.")
             save_leads_to_csv(existing_leads_data, LEADS_CSV_FILE, LEADS_CSV_HEADERS)
             return # Exit after saving existing leads if no AI/new data


    print(f"\nTrouv\u00e9 {len(all_result_files)} fichier(s) de r\u00e9sultats CSV \u00e0 traiter.")

    # Read all new entries from result files
    for file_path in all_result_files:
        print(f"Traitement du fichier : {file_path}")
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                 # Convert orderedDict to dict and add to the list
                for row in reader:
                     all_result_entries.append(dict(row))
        except Exception as e:
            print(f"Erreur lors de la lecture ou du traitement du fichier '{file_path}' : {e}.")

    print(f"[Clean] Read {len(all_result_entries)} new entries from result files.")

    # Combine existing leads and new entries into a single list for AI processing
    # If AI is not available, this list will be filtered directly later.
    all_entries_for_consolidation = existing_leads_data + all_result_entries
    print(f"[Clean] Total entries for consolidation pool: {len(all_entries_for_consolidation)}")


    # --- Use AI to consolidate entries if model is available ---
    if gemini_model:
         consolidated_entries = consolidate_with_gemini(all_entries_for_consolidation)
    else:
         print("[Clean] Skipping AI consolidation because Gemini model is not available.")
         # If AI is not available, the "consolidation" is just the raw list of entries
         consolidated_entries = all_entries_for_consolidation


    # --- Apply Filtering Criteria and Final Deduplication to Consolidated/Raw Entries ---
    final_leads_list_for_save = []
    seen_original_urls_in_final_leads = set() # Use a set to prevent accidental duplication in final list


    print("[Clean] Applying lead filtering and final deduplication...")
    filtered_and_deduplicated_leads = []

    # Statut d'erreur/saut à filtrer
    error_statuses_to_filter = [
        "Skipped - Looks like Post/Photo URL",
        "Redirected to login/checkpoint/error page",
        "Error Calling Page Scraper",
        "Timeout loading page elements", # Added Timeout as potentially unreliable
        "Critical Element Not Found" # Added Critical Element Not Found
    ]

    for entry in consolidated_entries:
        # Ensure entry is a dictionary and has required fields for filtering
        if not isinstance(entry, dict) or 'URL_Originale_Source' not in entry or 'Statut_Scraping_Detail' not in entry:
             print(f"[Clean - Filter] Skipping invalid entry (missing fields): {entry}")
             continue

        # --- Check if this entry should be filtered out based on status ---
        # If the status indicates a failed/skipped scrape attempt, we filter it out.
        # This check relies on the AI having correctly summarized the status when consolidating.
        consolidated_status = entry.get('Statut_Scraping_Detail')
        should_filter_by_status = False
        if consolidated_status:
             # Check if the consolidated status contains *only* error/skipped indicators
             # This is a heuristic and might need tuning.
             # A simple approach is to filter if the consolidated status is exactly one of the error statuses.
             # A more complex approach would check if *all* original statuses were errors.
             # Let's stick to the simpler approach for now based on consolidated status.
             if consolidated_status in error_statuses_to_filter:
                  should_filter_by_status = True
             # Optional: Check if the status indicates mixed results but the primary original URL was an error? More complex.

        if should_filter_by_status:
             print(f"[Clean - Filter] Excluding entry with status: {consolidated_status} for URL(s): {entry.get('URL_Originale_Source')}")
             continue # Skip this entry


        # --- Handle URL_Originale_Source for deduplication set ---
        # Add all original URLs associated with this consolidated entry to the seen set.
        original_urls = entry.get('URL_Originale_Source')
        urls_to_check = []
        csv_original_url = "N/A" # Default for CSV column

        if isinstance(original_urls, list):
             urls_to_check = original_urls
             csv_original_url = original_urls[0] if original_urls else "N/A" # Use first URL from list for CSV column
             # Clean URLs in list and add to set
             cleaned_urls_in_list = [url.strip() for url in urls_to_check if isinstance(url, str) and url.strip()]
             urls_to_check = cleaned_urls_in_list # Use cleaned list for duplication check
        elif isinstance(original_urls, str) and original_urls.strip():
             urls_to_check = [original_urls.strip()]
             csv_original_url = original_urls.strip() # Use the string URL for CSV column
        # else: print(f"[Clean - Filter] Entry with invalid or missing URL_Originale_Source for deduplication: {entry}") # Too verbose, continue to next checks


        # Check if *any* of the original URLs for this consolidated entry have already been added
        is_duplicate_by_url = False
        for url in urls_to_check:
            if url in seen_original_urls_in_final_leads:
                 is_duplicate_by_url = True
                 break

        if is_duplicate_by_url:
             # print(f"[Clean - Filter] Excluding entry as duplicate based on original URL(s): {urls_to_check}") # Too verbose
             continue # Skip this entry if any of its original URLs were already seen


        # --- If not filtered by status and not a duplicate by URL, apply lead criteria ---
        has_email = entry.get('Email') not in ["Not Found", "", None, "N/A"] # Added N/A
        has_whatsapp = entry.get('Whatsapp') not in ["Not Found", "", None, "N/A", "Not Generated", "Invalid Phone Format for WhatsApp"] # Added more placeholders
        has_website = entry.get('Url') not in ["Not Found", "", None, "N/A"] # Added N/A
        has_facebook = entry.get('Facebook') not in ["Not Found", "", None, "N/A"] # Added N/A
        has_instagram = entry.get('Instagram') not in ["Not Found", "", None, "N/A"] # Added N/A
        # Check for valid name (not placeholder) and address/URL presence
        has_valid_name = entry.get('Nom du tiers') not in ["Not Found", "Nom Inconnu", "Nom Inconnu (Scraping skipped/failed)", "", None, "N/A"] # Added N/A
        has_address_or_url = entry.get('Adresse') not in ["Not Found", "N/A", "N/A (Insta)", "", None] or entry.get('Url') not in ["Not Found", "", None, "N/A"]


        # A lead must have at least one contact info OR a valid name and an address/URL
        is_a_lead = (has_email or has_whatsapp or has_website or has_facebook or has_instagram) or \
                    (has_valid_name and has_address_or_url)

        if is_a_lead:
            # --- Format the entry for CSV saving ---
            formatted_entry = {}
            # Ensure all headers are present, use consolidated/cleaned values or default
            for header in LEADS_CSV_HEADERS:
                 # Use .get() with a default that won't interfere with subsequent checks
                 # Default to None or empty string and handle placeholders explicitly
                 value = entry.get(header, None) # Get consolidated value, default to None

                 # Apply specific formatting rules and default checks
                 if header == 'Téléphone':
                      # Ensure phone number is in a consistent format, e.g., +212XXXXXXXXX
                      if isinstance(value, str) and value not in ["Not Found", "N/A", "", None]:
                           cleaned_phone = CLEAN_PHONE_REGEX.sub('', value).strip()
                           if cleaned_phone:
                                # Attempt to format using the function. The function returns a wa.me link,
                                # but we need the number part for the 'Téléphone' field.
                                formatted_phone_link = format_phone_to_whatsapp_link(cleaned_phone)
                                if formatted_phone_link != "Not Generated":
                                     # Extract number from the formatted link (removes wa.me/+/)
                                     num_match = re.search(r"wa\.me/\+?(\d+)", formatted_phone_link)
                                     if num_match:
                                         # Store as +number for consistency
                                         formatted_entry[header] = "+" + num_match.group(1)
                                     else:
                                         # Fallback to original cleaned number if cannot extract from link
                                         formatted_entry[header] = "+" + cleaned_phone if not cleaned_phone.startswith('+') else cleaned_phone
                                else:
                                     # Cannot format reliably, just store the cleaned number
                                     formatted_entry[header] = cleaned_phone
                           else:
                                formatted_entry[header] = "Not Found" # Phone became empty after cleaning
                      else:
                           formatted_entry[header] = "Not Found" # Keep Not Found default

                 elif header == 'Whatsapp':
                      # Ensure it's a valid wa.me link and in the correct format
                      # Prioritize the WhatsApp link found directly by the scraper/AI if it's valid.
                      # Otherwise, generate from the phone number if the phone is valid.
                      whatsapp_link_from_scraper_ai = entry.get('Whatsapp', None) # Get the value AI consolidated for 'Whatsapp'
                      phone_number_for_whatsapp_gen = formatted_entry.get('Téléphone', entry.get('Téléphone', None)) # Get the processed or raw phone

                      cleaned_whatsapp_link_from_scraper_ai = None
                      if isinstance(whatsapp_link_from_scraper_ai, str) and whatsapp_link_from_scraper_ai not in ["Not Found", "N/A", "Not Generated", "", None]:
                           # Check if the consolidated WA link from AI is a valid wa.me link format
                           wa_match_consolidated = re.search(r"https?://wa\.me/\+?(\d+)", whatsapp_link_from_scraper_ai, re.IGNORECASE)
                           if wa_match_consolidated:
                                # It's a valid wa.me link format, use it and format it
                                cleaned_whatsapp_link_from_scraper_ai = format_phone_to_whatsapp_link(wa_match_consolidated.group(1))
                           # else: print(f"[Clean - Filter] Consolidated WA link from AI doesn't match wa.me format: {whatsapp_link_from_scraper_ai}") # Too verbose


                      if cleaned_whatsapp_link_from_scraper_ai and cleaned_whatsapp_link_from_scraper_ai != "Not Generated":
                           # Use the cleaned WA link from scraper/AI if it was a valid wa.me link
                           formatted_entry[header] = cleaned_whatsapp_link_from_scraper_ai
                      else:
                           # If no valid WA link from scraper/AI, try generating from the phone number
                           if isinstance(phone_number_for_whatsapp_gen, str) and phone_number_for_whatsapp_gen not in ["Not Found", "N/A", "", None]:
                                # Use the function to format the phone number into a WA link
                                generated_from_phone = format_phone_to_whatsapp_link(CLEAN_PHONE_REGEX.sub('', phone_number_for_whatsapp_gen)) # Clean before formatting
                                if generated_from_phone != "Not Generated":
                                     formatted_entry[header] = generated_from_phone
                                else:
                                     formatted_entry[header] = "Not Found" # Cannot generate valid WA link from phone
                           else:
                                formatted_entry[header] = "Not Found" # No phone number available to generate WA link


                 elif header == 'URL_Originale_Source':
                      # Format the list of original URLs for the CSV column
                      if isinstance(original_urls, list):
                           formatted_entry[header] = "; ".join([url.strip() for url in original_urls if isinstance(url, str) and url.strip()])
                      elif isinstance(original_urls, str):
                           formatted_entry[header] = original_urls.strip()
                      else:
                           formatted_entry[header] = "N/A" # Default if no original URL

                 elif header == 'Nom du tiers':
                      # Ensure default if still empty or placeholder after consolidation
                      if isinstance(value, str) and value.strip() in ["Not Found", "Nom Inconnu", "Nom Inconnu (Scraping skipped/failed)", ""]:
                          formatted_entry[header] = "Nom Inconnu"
                      else:
                          formatted_entry[header] = value # Keep consolidated value

                 elif header == 'Nom alternatif':
                      # Ensure default is N/A for Nom alternatif
                      if isinstance(value, str) and value.strip() in ["Not Found", ""]:
                           formatted_entry[header] = "N/A"
                      else:
                           formatted_entry[header] = value # Keep consolidated value

                 elif header in ['Adresse', 'Bio', 'Type de Page', 'Source_Mot_Cle', 'Type_Source', 'Nom_Trouve_Recherche', 'Titre_Trouve_Google', 'Type_Lien_Google']:
                     # Ensure N/A default for these fields
                      if isinstance(value, str) and value.strip() in ["Not Found", ""]:
                           formatted_entry[header] = "N/A"
                      else:
                           formatted_entry[header] = value # Keep consolidated value

                 elif header in ['Nombre de Publications', 'Nombre de Followers', 'Nombre de Suivis']:
                     # Ensure N/A default for counts
                      if isinstance(value, str) and value.strip() in ["Not Found", ""]:
                           formatted_entry[header] = "N/A"
                      else:
                           # Clean count numbers if necessary (remove non-digits except k) - AI should do this, but as safety
                           if isinstance(value, str):
                                cleaned_count = re.sub(r'[\s,kK\u202f\.]', '', value).strip()
                                if cleaned_count.isdigit(): formatted_entry[header] = cleaned_count
                                elif re.match(r'^\d+k$', cleaned_count, re.IGNORECASE):
                                     try:
                                          num_part = cleaned_count[:-1]
                                          formatted_entry[header] = str(int(float(num_part) * 1000))
                                     except ValueError: formatted_entry[header] = "N/A"
                                else: formatted_entry[header] = "N/A"
                           else: formatted_entry[header] = "N/A"


                 elif header in ['Email', 'Url', 'Facebook', 'Instagram']:
                     # Ensure Not Found default for these URL/contact fields
                      if isinstance(value, str) and value.strip() == "":
                           formatted_entry[header] = "Not Found"
                      else:
                           formatted_entry[header] = value # Keep consolidated value

                 elif header in ['Statut_Scraping_Detail', 'Message_Erreur_Detail']:
                     # Keep consolidated status/message, ensure empty string default
                     formatted_entry[header] = value if isinstance(value, str) else ""

                 else:
                     # For all other headers (like État, Client, Fournisseur, Date création, Code client)
                     # Take the value directly, ensuring it's not None
                     formatted_entry[header] = value if value is not None else ""


            # Add the original URLs to the seen set AFTER successfully processing the entry
            for url in urls_to_check:
                 if url: # Add only non-empty urls
                      seen_original_urls_in_final_leads.add(url)


            filtered_and_deduplicated_leads.append(formatted_entry) # Add the formatted entry


    print(f"\nTotal de leads (consolid\u00e9s, filtr\u00e9s et d\u00e9dupliqu\u00e9s) : {len(filtered_and_deduplicated_leads)}")

    # --- Sauvegarder le fichier leads.csv mis \u00e0 jour ---
    if filtered_and_deduplicated_leads:
        save_leads_to_csv(filtered_and_deduplicated_leads, LEADS_CSV_FILE, LEADS_CSV_HEADERS)
    else:
        print("Aucun lead \u00e0 sauvegarder dans leads.csv.")

# --- Fonction utilitaire pour sauvegarder le fichier leads.csv ---
def save_leads_to_csv(leads_list, filename, headers):
    print(f"\nSauvegarde du fichier leads.csv : {filename}...")
    if not leads_list:
        print("Aucune donn\u00e9e \u00e0 sauvegarder.")
        return

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            # Ensure headers match the keys in the dictionaries
            # Safest to get headers from the first entry if leads_list is not empty,
            # or use a predefined list if you're sure of the structure.
            # Using LEADS_CSV_HEADERS defined above.
            writer = csv.DictWriter(csvfile, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(leads_list)
        print(f"Fichier leads.csv sauvegard\u00e9 : '{filename}'")
    except Exception as e:
        print(f"Erreur lors de la sauvegarde du fichier leads.csv '{filename}' : {e}")
        traceback.print_exc()

# --- Bloc d'ex\u00e9cution autonome pour le script clean.py ---
if __name__ == "__main__":
    print("--- D\u00e9marrage du script clean.py ---")
    # Option pour lancer le nettoyage manuellement
    while True:
        run_clean = input("Voulez-vous lancer le processus de nettoyage et consolidation des leads ? (oui/non) : ").strip().lower()
        if run_clean in ['oui', 'o', 'yes', 'y']:
            # Ensure AI is loaded before proceeding if AI consolidation is needed
            if gemini_model:
                 try:
                      consolidate_and_filter_leads()
                      break # Exit the loop after running
                 except Exception as e_clean_run:
                      print(f"Erreur critique lors de l'ex\u00e9cution de consolidate_and_filter_leads: {e_clean_run}")
                      traceback.print_exc()
                      break # Exit loop on critical error
            else:
                 print("Le mod\u00e8le Gemini n'a pas pu \u00eatre charg\u00e9. Impossible d'ex\u00e9cuter la consolidation AI.")
                 print("Veuillez configurer la variable d'environnement GOOGLE_API_KEY.")
                 break # Exit the loop if AI is required but not available

        elif run_clean in ['non', 'n', 'no']:
            print("Processus de nettoyage annul\u00e9.")
            break # Exit the loop without running
        else:
            print("R\u00e9ponse invalide. Veuillez r\u00e9pondre par 'oui' ou 'non'.")


    print("\n--- Fin du script clean.py ---")