#!/bin/bash

# Script d'installation et de configuration pour AlienScraper avec systemd

# --- ÉTAPE PRÉALABLE MANUELLE ---
# Ce script suppose qu'il est exécuté depuis la racine du dépôt AlienScraper.
# Assurez-vous d'avoir cloné le dépôt avant de lancer ce script :
# git clone <URL_DU_REPO> AlienScraper && cd AlienScraper
echo "--- Configuration d'AlienScraper ---"

# --- Vérification des droits sudo ---
if [[ $EUID -ne 0 ]]; then
    echo "ERREUR: Ce script doit être exécuté avec sudo."
    echo "Veuillez lancer avec : sudo bash $0"
    exit 1
fi

# --- Installation des dépendances système (Debian/Ubuntu) ---
echo ""
echo "Vérification et installation des dépendances système (apt)..."
apt-get update -q # -q pour moins de verbosité
# Vérifier si chromium-browser est disponible, sinon essayer chromium
if apt-cache show chromium-browser > /dev/null 2>&1; then
    CHROMIUM_PACKAGE="chromium-browser"
else
    CHROMIUM_PACKAGE="chromium"
fi
echo "Utilisation du paquet: $CHROMIUM_PACKAGE"
apt-get install -y git python3 python3-venv python3-pip redis-server xvfb "$CHROMIUM_PACKAGE"
if [ $? -ne 0 ]; then
    echo "ERREUR: Échec de l'installation des dépendances système via apt-get."
    exit 1
fi
echo "Dépendances système installées/vérifiées."

# --- Démarrage et activation de Redis ---
echo ""
echo "Activation et démarrage du service Redis..."
systemctl enable redis-server.service
systemctl start redis-server.service
if ! systemctl is-active --quiet redis-server.service; then
    echo "AVERTISSEMENT: Le service Redis n'a pas pu être démarré ou activé automatiquement."
    echo "Veuillez vérifier l'état de Redis avec 'sudo systemctl status redis-server.service'."
    # On continue quand même, mais le worker échouera si Redis n'est pas là
fi
echo "Service Redis activé et démarré (ou tentative effectuée)."

# --- Détection des informations ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_USER=$(logname) # Utilise l'utilisateur qui a lancé sudo
PROJECT_GROUP=$(id -gn "$PROJECT_USER")
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
XVFB_RUN_EXEC=$(which xvfb-run)

echo "Détection des informations :"
echo " - Répertoire du projet : $SCRIPT_DIR"
echo " - Utilisateur des services : $PROJECT_USER"
echo " - Groupe des services : $PROJECT_GROUP"
echo " - Exécutable xvfb-run : $XVFB_RUN_EXEC"

# Vérifier si xvfb-run a été trouvé
if [ -z "$XVFB_RUN_EXEC" ]; then
    echo "ERREUR: xvfb-run n'a pas été trouvé. Assurez-vous qu'il est installé (sudo apt install xvfb)."
    exit 1
fi

# --- Création de l'environnement virtuel et installation des dépendances Python ---
echo ""
echo "Création de l'environnement virtuel (.venv)..."

# Utiliser le chemin complet vers l'exécutable python3 de l'utilisateur $PROJECT_USER
PYTHON_SYSTEM_EXEC=$(sudo -u "$PROJECT_USER" which python3)

if [ -z "$PYTHON_SYSTEM_EXEC" ]; then
    echo "ERREUR: Impossible de trouver l'exécutable python3 pour l'utilisateur $PROJECT_USER."
    exit 1
fi

# Supprimer l'ancien venv avant de recréer (pour être sûr)
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "Suppression de l'ancien environnement virtuel..."
    sudo rm -rf "$SCRIPT_DIR/.venv"
fi

# Créer le venv en utilisant l'exécutable python3 de l'utilisateur et en tant que cet utilisateur
sudo -u "$PROJECT_USER" "$PYTHON_SYSTEM_EXEC" -m venv "$SCRIPT_DIR/.venv"

if [ $? -ne 0 ]; then
    echo "ERREUR: Échec de la création de l'environnement virtuel."
    exit 1
fi

PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python"
PIP_EXEC="$SCRIPT_DIR/.venv/bin/pip"
echo "Environnement virtuel créé. Exécutable Python : $PYTHON_EXEC"

# Vérifier si requirements.txt existe
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "ERREUR: Le fichier requirements.txt est introuvable dans $SCRIPT_DIR."
    exit 1
fi

echo "Installation des dépendances Python depuis $REQUIREMENTS_FILE..."
sudo -u "$PROJECT_USER" bash -c "\"$PIP_EXEC\" install -r \"$REQUIREMENTS_FILE\""
if [ $? -ne 0 ]; then
    echo "ERREUR: Échec de l'installation des dépendances Python via pip."
    exit 1
fi
echo "Dépendances Python installées."

# Vérifier si l'environnement virtuel existe
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "ERREUR: L'environnement virtuel ou l'exécutable Python n'a pas été trouvé à $PYTHON_EXEC."
    exit 1
fi

# --- Demande de la clé API Google ---
echo ""
read -p "Veuillez entrer votre clé API Google (GOOGLE_API_KEY) : " GOOGLE_API_KEY
echo "" # Nouvelle ligne après la saisie masquée

if [ -z "$GOOGLE_API_KEY" ]; then
    echo "ERREUR: La clé API Google ne peut pas être vide."
    exit 1
fi

# --- Génération et installation des fichiers systemd ---
echo ""
echo "Génération et installation des fichiers de service systemd..."

TEMPLATE_WORKER="$SCRIPT_DIR/deploy/alienscraper-worker.service.template"
TEMPLATE_APP="$SCRIPT_DIR/deploy/alienscraper-app.service.template"
TARGET_WORKER="/etc/systemd/system/alienscraper-worker.service"
TARGET_APP="/etc/systemd/system/alienscraper-app.service"

# Vérifier si les templates existent
if [ ! -d "$SCRIPT_DIR/deploy" ] || [ ! -f "$TEMPLATE_WORKER" ] || [ ! -f "$TEMPLATE_APP" ]; then
    echo "ERREUR: Fichiers templates non trouvés dans $SCRIPT_DIR/deploy/"
    exit 1
fi

# Fonction pour remplacer les placeholders et créer le fichier service
create_service_file() {
    local template_file=$1
    local target_file=$2
    echo "  Création de $target_file à partir de $template_file..."
    ESCAPED_SCRIPT_DIR=$(printf '%s\n' "$SCRIPT_DIR" | sed -e 's/[\/&]/\\&/g')
    ESCAPED_PYTHON_EXEC=$(printf '%s\n' "$PYTHON_EXEC" | sed -e 's/[\/&]/\\&/g')
    ESCAPED_XVFB_RUN_EXEC=$(printf '%s\n' "$XVFB_RUN_EXEC" | sed -e 's/[\/&]/\\&/g')

    sed -e "s/__USER__/$PROJECT_USER/g" \
        -e "s/__GROUP__/$PROJECT_GROUP/g" \
        -e "s/__WORKING_DIR__/$ESCAPED_SCRIPT_DIR/g" \
        -e "s/__PYTHON_EXEC__/$ESCAPED_PYTHON_EXEC/g" \
        -e "s/__XVFB_RUN_EXEC__/$ESCAPED_XVFB_RUN_EXEC/g" \
        -e "s/__GOOGLE_API_KEY__/$GOOGLE_API_KEY/g" \
        "$template_file" > "$target_file"
    echo "  Fichier $target_file créé."
}

create_service_file "$TEMPLATE_WORKER" "$TARGET_WORKER"
create_service_file "$TEMPLATE_APP" "$TARGET_APP"

echo "Rechargement de systemd et gestion des services..."
systemctl daemon-reload
echo "Activation des services pour démarrage automatique..."
systemctl enable alienscraper-worker.service
systemctl enable alienscraper-app.service
echo "Démarrage des services..."
systemctl start alienscraper-worker.service
systemctl start alienscraper-app.service

echo "Installation et configuration terminées."
echo "Vous pouvez maintenant accéder à l'application via http://localhost:5000"
echo "ou via l'IP de votre serveur si vous êtes sur un VPS."