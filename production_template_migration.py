# file: app_streamlit_jira.py
import streamlit as st
from jira import JIRA, JIRAError
from dotenv import load_dotenv
import os
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from datetime import timedelta
import pandas as pd
import plotly.express as px

# Load .env if present
load_dotenv()

# -------------------
# Helpers
# -------------------
def create_jira_connection(url: str, username: str, token_or_password: str, cloud=True):
    """
    Retourne un objet JIRA connecté ou lève une exception en cas d'erreur.
    - cloud=True : utilise (username, api_token) (Atlassian Cloud)
    - cloud=False: utilise (username, password) (Server / Data Center)
    """
    options = {"server": url}
    try:
        jira = JIRA(options=options, basic_auth=(username, token_or_password))
        jira.myself()  # Test simple pour valider la connexion
        return jira
    except JIRAError as e:
        raise e

# ============================================================
# 🔐 LOGIN Jira (Atlassian Cloud) — Service Account Version
# ============================================================

def jira_login_page():

    # If already authenticated, skip login UI
    if st.session_state.get("connected", False):
        return True

    # ---------- UI STYLE ----------
    st.markdown("""
        <style>
            body {
                background: linear-gradient(135deg, #141e30, #243b55);
            }
            .login-box {
                background-color: rgba(255, 255, 255, 0.06);
                padding: 40px;
                border-radius: 16px;
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                box-shadow: 0 8px 20px rgba(0,0,0,0.25);
            }
            .login-title {
                color: #ffffff;
                font-size: 32px;
                font-weight: 700;
                text-align: center;
                margin-bottom: 10px;
            }
            .login-sub {
                color: #cfd3d6;
                text-align: center;
                margin-bottom: 30px;
            }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top: 80px;'></div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)

        st.markdown("<div class='login-title'>🔗 Jira Service Account Login</div>", unsafe_allow_html=True)
        st.markdown("<div class='login-sub'>Entrez les informations de votre compte de service Atlassian</div>", unsafe_allow_html=True)

        # Default env vars (for local dev or Streamlit Cloud)
        default_url = os.getenv("JIRA_URL", "")
        default_email = os.getenv("JIRA_EMAIL", "")
        default_token = os.getenv("JIRA_API_TOKEN", "")

        # Input Fields
        jira_url = st.text_input("🔗 Jira URL", value=default_url, placeholder="https://yourinstance.atlassian.net")
        username = st.text_input("📧 Service Account Email", value=default_email)
        token = st.text_input("🔑 API Token", value=default_token, type="password")

        cloud_mode = True  # Always Cloud for service accounts

        submit = st.button("Se connecter", use_container_width=True)

        if submit:
            st.session_state.last_error = None

            if not jira_url or not username or not token:
                st.session_state.last_error = "Tous les champs doivent être remplis."
                st.error(st.session_state.last_error)
                st.session_state.connected = False
                st.session_state.jira_client = None

            else:
                try:
                    client = create_jira_connection(
                        jira_url.strip(),
                        username.strip(),
                        token.strip(),
                        cloud=cloud_mode
                    )
                    st.session_state.jira_client = client
                    st.session_state.connected = True
                    st.session_state.username = username.strip()
                    st.session_state.token = token.strip()

                    st.success("Connexion réussie ✔️")
                    st.rerun()

                except Exception as e:
                    st.session_state.jira_client = None
                    st.session_state.connected = False
                    st.session_state.last_error = f"Erreur de connexion : {e}"
                    st.error(st.session_state.last_error)

        # Display last error block
        if st.session_state.get("last_error"):
            st.write("Dernière erreur :")
            st.code(st.session_state.last_error)

        st.markdown("</div>", unsafe_allow_html=True)

    return False


# ============================================================
# 🧩 REQUIRE LOGIN BEFORE ACCESS
# ============================================================

if not jira_login_page():
    st.stop()


def safe_get_projects(jira):
    try:
        return jira.projects()
    except Exception:
        return []

def rest_api_get(base_url: str, path: str, auth: HTTPBasicAuth, params: dict = None):
    """
    Appel GET vers l'API Jira v3.
    """
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json"}
    resp = requests.get(url, headers=headers, auth=auth, params=params, timeout=30)
    if resp.status_code >= 400:
        raise Exception(f"API error {resp.status_code}: {resp.text}")
    return resp.json()

def get_jql_template_epic(base_url: str, auth: HTTPBasicAuth, maxResults=50):

    jql = "project = PPT AND issuetype = Epic ORDER BY created DESC"

    params = {
        "jql": jql,
        "startAt": 0,
        "maxResults": 50,
        "fields": "summary,description,status,assignee,customfield_10015"
    }

    url = f"{base_url}/rest/api/3/search/jql"
    resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, params=params)

    if resp.status_code == 200:
        data = resp.json()
        issues = data.get("issues", [])
        for issue in issues:
            key = issue["key"]
            fields = issue["fields"]
            summary = fields.get("summary")
            status = fields.get("status", {}).get("name")
            start_date = fields.get("customfield_10015")
            print(f"Issue {key}: {summary} — status: {status}")
    else:
        print(f"Erreur HTTP {resp.status_code}: {resp.text}")

    return data.get("issues", [])

def get_child_issues_for_epic(base_url: str, auth: HTTPBasicAuth, epic_key: str, maxResults=100):
    jql = f'"parent" = {epic_key} ORDER BY startdate ASC'
    params = {
        "jql": jql,
        "maxResults": maxResults,
        "fields": "summary,status,assignee,reporter,description,customfield_10015,duedate,issuelinks,issuetype"
    }
    url = f"{base_url}/rest/api/3/search/jql"
    resp = requests.get(url, headers={"Accept": "application/json"}, auth=auth, params=params)

    if resp.status_code == 200:
        data = resp.json()
        issues = data.get("issues", [])
        for issue in issues:
            key = issue["key"]
            fields = issue["fields"]
            summary = fields.get("summary")
            status = fields.get("status", {}).get("name")
            start_date = fields.get("customfield_10015")  # Start date
            due_date = fields.get("duedate")              # Due date
            links = fields.get("issuelinks", [])
            print(f"Issue {key}: {summary} — status: {status}")
    else:
        print(f"Erreur HTTP {resp.status_code}: {resp.text}")

    issues = data.get("issues", [])
    ordre_issues = ordre_child_issues(issues)
    return ordre_issues

def ordre_child_issues(issues):
    """
    Trie une liste d'issues par customfield_10015 (start date) croissant.
    Les issues sans start date sont placées à la fin.
    """
    def get_start_date(issue):
        start = issue.get("fields", {}).get("customfield_10015")
        if start:
            try:
                return datetime.fromisoformat(str(start))
            except Exception:
                return datetime.max  # Si format invalide, les mettre à la fin
        else:
            return datetime.max  # Si pas de start date, les mettre à la fin

    return sorted(issues, key=get_start_date)


def adf_to_markdown(adf):
    """Convertit un document Atlassian ADF en markdown affichable."""
    if not adf:
        return ""

    md = ""

    for block in adf.get("content", []):
        btype = block.get("type")

        # Paragraphe
        if btype == "paragraph":
            line = ""
            for c in block.get("content", []):
                if c.get("type") == "text":
                    line += c.get("text", "")
            md += line + "\n\n"

        # Liste à puce
        elif btype == "bulletList":
            for item in block.get("content", []):
                for p in item.get("content", []):
                    for c in p.get("content", []):
                        if c.get("type") == "text":
                            md += f"- {c['text']}\n"
            md += "\n"

    return md.strip()

def to_datetime_safe(value):
    
    if not value:  # None, '', etc.
        return None
    try:
        print(datetime.fromisoformat(str(value)))
        return datetime.fromisoformat(str(value))
    except Exception as e:
        print(f"Impossible de convertir '{value}' ({type(value)}): {e}")
        return None


# -------------------
# Streamlit UI
# -------------------
st.set_page_config(page_title="Epic migration manager", layout="wide")
st.title("Epic Migration Manager")

# -------------------
# Session state
# -------------------
if "jira_client" not in st.session_state:
    st.session_state.jira_client = None
if "connected" not in st.session_state:
    st.session_state.connected = False
if "last_error" not in st.session_state:
    st.session_state.last_error = None
if "login_attempt" not in st.session_state:
    st.session_state.login_attempt = False
if "epics_list" not in st.session_state:
    st.session_state.epics_list = []


st.header("Configure the Epic migration")

# Bouton de déconnexion
if st.button("Disconnect"):
    st.session_state.connected = False
    st.session_state.jira_client = None
    st.session_state.login_attempt = False
    st.session_state.epics_list = []
    st.experimental_rerun = False  # ne plus utiliser, Streamlit recalculera automatiquement
    st.info("Disconnected, go back to connection page")

if st.session_state.connected and st.session_state.jira_client:
    jira = st.session_state.jira_client
    base_url = st.session_state.jira_client.server_url
    auth = HTTPBasicAuth(st.session_state.username, st.session_state.token)

    # Liste des projets
    projects = safe_get_projects(jira)

    #--- Start filter projetcs by category
    filtered_projects = []
    for p in projects:
        cat = None
        if hasattr(p, "projectCategory") and p.projectCategory:
            # Try both formats (Jira Python API OR REST dict)
            if hasattr(p.projectCategory, "name"):
                cat = p.projectCategory.name
            elif isinstance(p.projectCategory, dict):
                cat = p.projectCategory.get("name")

        if cat == "Production":
            filtered_projects.append(p)

    if not filtered_projects:
        st.info("Aucun projet dans la catégorie Production.")
        st.stop()

    #--- End filter projetcs by category

    projects_map = {p.key: p for p in filtered_projects}
    project_keys = list(projects_map.keys())

    project_labels = {f"{p.key} – {p.name}": p.key for p in filtered_projects}

    if not project_keys:
        st.info("Aucun projet trouvé ou pas accès.")
    else:

        selected_label = st.selectbox(
            "Select the target project",
            options=list(project_labels.keys())
        )
        
        selected_key = project_labels[selected_label]
        st.write(f"Selected Project : **{selected_key}** — {projects_map[selected_key].name}")

        st.markdown("---")
        st.subheader("Template selection")

        try:
            with st.spinner(""):
                epics = get_jql_template_epic(base_url, auth, maxResults=100)
            if not epics:
                st.info("Aucun EPIC trouvé pour ce JQL.")
                st.session_state.epics_list = []
            else:
                epics_map = {
                    e["key"]: {
                        "summary": e["fields"].get("summary", ""),
                        "description": e["fields"].get("description", "")
                    } 
                    for e in epics
                }
                st.session_state.epics_list = epics_map
        except Exception as e:
            st.error(f"Erreur en récupérant les Epics : {e}")
            st.session_state.epics_list = []

        if st.session_state.epics_list:
            epics_map = st.session_state.epics_list
            epic_choices = list(epics_map.keys())
            selected_epic = st.selectbox(
                "Select the process you want to migrate",
                options=epic_choices,
                format_func=lambda k: epics_map[k]["summary"]
            )
            selected_epic_data = epics_map[selected_epic]
            st.write(f"Selected Process: {selected_epic_data['summary']}")
            st.markdown("### Process Description")

            description_adf = selected_epic_data["description"] 
            markdown_description = adf_to_markdown(description_adf)

            st.markdown(markdown_description)

            # 1. Choisir la start date finale
            new_start_date = st.date_input(
                "Process start in your project",
                value=datetime.today()
            )

            if st.button("Show process issues"):
                try:
                    with st.spinner("Collecting issues..."):
                        child_issues = get_child_issues_for_epic(base_url, auth, selected_epic, maxResults=200)

                    if not child_issues:
                        st.info(f"No issue found for : {selected_epic}.")
                    else:
                        gantt_data = []

                        # --------------------------------------------------------------
                        # 🔵 AJOUT DE L'ÉPIC AU DIAGRAMME DE GANTT
                        # --------------------------------------------------------------

                        # Récupération de l’EPIC d’origine
                        epic_issue = jira.issue(selected_epic)
                        epic_fields = epic_issue.fields   

            

                        # Dates EPIC originales
                        epic_start_orig = epic_fields.customfield_10015
                        epic_due_orig = epic_fields.duedate

                        if epic_start_orig:
                            epic_start_dt = to_datetime_safe(epic_start_orig)
                        else:
                            epic_start_dt = None

                        if epic_due_orig:
                            epic_due_dt = to_datetime_safe(epic_due_orig)
                        else:
                            epic_due_dt = None

                        # 🧠 Calcul delta par rapport à new_start_date
                        if epic_start_dt:
                            delta_epic = new_start_date - epic_start_dt.date()
                        else:
                            delta_epic = timedelta(days=0)

                        # Nouvelle date Epic pour le Gantt
                        epic_start_gantt = (epic_start_dt + delta_epic) if epic_start_dt else new_start_date
                        epic_due_gantt = (epic_due_dt + delta_epic) if epic_due_dt else (epic_start_gantt + timedelta(days=7))



                        # 🏷️ Calcul durée Epic
                        if epic_start_orig and epic_due_orig:
                            sd = epic_start_gantt
                            ed = epic_due_gantt
                            duration_epic = (ed - sd).days

                            gantt_data.insert(0, {   # On met l’Epic en PREMIER
                                "Task": f"{selected_epic} — {selected_epic_data['summary']}",
                                "Start": epic_start_gantt,
                                "Finish": epic_due_gantt,
                                "Duration": duration_epic,
                                "Type": "Epic"
                            })




                        for ch in child_issues:
                            key = ch.get("key")
                            f = ch.get("fields", {})



                            start_orig = f.get("customfield_10015")
                            due_orig = f.get("duedate")

                            if start_orig:
                                start_dt = datetime.fromisoformat(start_orig.replace("Z", ""))
                                start_gantt = start_dt + delta_epic
                            else:
                                start_gantt = None

                            if start_orig and due_orig:
                                due_dt = datetime.fromisoformat(due_orig.replace("Z", ""))
                                due_gantt = due_dt + delta_epic
                            else:
                                due_gantt = None

                            start = start_gantt   # Start date
                            end = due_gantt            # Due date

                            summary = f.get("summary", "—")
                            issue_type = f.get("issuetype", {}).get("name", "—")

                            if start and end:
                                try:

                                    duration_days = (end - start).days
                                except:
                                    duration_days = None

                                gantt_data.append({
                                    "Task": f"{key} — {summary}",
                                    "Start": start,
                                    "Finish": end,
                                    "Duration": duration_days,
                                    "Type": issue_type,
                                    "Epic": selected_epic_data["summary"]  # 🔥 On ajoute l'EPIC ici
                                })

                        df_gantt = pd.DataFrame(gantt_data)

                        if not df_gantt.empty:
                            
                            task_name = "Task"

                            # 🔹 Format Duration → "47 Days"
                            df_gantt["DurationLabel"] = df_gantt["Duration"].apply(
                                lambda d: f"({d} Days)" if d is not None else ""
                            )

                            st.subheader("Process Gant Diagram")

                            fig = px.timeline(
                                df_gantt,
                                x_start="Start",
                                x_end="Finish",
                                y="Task",
                                color="Type",
                                text="DurationLabel"     # 🏷️ Afficher "X Days" dans la barre
                            )

                            fig.update_traces(textposition="inside", insidetextanchor="middle")
                            fig.update_yaxes(autorange="max reversed")

                            st.plotly_chart(fig, use_container_width=True)

                        else:
                            st.info("No tasks has Start Date + Due Date.")




                except Exception as e:
                    st.error(f"Error why gathering epic : {e}")
else:
    st.info("Connect first to gather projects and issues")

# ---------------------------------------------------------
# SECTION MIGRATION DU TEMPLATE
# ---------------------------------------------------------
st.markdown("---")
st.subheader("Template Migration in the selected project")

# 2. Bouton migration
if st.button("Migrate Template"):
    try:
        st.write("📌 Migration under process...")

        # Récupération de l’EPIC d’origine
        epic_issue = jira.issue(selected_epic)
        epic_fields = epic_issue.fields
        
        # Dates EPIC origine
        epic_start = epic_fields.customfield_10015
        epic_due = epic_fields.duedate
        epic_duration = 0

        # Conversion si existe
        if epic_start:
            epic_start_dt = datetime.fromisoformat(epic_start.replace("Z", ""))
            if epic_due:
                epic_due_dt = datetime.fromisoformat(epic_due.replace("Z", ""))
                epic_duration = epic_due_dt - epic_start_dt
            else:
                epic_due_dt = None
        else:
            epic_start_dt = None

        # ---------------------------------------------------------
        # 1. Créer le nouvel EPIC dans le projet sélectionné
        # ---------------------------------------------------------
        new_epic_data = {
            "project": {"key": selected_key},
            "summary": epic_fields.summary,
            "description": epic_fields.description,
            "issuetype": {"name": "Epic"},
            "customfield_10015": new_start_date.strftime("%Y-%m-%d"),
            "duedate": (new_start_date + epic_duration).strftime("%Y-%m-%d")
        }

        new_epic = jira.create_issue(fields=new_epic_data)
        st.success(f"New EPIC created : {new_epic.key}")


        

        # ---------------------------------------------------------
        # 2. Recréer chaque enfant avec delta date
        # ---------------------------------------------------------
        

        child_issues = get_child_issues_for_epic(base_url, auth, selected_epic, maxResults=200)     
        child_links_map  = {}
        old_to_new_keys = {}

        for ch in child_issues:
            ch_key = ch["key"]
            fields = ch["fields"]

            #--- Start stock links

            original_links = []

            for link in fields.get("issuelinks", []):
                if "outwardIssue" in link:
                    original_links.append({
                        "type": link["type"]["name"],
                        "direction": "outward",
                        "key": link["outwardIssue"]["key"]
                    })
                elif "inwardIssue" in link:
                    original_links.append({
                        "type": link["type"]["name"],
                        "direction": "inward",
                        "key": link["inwardIssue"]["key"]
                    })
            
            child_links_map[ch_key] = original_links

            #--- End stock links 

            orig_start = fields.get("customfield_10015")
            orig_due = fields.get("duedate")

            # Calcul du delta si possible
            if epic_start_dt and orig_start:
                child_start_dt = datetime.fromisoformat(orig_start.replace("Z", ""))
                delta_days = (child_start_dt - epic_start_dt).days
                new_child_start = new_start_date + timedelta(days=delta_days)
            else:
                new_child_start = None

            # Nouvelle date de fin
            if orig_start and orig_due:
                start_dt = datetime.fromisoformat(orig_start.replace("Z", ""))
                due_dt = datetime.fromisoformat(orig_due.replace("Z", ""))
                duration = (due_dt - start_dt).days
                new_child_due = (new_child_start + timedelta(days=duration)) if new_child_start else None
            else:
                new_child_due = None

            # 1️⃣ Obtenir les types de ticket du projet cible
            issue_types = jira.project(selected_key).issueTypes  # liste d'objets IssueType

            # 2️⃣ Trouver l'ID correspondant au type de l'enfant
            child_type_name = fields.get("issuetype", {}).get("name")  # "Task", "Bug", etc.
            child_type_id = None
            for itype in issue_types:
                if itype.name == child_type_name:
                    child_type_id = itype.id
                    break

            if not child_type_id:
                raise Exception(f"Error while migrating '{child_type_name}' in the project {selected_key}")


            # Création du ticket enfant dans le nouveau projet
            create_payload = {
                "project": {"key": selected_key},
                "summary": fields.get("summary"),
                "description": fields.get("description"),
                "issuetype": {"id": child_type_id},
                "customfield_10014": new_epic.key,  # Lien vers l'epic parent
            }

            # Ajouter dates
            if new_child_start:
                create_payload["customfield_10015"] = new_child_start.strftime("%Y-%m-%d")
            if new_child_due:
                create_payload["duedate"] = new_child_due.strftime("%Y-%m-%d")

            # Création
            new_issue = jira.create_issue(fields=create_payload)

            old_to_new_keys[ch_key] = new_issue.key

            st.write(f"Task migrated: {new_issue.key}")

        for old_key, links in child_links_map.items():
            new_key = old_to_new_keys.get(old_key)
            if not new_key:
                continue
            for link in links:
                linked_old_key = link["key"]
                linked_new_key = old_to_new_keys.get(linked_old_key)
                if not linked_new_key:
                    continue  # ignore les liens vers des issues hors template
                if link["direction"] == "outward":
                    jira.create_issue_link(type=link["type"], inwardIssue=new_key, outwardIssue=linked_new_key)
                else:
                    jira.create_issue_link(type=link["type"], inwardIssue=linked_new_key, outwardIssue=new_key)
                    
        st.success("Successful migration!")

    except Exception as e:
        st.error(f"Error while migrating : {e}")


st.markdown("---")
st.caption("Info: You can configure your atlassian api token here: https://id.atlassian.com/manage/api-tokens")
