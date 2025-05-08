import csv
import os
from pathlib import Path
import re # Import regex for phone number cleaning
import config # Importer la configuration centralisée

# --- Configuration ---
# output_dir sera défini dans la fonction main basé sur le chemin d'entrée réel

# Noms des colonnes à extraire dans le fichier d'entrée
facebook_col = "Facebook"
instagram_col = "Instagram"
email_col = "Email"
phone_col = "Téléphone"

# Noms des fichiers de sortie et leurs en-têtes
output_files_config = {
    "facebook": {"filename": "facebook_links.csv", "header": ["Facebook Link"]},
    "instagram": {"filename": "instagram_links.csv", "header": ["Instagram Link"]},
    "email": {"filename": "emails.csv", "header": ["Email"]},
    "phone": {"filename": "phone_numbers.csv", "header": ["Phone Number"]},
}
# ---------------------

def read_existing_data(filepath, header):
    """Lit les données d'un fichier CSV existant et les retourne dans un set."""
    data_set = set()
    if filepath.exists():
        try:
            # Utiliser 'utf-8-sig' pour gérer le BOM potentiel
            with open(filepath, 'r', newline='', encoding='utf-8-sig') as f_in:
                reader = csv.reader(f_in)
                # Lire l'en-tête pour vérifier (optionnel) et passer à la ligne suivante
                try:
                    existing_header = next(reader)
                    if existing_header != header:
                        print(f"  [Extract Leads] Avertissement : L'en-tête du fichier existant {filepath.name} ({existing_header}) ne correspond pas à l'attendu ({header}). Il sera écrasé.")
                except StopIteration:
                    pass # Fichier vide
                except Exception as e_header:
                    print(f"  [Extract Leads] Erreur lors de la lecture de l'en-tête de {filepath.name}: {e_header}")

                # Lire les données restantes
                for row in reader:
                    if row: # S'assurer que la ligne n'est pas vide
                        data_set.add(row[0].strip()) # Nettoyer les espaces potentiels
        except Exception as e:
            print(f"  [Extract Leads] Erreur lors de la lecture du fichier existant {filepath}: {e}")
    return data_set

def write_data_to_csv(filepath, header, data_set):
    """Écrit les données d'un set dans un fichier CSV."""
    # Trier les données pour une sortie cohérente (optionnel)
    sorted_data = sorted(list(data_set))
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as f_out:
            writer = csv.writer(f_out)
            writer.writerow(header) # Écrire l'en-tête
            for item in sorted_data:
                writer.writerow([item]) # Écrire chaque élément comme une ligne
        print(f"  [Extract Leads] Fichier '{filepath.name}' sauvegardé avec {len(sorted_data)} entrées uniques.")
    except Exception as e:
        print(f"  [Extract Leads] Erreur lors de l'écriture du fichier {filepath}: {e}")

def format_phone_number(phone_str):
    """Nettoie et formate un numéro de téléphone pour ajouter '+'."""
    if not phone_str or not isinstance(phone_str, str) or phone_str.lower() in ['not found', 'n/a', 'non trouvé']:
        return None

    # Garde seulement les chiffres et le '+' initial s'il existe
    cleaned_phone = re.sub(r'[^\d+]', '', phone_str)

    # Si après nettoyage il ne reste que '+' ou rien, ou pas assez de chiffres
    if not cleaned_phone or cleaned_phone == '+' or sum(c.isdigit() for c in cleaned_phone) < 7:
        return None

    # Ajouter '+' s'il n'est pas déjà là
    if not cleaned_phone.startswith('+'):
        # Heuristique simple: si ça commence par 212 et a la bonne longueur, c'est probablement marocain sans le +
        if cleaned_phone.startswith('212') and len(cleaned_phone) >= 11:
             cleaned_phone = '+' + cleaned_phone
        # Heuristique simple: si ça commence par 0 et a 9 ou 10 chiffres, on suppose Maroc et ajoute +212
        elif cleaned_phone.startswith('0') and len(cleaned_phone) in [9, 10]:
             cleaned_phone = '+212' + cleaned_phone[1:]
        else:
             # Pour les autres cas, on ajoute juste '+' devant (peut nécessiter ajustement selon les pays)
             cleaned_phone = '+' + cleaned_phone

    return cleaned_phone


def main(input_file_path=None):
    """
    Fonction principale pour extraire les données de leads.csv.
    :param input_file_path: Chemin vers le fichier leads.csv (Path object ou str).
                              Si None, utilise DEFAULT_INPUT_CSV_PATH.
    """
    if input_file_path:
        input_csv_path = Path(input_file_path)
    else:
        input_csv_path = config.LEADS_CSV_FINAL_PATH # Utilise le chemin depuis config.py par défaut

    if not input_csv_path.is_file():
        print(f"[Extract Leads] Erreur : Le fichier d'entrée '{input_csv_path}' n'a pas été trouvé.")
        return # Utiliser return au lieu de exit()

    # Définir le dossier de sortie basé sur le fichier d'entrée
    output_dir = config.LISTES_OUTPUT_DIR # Utilise le chemin depuis config.py

    # Créer le dossier de sortie s'il n'existe pas
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n[Extract Leads] Mise à jour des listes dans : {output_dir.resolve()}")
    except OSError as e:
        print(f"[Extract Leads] Erreur lors de la création du dossier de sortie {output_dir}: {e}")
        return # Ne pas continuer si on ne peut pas créer le dossier

    # Initialiser les sets pour stocker les données uniques
    datasets = {
        "facebook": set(),
        "instagram": set(),
        "email": set(),
        "phone": set(),
    }

    # Lire les données existantes des fichiers de sortie
    print("[Extract Leads] Lecture des fichiers de sortie existants (si présents)...")
    # Renommer la variable de boucle pour éviter de masquer le module 'config'
    for key, file_config in output_files_config.items():
        filepath = output_dir / file_config["filename"]
        datasets[key] = read_existing_data(filepath, file_config["header"])
        print(f" - {file_config['filename']}: {len(datasets[key])} entrées existantes lues.")

    # Lire le fichier CSV d'entrée et extraire les données
    print(f"[Extract Leads] Lecture et traitement du fichier d'entrée : {input_csv_path.name}...")
    new_entries_count = {key: 0 for key in datasets}
    processed_rows = 0
    try:
        # Utiliser 'utf-8-sig' pour gérer le BOM potentiel
        with open(input_csv_path, 'r', newline='', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            # Vérifier si les colonnes nécessaires existent (plus souple avec .get())
            required_cols = [col for col in [facebook_col, instagram_col, email_col, phone_col] if col] # Ignore None/empty names
            missing_cols = [col for col in required_cols if col not in reader.fieldnames]
            if missing_cols:
                 print(f"[Extract Leads] Avertissement: Colonnes manquantes dans {input_csv_path.name}: {', '.join(missing_cols)}")
                 print(f"  Colonnes attendues: {required_cols}")
                 print(f"  Colonnes trouvées: {reader.fieldnames}")
                 # On continue quand même, .get() gérera les colonnes manquantes

            for row in reader:
                processed_rows += 1
                # Facebook
                fb_link = row.get(facebook_col, '').strip()
                if fb_link and fb_link.lower() not in ['not found', 'n/a', 'non trouvé']:
                    if fb_link not in datasets["facebook"]:
                        datasets["facebook"].add(fb_link)
                        new_entries_count["facebook"] += 1

                # Instagram
                ig_link = row.get(instagram_col, '').strip()
                if ig_link and ig_link.lower() not in ['not found', 'n/a', 'non trouvé']:
                     if ig_link not in datasets["instagram"]:
                        datasets["instagram"].add(ig_link)
                        new_entries_count["instagram"] += 1

                # Email
                email = row.get(email_col, '').strip()
                # Simple validation: non vide, pas 'not found', contient '@'
                if email and email.lower() not in ['not found', 'n/a', 'non trouvé'] and '@' in email:
                    if email not in datasets["email"]:
                        datasets["email"].add(email)
                        new_entries_count["email"] += 1

                # Téléphone
                phone_raw = row.get(phone_col, '').strip()
                formatted_phone = format_phone_number(phone_raw)
                if formatted_phone:
                    if formatted_phone not in datasets["phone"]:
                        datasets["phone"].add(formatted_phone)
                        new_entries_count["phone"] += 1

        print(f"[Extract Leads] Lecture de {processed_rows} lignes terminée.")
        for key, count in new_entries_count.items():
            print(f" - {count} nouvelles entrées uniques trouvées pour {key}.")

    except FileNotFoundError:
        print(f"[Extract Leads] Erreur : Le fichier d'entrée '{input_csv_path}' n'a pas été trouvé.")
        return
    except Exception as e:
        print(f"[Extract Leads] Une erreur est survenue lors de la lecture de {input_csv_path} (ligne ~{processed_rows+1}): {e}")
        import traceback
        traceback.print_exc() # Affiche plus de détails sur l'erreur
        return

    # Écrire les données mises à jour dans les fichiers CSV de sortie
    print("\n[Extract Leads] Écriture des fichiers de sortie mis à jour...")
    # Utiliser le même nom de variable renommé ici aussi
    for key, file_config in output_files_config.items():
        filepath = output_dir / file_config["filename"]
        write_data_to_csv(filepath, file_config["header"], datasets[key])

    print("\n[Extract Leads] Mise à jour des listes terminée !")

# Permet d'exécuter le script directement pour tester ou utiliser indépendamment
if __name__ == "__main__":
    print("Exécution de extract_leads.py en mode autonome...")
    # Vous pouvez décommenter la ligne suivante pour tester avec un chemin spécifique
    # main(input_file_path=r"chemin\vers\votre\leads.csv")
    main() # Utilise le chemin par défaut défini dans config.py
